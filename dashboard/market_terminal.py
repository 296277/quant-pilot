"""Market-terminal services for the local research dashboard.

Public endpoints are used for research snapshots only. Results are cached on
disk so a transient upstream failure does not blank the dashboard. No broker
account or order endpoint is present in this module.
"""

from __future__ import annotations

import json
import math
import re
import time
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from dashboard.strategy_factory import Costs, build_candidate_ledger, generate_candidates
from quant_trading.market_data import fetch_tencent_daily


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = PROJECT_ROOT / "data" / "processed" / "terminal"
SNAPSHOT_FILE = STATE_ROOT / "market_snapshot.json"
INDICES_FILE = STATE_ROOT / "indices_snapshot.json"
LIMIT_POOL_FILE = STATE_ROOT / "limit_pool_snapshot.json"
WATCHLIST_FILE = STATE_ROOT / "watchlist.json"
MONITOR_RULES_FILE = STATE_ROOT / "monitor_rules.json"
MONITOR_EVENTS_FILE = STATE_ROOT / "monitor_events.json"
SNAPSHOT_TTL_SECONDS = 90
INDICES_TTL_SECONDS = 300
SNAPSHOT_PAGE_WORKERS = 2
SNAPSHOT_PAGE_ATTEMPTS = 4
_SNAPSHOT_REFRESH_LOCK = threading.Lock()
_INDICES_REFRESH_LOCK = threading.Lock()
_LIMIT_POOL_REFRESH_LOCK = threading.Lock()
INDICES_SPEC = [("sh000001", "上证指数"), ("sz399001", "深证成指"), ("sz399006", "创业板指"), ("sh000688", "科创50")]
TENCENT_MARKET_SYMBOLS = (
    "sh601398", "sh601318", "sh600036", "sh600900", "sh601088",
    "sh688256", "sh603019", "sz000977", "sz300308", "sz002230",
    "sh688981", "sh603501", "sz002371", "sh688012", "sh600584",
    "sz300750", "sz002594", "sh601012", "sz300274", "sz002129",
    "sh688017", "sz002472", "sh603662", "sz300124", "sz002747",
    "sh600276", "sz300760", "sh603259", "sz000661", "sz002422",
    "sz002085", "sz001696", "sh688297", "sh600879", "sz002036",
)


STRATEGY_LABELS = {
    "adaptive_trend": "自适应趋势",
    "channel_breakout": "通道突破",
    "supertrend_adx": "SuperTrend + ADX",
    "turtle_atr": "海龟突破 + ATR",
    "bollinger_rsi": "布林带 + RSI",
    "macd_volume": "MACD + 成交量",
    "squeeze_breakout": "波动率挤压",
    "multi_timeframe": "多周期趋势",
    "regime_adaptive": "状态自适应",
    "signal_voting": "多信号投票",
}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _http_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("gb18030", errors="replace")


def _upstream_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "remote end closed" in lowered or "connection reset" in lowered:
        return "上游暂时断开连接，可能触发了访问频率限制"
    if "timed out" in lowered or "timeout" in lowered:
        return "上游请求超时"
    return message or exc.__class__.__name__


def _stock_symbol(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return f"bj{code}"
    return f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def fetch_market_snapshot(*, force: bool = False) -> dict[str, Any]:
    requested_at = time.time()
    cached = _read_json(SNAPSHOT_FILE, {})
    if not force and cached and time.time() - float(cached.get("epoch", 0)) < SNAPSHOT_TTL_SECONDS:
        return cached
    with _SNAPSHOT_REFRESH_LOCK:
        cached = _read_json(SNAPSHOT_FILE, {})
        cache_epoch = float(cached.get("epoch", 0)) if cached else 0
        if cached and (
            (not force and time.time() - cache_epoch < SNAPSHOT_TTL_SECONDS)
            or cache_epoch >= requested_at
        ):
            return cached
        return _refresh_market_snapshot(cached)


def _parse_tencent_quote(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r'^v_([a-z0-9]+)="(.*)";\s*$', line.strip(), re.IGNORECASE)
        if not match:
            continue
        symbol = match.group(1).lower()
        fields = match.group(2).split("~")
        if len(fields) < 39 or not fields[2].isdigit():
            continue
        try:
            amount_parts = fields[35].split("/")
            rows.append({
                "symbol": symbol,
                "code": fields[2],
                "name": fields[1] or fields[2],
                "price": _number(fields[3]),
                "change": _number(fields[32]) / 100,
                "change_value": _number(fields[31]),
                "volume": _number(fields[6]),
                "amount": _number(amount_parts[2] if len(amount_parts) > 2 else 0),
                "turnover": _number(fields[38]) / 100,
                "volume_ratio": 0,
                "high": _number(fields[33]),
                "low": _number(fields[34]),
                "open": _number(fields[5]),
                "previous_close": _number(fields[4]),
                "market_cap": 0,
                "float_cap": 0,
            })
        except (IndexError, ValueError, TypeError):
            continue
    return [row for row in rows if row["price"] > 0]


def _refresh_tencent_snapshot() -> dict[str, Any]:
    url = "https://qt.gtimg.cn/q=" + ",".join(TENCENT_MARKET_SYMBOLS)
    rows = _parse_tencent_quote(_http_text(url, timeout=12))
    if not rows:
        raise RuntimeError("腾讯未返回可用市场报价")
    return {
        "epoch": time.time(),
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "source": "腾讯公开报价（项目观察池）",
        "source_scope": "项目配置的 A 股观察池，不宣称全市场覆盖",
        "stale": False,
        "total": len(rows),
        "items": rows,
    }


def _refresh_market_snapshot(cached: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    try:
        result = _refresh_tencent_snapshot()
        _write_json(SNAPSHOT_FILE, result)
        return result
    except Exception as exc:
        errors.append(f"腾讯：{_upstream_error_message(exc)}")
    try:
        result = _refresh_eastmoney_snapshot()
        result["source_fallback"] = "东方财富备用源"
        _write_json(SNAPSHOT_FILE, result)
        return result
    except Exception as exc:
        errors.append(f"东方财富：{_upstream_error_message(exc)}")
    if cached:
        cached["stale"] = True
        cached["warning"] = "实时刷新暂不可用，已保留上次快照。" + "；".join(errors) + "，请稍后再试。"
        return cached
    raise RuntimeError("；".join(errors))


def _refresh_eastmoney_snapshot() -> dict[str, Any]:
    parameters = {
        "pn": 1,
        "pz": 100,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f4,f5,f6,f8,f10,f15,f16,f17,f18,f20,f21",
    }
    url = "https://push2.eastmoney.com/api/qt/clist/get?" + urllib.parse.urlencode(parameters)
    try:
        payload = None
        last_error: Exception | None = None
        for attempt in range(SNAPSHOT_PAGE_ATTEMPTS):
            try:
                payload = _http_json(url)
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.6 * (2**attempt))
        if payload is None:
            raise last_error or RuntimeError("市场快照请求失败")
        total = int((payload.get("data") or {}).get("total") or 0)
        first_page = list((payload.get("data") or {}).get("diff") or [])
        page_size = len(first_page) or int(parameters["pz"])
        page_count = max(1, math.ceil(total / page_size))
        all_diff = first_page
        if page_count > 1:
            def fetch_page(page: int) -> list[dict[str, Any]]:
                page_parameters = dict(parameters)
                page_parameters["pn"] = page
                page_url = "https://push2.eastmoney.com/api/qt/clist/get?" + urllib.parse.urlencode(page_parameters)
                error: Exception | None = None
                for page_attempt in range(SNAPSHOT_PAGE_ATTEMPTS):
                    try:
                        page_payload = _http_json(page_url)
                        return list((page_payload.get("data") or {}).get("diff") or [])
                    except Exception as exc:
                        error = exc
                        time.sleep(0.5 * (2**page_attempt))
                raise error or RuntimeError(f"市场快照第 {page} 页失败")

            # The public endpoint closes bursty connections. Keep pagination deliberately
            # conservative and coalesce concurrent dashboard refreshes with the lock above.
            with ThreadPoolExecutor(max_workers=SNAPSHOT_PAGE_WORKERS) as executor:
                futures = {executor.submit(fetch_page, page): page for page in range(2, page_count + 1)}
                pages: dict[int, list[dict[str, Any]]] = {}
                for future in as_completed(futures):
                    pages[futures[future]] = future.result()
            for page in range(2, page_count + 1):
                all_diff.extend(pages.get(page, []))
        rows = []
        for item in all_diff:
            code = str(item.get("f12") or "")
            if len(code) != 6:
                continue
            rows.append(
                {
                    "symbol": _stock_symbol(code),
                    "code": code,
                    "name": str(item.get("f14") or code),
                    "price": _number(item.get("f2")),
                    "change": _number(item.get("f3")) / 100,
                    "change_value": _number(item.get("f4")),
                    "volume": _number(item.get("f5")),
                    "amount": _number(item.get("f6")),
                    "turnover": _number(item.get("f8")) / 100,
                    "volume_ratio": _number(item.get("f10")),
                    "high": _number(item.get("f15")),
                    "low": _number(item.get("f16")),
                    "open": _number(item.get("f17")),
                    "previous_close": _number(item.get("f18")),
                    "market_cap": _number(item.get("f20")),
                    "float_cap": _number(item.get("f21")),
                }
            )
        if not rows:
            raise RuntimeError("东方财富未返回可用市场快照")
        result = {
            "epoch": time.time(),
            "retrieved_at": datetime.now().isoformat(timespec="seconds"),
            "source": "东方财富公开市场快照",
            "stale": False,
            "total": total or len(rows),
            "items": rows,
        }
        _write_json(SNAPSHOT_FILE, result)
        return result
    except Exception:
        raise


def _index_summary(symbol: str, name: str) -> dict[str, Any]:
    data = fetch_tencent_daily(symbol, 120, timeout=8)
    close = data["close"].astype(float)
    return {
        "symbol": symbol,
        "name": name,
        "price": float(close.iloc[-1]),
        "change": float(close.pct_change().iloc[-1]),
        "ma5": float(close.rolling(5).mean().iloc[-1]),
        "ma20": float(close.rolling(20).mean().iloc[-1]),
        "ma60": float(close.rolling(60).mean().iloc[-1]),
        "high60": float(close.rolling(60).max().iloc[-1]),
        "low60": float(close.rolling(60).min().iloc[-1]),
        "series": [{"date": str(index.date()), "close": float(value)} for index, value in close.tail(60).items()],
    }


def index_dashboard(*, force: bool = False) -> dict[str, Any]:
    requested_at = time.time()
    cached = _read_json(INDICES_FILE, {})
    if not force and cached and time.time() - float(cached.get("epoch", 0)) < INDICES_TTL_SECONDS:
        return cached
    with _INDICES_REFRESH_LOCK:
        cached = _read_json(INDICES_FILE, {})
        cache_epoch = float(cached.get("epoch", 0)) if cached else 0
        if cached and (
            (not force and time.time() - cache_epoch < INDICES_TTL_SECONDS)
            or cache_epoch >= requested_at
        ):
            return cached
        indices = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_index_summary, symbol, name): (symbol, name) for symbol, name in INDICES_SPEC}
            for future in as_completed(futures):
                symbol, name = futures[future]
                try:
                    indices.append(future.result())
                except Exception as exc:
                    indices.append({"symbol": symbol, "name": name, "error": str(exc)})
        order = {symbol: index for index, (symbol, _) in enumerate(INDICES_SPEC)}
        indices.sort(key=lambda item: order.get(item["symbol"], 99))
        usable = [item for item in indices if not item.get("error")]
        if not usable and cached:
            cached["stale"] = True
            cached["warning"] = "指数行情暂时不可用，已显示上次快照。"
            return cached
        result = {
            "epoch": time.time(),
            "as_of": datetime.now().isoformat(timespec="seconds"),
            "source": "腾讯公开日线",
            "stale": False,
            "indices": indices,
        }
        _write_json(INDICES_FILE, result)
        return result


def _snapshot_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["symbol"]: item for item in snapshot.get("items", [])}


def _configured_groups(universe: dict[str, Any], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lookup = _snapshot_map(snapshot)
    groups = []
    for group in universe.get("stocks", []):
        members = []
        for asset in group.get("assets", []):
            market = lookup.get(asset["symbol"])
            if market:
                members.append({**asset, **market})
        if not members:
            continue
        changes = [item["change"] for item in members]
        groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "count": len(members),
                "change": float(np.mean(changes)),
                "median_change": float(np.median(changes)),
                "up": sum(value > 0 for value in changes),
                "down": sum(value < 0 for value in changes),
                "amount": sum(item["amount"] for item in members),
                "turnover": float(np.mean([item["turnover"] for item in members])),
                "volume_ratio": float(np.mean([item["volume_ratio"] for item in members])),
                "leaders": sorted(members, key=lambda item: item["change"], reverse=True)[:3],
                "laggards": sorted(members, key=lambda item: item["change"])[:3],
                "members": sorted(members, key=lambda item: item["change"], reverse=True),
            }
        )
    return groups


def market_dashboard(universe: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    snapshot = fetch_market_snapshot(force=force)
    items = snapshot["items"]
    coverage = len(items) / max(int(snapshot.get("total") or len(items)), 1)
    complete = coverage >= 0.95
    changes = np.array([item["change"] for item in items], dtype=float)
    bins = [(-np.inf, -0.05), (-0.05, -0.03), (-0.03, -0.01), (-0.01, 0), (0, 0.01), (0.01, 0.03), (0.03, 0.05), (0.05, np.inf)]
    breadth = [{"label": label, "count": int(((changes > low) & (changes <= high)).sum())} for (low, high), label in zip(bins, ["<-5%", "-5~-3%", "-3~-1%", "-1~0%", "0~1%", "1~3%", "3~5%", ">5%"])]
    indices = index_dashboard().get("indices", [])
    groups = _configured_groups(universe, snapshot)
    return {
        "as_of": snapshot["retrieved_at"],
        "source": snapshot["source"],
        "stale": snapshot.get("stale", False),
        "warning": snapshot.get("warning"),
        "universe_count": len(items),
        "reported_total": int(snapshot.get("total") or len(items)),
        "coverage": coverage,
        "complete": complete,
        "indices": indices,
        "summary": {
            "up": int((changes > 0).sum()),
            "flat": int((changes == 0).sum()),
            "down": int((changes < 0).sum()),
            "strong": int((changes >= 0.03).sum()),
            "weak": int((changes <= -0.03).sum()),
            "limit_up": int((changes >= 0.095).sum()),
            "limit_down": int((changes <= -0.095).sum()),
            "amount": float(sum(item["amount"] for item in items)),
            "average_turnover": float(np.mean([item["turnover"] for item in items])),
            "average_volume_ratio": float(np.mean([item["volume_ratio"] for item in items])),
            "mean_change": float(changes.mean()),
            "median_change": float(np.median(changes)),
        },
        "breadth": breadth,
        "groups": groups,
        "leaders": sorted(items, key=lambda item: item["change"], reverse=True)[:10],
        "laggards": sorted(items, key=lambda item: item["change"])[:10],
        "turnover_leaders": sorted(items, key=lambda item: item["amount"], reverse=True)[:10],
        "active": sorted(items, key=lambda item: (item["turnover"] * max(item["volume_ratio"], 0)), reverse=True)[:10],
    }


def _fetch_assets(assets: list[dict[str, str]], limit: int = 320) -> tuple[dict[str, pd.DataFrame], list[str]]:
    frames: dict[str, pd.DataFrame] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(assets)))) as executor:
        futures = {executor.submit(fetch_tencent_daily, item["symbol"], limit): item for item in assets}
        for future in as_completed(futures):
            asset = futures[future]
            try:
                frames[asset["symbol"]] = future.result()
            except Exception:
                failures.append(asset["symbol"])
    return frames, failures


def _simple_strategy_scores(data: pd.DataFrame) -> list[dict[str, Any]]:
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    volume = pd.to_numeric(data.get("volume", 0), errors="coerce").fillna(0)
    ema10, ema40 = close.ewm(span=10, adjust=False).mean(), close.ewm(span=40, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain.div(loss.replace(0, np.nan)))
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    upper, lower = middle + 2 * deviation, middle - 2 * deviation
    channel = high.rolling(20).max().shift(1)
    momentum20 = close.pct_change(20)
    volume_ratio = volume.div(volume.rolling(20).mean().replace(0, np.nan))
    raw = [
        ("adaptive_trend", ema10.iloc[-1] > ema40.iloc[-1] and close.iloc[-1] > ema40.iloc[-1], 50 + 50 * np.tanh(_number(momentum20.iloc[-1]) * 8)),
        ("channel_breakout", close.iloc[-1] > channel.iloc[-1], 45 + 55 * min(1, max(0, close.iloc[-1] / channel.iloc[-1] - 0.98) / 0.04) if channel.iloc[-1] else 0),
        ("bollinger_rsi", close.iloc[-1] < lower.iloc[-1] and rsi.iloc[-1] < 35, max(0, 100 - _number(rsi.iloc[-1]))),
        ("macd_volume", macd.iloc[-1] > macd_signal.iloc[-1] and volume_ratio.iloc[-1] > 1.1, 45 + min(55, _number(volume_ratio.iloc[-1]) * 20)),
        ("squeeze_breakout", (upper.iloc[-2] - lower.iloc[-2]) / middle.iloc[-2] < 0.08 and close.iloc[-1] > upper.iloc[-1], 65 if close.iloc[-1] > upper.iloc[-1] else 20),
        ("multi_timeframe", close.iloc[-1] > ema40.iloc[-1] and close.pct_change(5).iloc[-1] > 0, 50 + 50 * np.tanh(_number(momentum20.iloc[-1]) * 7)),
        ("signal_voting", True, 20 * sum([ema10.iloc[-1] > ema40.iloc[-1], close.iloc[-1] > channel.iloc[-1], macd.iloc[-1] > macd_signal.iloc[-1], rsi.iloc[-1] > 50, volume_ratio.iloc[-1] > 1])),
    ]
    return [{"id": strategy_id, "name": STRATEGY_LABELS[strategy_id], "active": bool(active), "score": round(float(score), 1)} for strategy_id, active, score in raw]


def strategy_scan(universe: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    group_id = str(payload.get("group") or "all")
    strategy_id = str(payload.get("strategy") or "all")
    groups = universe.get("stocks", [])
    selected_groups = groups if group_id == "all" else [group for group in groups if group["id"] == group_id]
    assets = []
    for group in selected_groups:
        for asset in group["assets"]:
            assets.append({**asset, "group_id": group["id"], "group_name": group["name"]})
    unique = {asset["symbol"]: asset for asset in assets}
    assets = list(unique.values())
    frames, failures = _fetch_assets(assets, 320)
    results = []
    for asset in assets:
        data = frames.get(asset["symbol"])
        if data is None or len(data) < 80:
            continue
        scores = _simple_strategy_scores(data)
        candidates = [item for item in scores if item["active"]]
        if strategy_id != "all":
            candidates = [item for item in scores if item["id"] == strategy_id and item["active"]]
        if not candidates:
            continue
        winner = max(candidates, key=lambda item: item["score"])
        close = data["close"].astype(float)
        volume = pd.to_numeric(data.get("volume", 0), errors="coerce").fillna(0)
        results.append(
            {
                **asset,
                "strategy_id": winner["id"],
                "strategy_name": winner["name"],
                "score": winner["score"],
                "price": float(close.iloc[-1]),
                "change": float(close.pct_change().iloc[-1]),
                "volume_ratio": float(volume.iloc[-1] / volume.tail(20).mean()) if volume.tail(20).mean() else 0,
                "momentum60": float(close.pct_change(60).iloc[-1]),
                "signals": scores,
                "series": [{"date": str(index.date()), "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])} for index, row in data.tail(14).iterrows()],
            }
        )
    results.sort(key=lambda item: (item["score"], item["momentum60"]), reverse=True)
    return {"as_of": datetime.now().isoformat(timespec="seconds"), "items": results, "scanned": len(assets), "failures": failures, "strategy_labels": STRATEGY_LABELS}


def _annual_metrics(returns: pd.Series, periods: int = 252) -> dict[str, float]:
    returns = returns.fillna(0).astype(float)
    equity = (1 + returns).cumprod()
    drawdown = equity.div(equity.cummax()).sub(1)
    years = len(returns) / periods
    std = returns.std(ddof=0)
    return {
        "total_return": float(equity.iloc[-1] - 1),
        "annual_return": float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else 0,
        "sharpe": float(returns.mean() / std * math.sqrt(periods)) if std else 0,
        "max_drawdown": float(drawdown.min()),
        "equity": equity,
        "drawdown": drawdown,
    }


def portfolio_backtest(universe: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    group_id = str(payload.get("group") or universe["stocks"][0]["id"])
    group = next((item for item in universe["stocks"] if item["id"] == group_id), None)
    if group is None:
        raise ValueError("请选择有效板块")
    strategy_id = str(payload.get("strategy") or "adaptive_trend")
    if strategy_id not in STRATEGY_LABELS:
        raise ValueError("请选择有效策略")
    initial_cash = min(max(float(payload.get("initial_cash", 100000)), 1000), 1_000_000_000)
    max_positions = min(max(int(payload.get("max_positions", 3)), 1), len(group["assets"]))
    max_exposure = min(max(float(payload.get("max_exposure", 1.0)), 0.1), 1.0)
    stop_loss = min(max(float(payload.get("stop_loss", 0.08)), 0), 0.5)
    take_profit = min(max(float(payload.get("take_profit", 0.25)), 0), 2.0)
    max_hold = min(max(int(payload.get("max_hold", 60)), 1), 1000)
    buy_cost = min(max(float(payload.get("buy_cost", 0.0005)), 0), 0.05)
    sell_cost = min(max(float(payload.get("sell_cost", 0.001)), 0), 0.05)
    assets = group["assets"]
    frames, failures = _fetch_assets(assets, 1000)
    ledgers: dict[str, pd.DataFrame] = {}
    parameters: dict[str, dict[str, Any]] = {}
    for asset in assets:
        data = frames.get(asset["symbol"])
        if data is None or len(data) < 220:
            continue
        generated = generate_candidates(data, costs=Costs(buy=buy_cost, sell=sell_cost))
        candidate = next((item for item in generated["candidates"] if item["id"] == strategy_id), None)
        if candidate is None:
            continue
        parameters[asset["symbol"]] = candidate["parameters"]
        ledgers[asset["symbol"]] = build_candidate_ledger(data, strategy_id, candidate["parameters"], costs=Costs(0, 0))
    if not ledgers:
        raise ValueError("所选板块没有足够历史数据完成回测")
    common = sorted(set.intersection(*(set(frame.index) for frame in ledgers.values())))
    lookback = min(max(int(payload.get("lookback", 300)), 80), len(common))
    dates = pd.DatetimeIndex(common[-lookback:])
    asset_by_symbol = {item["symbol"]: item for item in assets}
    positions: dict[str, dict[str, Any]] = {}
    daily_returns: list[float] = []
    benchmark_returns: list[float] = []
    trades: list[dict[str, Any]] = []
    exposure_history: list[float] = []
    for day_index, date in enumerate(dates):
        signals = []
        for symbol, ledger in ledgers.items():
            if date not in ledger.index:
                continue
            row = ledger.loc[date]
            history = ledger.loc[:date, "close"]
            momentum = float(history.pct_change(20).iloc[-1]) if len(history) > 20 else 0
            if float(row["position_open"]) > 0:
                signals.append((symbol, momentum))
        signals.sort(key=lambda item: item[1], reverse=True)
        selected = {symbol for symbol, _ in signals[:max_positions]}
        for symbol in list(positions):
            ledger = ledgers[symbol]
            row = ledger.loc[date]
            position = positions[symbol]
            open_price = float(row["open"])
            pnl = open_price / position["entry_price"] - 1
            position["days"] += 1
            reason = None
            if symbol not in selected:
                reason = "信号退出"
            elif pnl <= -stop_loss:
                reason = "止损"
            elif take_profit > 0 and pnl >= take_profit:
                reason = "止盈"
            elif position["days"] >= max_hold:
                reason = "最长持有"
            if reason:
                net = pnl - buy_cost - sell_cost
                trades.append({"symbol": symbol, "name": asset_by_symbol[symbol]["name"], "entry_date": position["entry_date"], "exit_date": str(date.date()), "entry_price": position["entry_price"], "exit_price": open_price, "holding_days": position["days"], "net_return": net, "reason": reason})
                del positions[symbol]
        slots = max_positions - len(positions)
        for symbol, _ in signals:
            if slots <= 0:
                break
            if symbol in positions:
                continue
            open_price = float(ledgers[symbol].loc[date, "open"])
            positions[symbol] = {"entry_date": str(date.date()), "entry_price": open_price, "days": 0}
            slots -= 1
        weight = max_exposure / max_positions
        day_return = 0.0
        for symbol in positions:
            row = ledgers[symbol].loc[date]
            day_return += weight * float(row["asset_forward_return"])
        daily_returns.append(day_return)
        benchmark_returns.append(float(np.mean([frame.loc[date, "asset_forward_return"] for frame in ledgers.values()])))
        exposure_history.append(weight * len(positions))
    returns = pd.Series(daily_returns, index=dates)
    benchmark = pd.Series(benchmark_returns, index=dates)
    metrics = _annual_metrics(returns)
    benchmark_metrics = _annual_metrics(benchmark)
    wins = [trade for trade in trades if trade["net_return"] > 0]
    series = []
    for index, date in enumerate(dates):
        series.append({"date": str(date.date()), "equity": float(metrics["equity"].iloc[index]), "benchmark": float(benchmark_metrics["equity"].iloc[index]), "drawdown": float(metrics["drawdown"].iloc[index]), "exposure": exposure_history[index]})
    return {
        "strategy_id": strategy_id,
        "strategy_name": STRATEGY_LABELS[strategy_id],
        "group": {"id": group["id"], "name": group["name"]},
        "settings": {"initial_cash": initial_cash, "max_positions": max_positions, "max_exposure": max_exposure, "stop_loss": stop_loss, "take_profit": take_profit, "max_hold": max_hold, "lookback": lookback},
        "metrics": {key: value for key, value in metrics.items() if key not in {"equity", "drawdown"}},
        "benchmark_return": benchmark_metrics["total_return"],
        "excess_return": metrics["total_return"] - benchmark_metrics["total_return"],
        "final_equity": initial_cash * (1 + metrics["total_return"]),
        "win_rate": len(wins) / len(trades) if trades else None,
        "trades": trades,
        "series": series,
        "failures": failures,
        "parameters": parameters,
        "execution_notes": ["收盘信号、次日开盘执行", "等风险槽位，不使用未来排名", "包含双边费用", "A股涨跌停与停牌在单股模拟账户中建模；组合回测未逐笔建模"],
    }


def _limit_threshold(item: dict[str, Any]) -> float:
    code = item["code"]
    name = item["name"].upper()
    if "ST" in name:
        return 0.047
    if code.startswith(("300", "301", "688")):
        return 0.195
    if code.startswith(("4", "8", "92")):
        return 0.295
    return 0.095


def _limit_time(value: Any) -> str:
    digits = str(int(_number(value))).zfill(6)
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}" if digits != "000000" else "—"


def _parse_limit_pool(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    pool = list(data.get("pool") or [])
    items = []
    for raw in pool:
        code = str(raw.get("c") or "")
        if len(code) != 6:
            continue
        streak = max(1, int(_number(raw.get("lbc"), 1)))
        statistics = raw.get("zttj") or {}
        items.append({
            "symbol": _stock_symbol(code),
            "code": code,
            "name": str(raw.get("n") or code),
            "price": _number(raw.get("p")) / 1000,
            "change": _number(raw.get("zdp")) / 100,
            "amount": _number(raw.get("amount")),
            "turnover": _number(raw.get("hs")) / 100,
            "float_cap": _number(raw.get("ltsz")),
            "market_cap": _number(raw.get("tshare")),
            "streak": streak,
            "first_limit_time": _limit_time(raw.get("fbt")),
            "last_limit_time": _limit_time(raw.get("lbt")),
            "break_count": int(_number(raw.get("zbc"))),
            "sealed_amount": _number(raw.get("fund")),
            "industry": str(raw.get("hybk") or "未分类"),
            "limit_days": int(_number(statistics.get("days"))),
            "limit_count": int(_number(statistics.get("ct"))),
        })
    return {
        "epoch": time.time(),
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": str(data.get("qdate") or ""),
        "source": "东方财富涨停池（全市场）",
        "scope": "all_market",
        "stale": False,
        "total": int(data.get("tc") or len(items)),
        "items": items,
    }


def _refresh_limit_pool() -> dict[str, Any]:
    last_payload: dict[str, Any] = {}
    for day_offset in range(10):
        trade_date = (datetime.now() - timedelta(days=day_offset)).strftime("%Y%m%d")
        parameters = {
            "ut": "7eea3edcaed734bea9cbfc24409ed989",
            "dpt": "wz.ztzt",
            "Pageindex": 0,
            "pagesize": 200,
            "sort": "fbt:asc",
            "date": trade_date,
        }
        url = "https://push2ex.eastmoney.com/getTopicZTPool?" + urllib.parse.urlencode(parameters)
        payload = _http_json(url, timeout=15)
        last_payload = payload
        if list((payload.get("data") or {}).get("pool") or []):
            result = _parse_limit_pool(payload)
            _write_json(LIMIT_POOL_FILE, result)
            return result
    result = _parse_limit_pool(last_payload)
    if not result["items"]:
        raise RuntimeError("全市场涨停池暂未返回可用数据")
    _write_json(LIMIT_POOL_FILE, result)
    return result


def fetch_limit_pool(*, force: bool = False) -> dict[str, Any]:
    requested_at = time.time()
    cached = _read_json(LIMIT_POOL_FILE, {})
    if not force and cached and time.time() - float(cached.get("epoch", 0)) < SNAPSHOT_TTL_SECONDS:
        return cached
    with _LIMIT_POOL_REFRESH_LOCK:
        cached = _read_json(LIMIT_POOL_FILE, {})
        cache_epoch = float(cached.get("epoch", 0)) if cached else 0
        if cached and (
            (not force and time.time() - cache_epoch < SNAPSHOT_TTL_SECONDS)
            or cache_epoch >= requested_at
        ):
            return cached
        try:
            return _refresh_limit_pool()
        except Exception as exc:
            if cached:
                result = dict(cached)
                result["stale"] = True
                result["warning"] = f"涨停池实时刷新失败，已显示最近快照：{_upstream_error_message(exc)}"
                return result
            raise


def limit_ladder(universe: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    snapshot = fetch_limit_pool(force=force)
    lookup_group = {}
    for group in universe["stocks"]:
        for asset in group["assets"]:
            lookup_group.setdefault(asset["symbol"], []).append(group["name"])
    ladders: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: [], 4: []}
    for item in snapshot["items"]:
        groups = list(dict.fromkeys([*lookup_group.get(item["symbol"], []), item["industry"]]))
        bucket = min(4, item["streak"])
        ladders[bucket].append({**item, "groups": groups})
    for items in ladders.values():
        items.sort(key=lambda item: (-item["streak"], item["first_limit_time"], -item["sealed_amount"]))
    return {
        "as_of": snapshot["retrieved_at"],
        "trade_date": snapshot.get("trade_date"),
        "source": snapshot["source"],
        "scope": snapshot.get("scope", "all_market"),
        "stale": bool(snapshot.get("stale")),
        "warning": snapshot.get("warning"),
        "total": len(snapshot["items"]),
        "ladders": {str(key): value for key, value in ladders.items()},
        "failures": [],
    }


def concept_analysis(universe: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    snapshot = fetch_market_snapshot(force=force)
    groups = _configured_groups(universe, snapshot)
    ranked = sorted(groups, key=lambda item: item["change"], reverse=True)
    return {
        "as_of": snapshot["retrieved_at"],
        "source": f"{snapshot['source']} + 本项目配置板块",
        "stale": snapshot.get("stale", False),
        "warning": snapshot.get("warning"),
        "scope_note": f"覆盖本项目 {len(ranked)} 个配置板块，不宣称全市场概念库",
        "groups": ranked,
        "leaders": ranked[:10],
        "laggards": list(reversed(ranked[-10:])),
        "strongest": ranked[0] if ranked else None,
        "weakest": ranked[-1] if ranked else None,
    }


def industry_analysis(universe: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Rank the configured stock groups as transparent industry proxies.

    The public quote source does not provide a stable full-market industry
    taxonomy. Using the project's configured groups keeps the result honest and
    makes the page useful without another fragile upstream dependency.
    """
    snapshot = fetch_market_snapshot(force=force)
    groups = _configured_groups(universe, snapshot)
    industries = []
    for group in groups:
        members = sorted(group["members"], key=lambda item: item["change"], reverse=True)
        amount = sum(float(item.get("amount") or 0) for item in members)
        industries.append({
            "id": group["id"],
            "name": group["name"],
            "change": group["change"],
            "amount": amount,
            "up": sum(item["change"] > 0 for item in members),
            "down": sum(item["change"] < 0 for item in members),
            "members": members[:5],
            "member_count": len(members),
        })
    industries.sort(key=lambda item: item["change"], reverse=True)
    return {
        "as_of": snapshot["retrieved_at"],
        "source": snapshot["source"],
        "source_scope": "按项目配置板块聚合，不代表交易所官方行业分类",
        "stale": snapshot.get("stale", False),
        "warning": snapshot.get("warning"),
        "industries": industries,
    }


def get_watchlist() -> list[dict[str, Any]]:
    return _read_json(WATCHLIST_FILE, [])


def update_watchlist(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = get_watchlist()
    action = str(payload.get("action") or "add")
    symbol = str(payload.get("symbol") or "").lower()
    if action == "remove":
        items = [item for item in items if item.get("symbol") != symbol]
    else:
        if not symbol:
            raise ValueError("缺少标的代码")
        entry = {"symbol": symbol, "name": str(payload.get("name") or symbol), "group": str(payload.get("group") or ""), "added_at": datetime.now().isoformat(timespec="seconds")}
        items = [item for item in items if item.get("symbol") != symbol]
        items.append(entry)
    _write_json(WATCHLIST_FILE, items)
    return items


def _monitor_state() -> dict[str, Any]:
    return {"rules": _read_json(MONITOR_RULES_FILE, []), "events": _read_json(MONITOR_EVENTS_FILE, [])}


def monitor_view() -> dict[str, Any]:
    state = _monitor_state()
    state["rule_types"] = [
        {"id": "price_above", "name": "价格高于"},
        {"id": "price_below", "name": "价格低于"},
        {"id": "change_above", "name": "涨幅达到"},
        {"id": "change_below", "name": "跌幅达到"},
        {"id": "volume_ratio_above", "name": "量比达到"},
    ]
    return state


def update_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    state = _monitor_state()
    action = str(payload.get("action") or "add")
    if action == "delete":
        rule_id = int(payload.get("id"))
        state["rules"] = [rule for rule in state["rules"] if int(rule["id"]) != rule_id]
    elif action == "clear_events":
        state["events"] = []
    elif action == "evaluate":
        snapshot = fetch_market_snapshot(force=bool(payload.get("force")))
        lookup = _snapshot_map(snapshot)
        now = datetime.now().isoformat(timespec="seconds")
        existing = {(event["rule_id"], event["snapshot_at"]) for event in state["events"]}
        for rule in state["rules"]:
            market = lookup.get(rule["symbol"])
            if not market or not rule.get("enabled", True):
                continue
            rule_type, threshold = rule["type"], float(rule["threshold"])
            current = market["price"] if rule_type.startswith("price_") else market["change"] if rule_type.startswith("change_") else market["volume_ratio"]
            triggered = current >= threshold if rule_type.endswith("above") else current <= threshold
            event_key = (rule["id"], snapshot["retrieved_at"])
            if triggered and event_key not in existing:
                state["events"].insert(0, {"id": int(time.time() * 1000), "rule_id": rule["id"], "snapshot_at": snapshot["retrieved_at"], "triggered_at": now, "symbol": rule["symbol"], "name": rule["name"], "type": rule_type, "threshold": threshold, "current": current, "price": market["price"], "change": market["change"]})
        state["events"] = state["events"][:300]
    else:
        rule_type = str(payload.get("type") or "")
        if rule_type not in {"price_above", "price_below", "change_above", "change_below", "volume_ratio_above"}:
            raise ValueError("无效监控类型")
        symbol = str(payload.get("symbol") or "").lower()
        if not symbol:
            raise ValueError("缺少标的代码")
        threshold = float(payload.get("threshold"))
        rule_id = max([int(rule["id"]) for rule in state["rules"]] + [0]) + 1
        state["rules"].append({"id": rule_id, "symbol": symbol, "name": str(payload.get("name") or symbol), "type": rule_type, "threshold": threshold, "enabled": True, "created_at": datetime.now().isoformat(timespec="seconds")})
    _write_json(MONITOR_RULES_FILE, state["rules"])
    _write_json(MONITOR_EVENTS_FILE, state["events"])
    return monitor_view()


def stock_analysis(symbol: str) -> dict[str, Any]:
    data = fetch_tencent_daily(symbol, 1000)
    close = data["close"].astype(float)
    result = generate_candidates(data)
    return {
        "symbol": symbol,
        "latest": result["latest"],
        "profile": result["profile"],
        "candidates": [{key: item[key] for key in ("id", "name", "family", "rank", "description", "risk", "test", "parameters")} for item in result["candidates"]],
        "series": [{"date": str(index.date()), "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"]), "volume": float(row.get("volume", 0)), "ma20": float(close.rolling(20).mean().loc[index]) if pd.notna(close.rolling(20).mean().loc[index]) else None, "ma60": float(close.rolling(60).mean().loc[index]) if pd.notna(close.rolling(60).mean().loc[index]) else None} for index, row in data.tail(180).iterrows()],
    }
