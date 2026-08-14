"""Self-contained local quantitative dashboard server."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from quant_trading.market_data import fetch_gate_candles, fetch_tencent_daily  # noqa: E402
from dashboard.paper_trading import (  # noqa: E402
    account_view,
    advance_account,
    load_account,
    reset_account,
    start_account,
)
from dashboard.broker_adapters import (  # noqa: E402
    broker_catalog,
    configure_broker,
    okx_demo_place_order,
    okx_public_candles,
    sync_broker,
)
from dashboard.market_terminal import (  # noqa: E402
    concept_analysis,
    get_watchlist,
    index_dashboard,
    industry_analysis,
    limit_ladder,
    market_dashboard,
    monitor_view,
    portfolio_backtest,
    stock_analysis,
    strategy_scan,
    update_monitor,
    update_watchlist,
)
from dashboard.strategy_factory import Costs, build_candidate_ledger, generate_candidates  # noqa: E402


ASSET_UNIVERSE = {
    "stocks": [
        {"id": "blue_chip", "name": "大盘蓝筹", "assets": [
            {"symbol": "sh601398", "name": "工商银行"}, {"symbol": "sh601318", "name": "中国平安"},
            {"symbol": "sh600036", "name": "招商银行"}, {"symbol": "sh600900", "name": "长江电力"},
            {"symbol": "sh601088", "name": "中国神华"},
        ]},
        {"id": "ai_compute", "name": "人工智能与算力", "assets": [
            {"symbol": "sh688256", "name": "寒武纪"}, {"symbol": "sh603019", "name": "中科曙光"},
            {"symbol": "sz000977", "name": "浪潮信息"}, {"symbol": "sz300308", "name": "中际旭创"},
            {"symbol": "sz002230", "name": "科大讯飞"},
        ]},
        {"id": "semiconductor", "name": "半导体", "assets": [
            {"symbol": "sh688981", "name": "中芯国际"}, {"symbol": "sh603501", "name": "豪威集团"},
            {"symbol": "sz002371", "name": "北方华创"}, {"symbol": "sh688012", "name": "中微公司"},
            {"symbol": "sh600584", "name": "长电科技"},
        ]},
        {"id": "new_energy", "name": "新能源", "assets": [
            {"symbol": "sz300750", "name": "宁德时代"}, {"symbol": "sz002594", "name": "比亚迪"},
            {"symbol": "sh601012", "name": "隆基绿能"}, {"symbol": "sz300274", "name": "阳光电源"},
            {"symbol": "sz002129", "name": "TCL中环"},
        ]},
        {"id": "robotics", "name": "机器人", "assets": [
            {"symbol": "sh688017", "name": "绿的谐波"}, {"symbol": "sz002472", "name": "双环传动"},
            {"symbol": "sh603662", "name": "柯力传感"}, {"symbol": "sz300124", "name": "汇川技术"},
            {"symbol": "sz002747", "name": "埃斯顿"},
        ]},
        {"id": "medicine", "name": "医药生物", "assets": [
            {"symbol": "sh600276", "name": "恒瑞医药"}, {"symbol": "sz300760", "name": "迈瑞医疗"},
            {"symbol": "sh603259", "name": "药明康德"}, {"symbol": "sz000661", "name": "长春高新"},
            {"symbol": "sz002422", "name": "科伦药业"},
        ]},
        {"id": "low_altitude", "name": "低空经济", "assets": [
            {"symbol": "sz002085", "name": "万丰奥威"}, {"symbol": "sz001696", "name": "宗申动力"},
            {"symbol": "sh688297", "name": "中无人机"}, {"symbol": "sh600879", "name": "航天电子"},
            {"symbol": "sz002036", "name": "联创电子"},
        ]},
    ],
    "crypto": [
        {"id": "crypto_major", "name": "主流币", "assets": [
            {"symbol": "BTC", "name": "Bitcoin"}, {"symbol": "ETH", "name": "Ethereum"},
            {"symbol": "SOL", "name": "Solana"}, {"symbol": "BNB", "name": "BNB"},
            {"symbol": "XRP", "name": "XRP"},
        ]},
        {"id": "crypto_l1", "name": "公链生态", "assets": [
            {"symbol": "ADA", "name": "Cardano"}, {"symbol": "AVAX", "name": "Avalanche"},
            {"symbol": "SUI", "name": "Sui"}, {"symbol": "APT", "name": "Aptos"},
            {"symbol": "DOT", "name": "Polkadot"},
        ]},
        {"id": "crypto_defi", "name": "DeFi", "assets": [
            {"symbol": "LINK", "name": "Chainlink"}, {"symbol": "UNI", "name": "Uniswap"},
            {"symbol": "AAVE", "name": "Aave"}, {"symbol": "MKR", "name": "Maker"},
            {"symbol": "LDO", "name": "Lido"},
        ]},
    ],
}


THEME_LIBRARY = [
    {"id": "ai_compute", "name": "AI 算力基础设施", "focus": "服务器、光模块、国产算力", "risk": "估值与资本开支周期"},
    {"id": "robotics", "name": "人形机器人", "focus": "减速器、传感器、电机与执行器", "risk": "量产节奏与订单兑现"},
    {"id": "low_altitude", "name": "低空经济", "focus": "整机、动力、航电与空管", "risk": "政策落地与商业化周期"},
    {"id": "semiconductor", "name": "半导体国产化", "focus": "设备、制造、设计与封测", "risk": "行业周期与研发投入"},
    {"id": "new_energy", "name": "新能源修复", "focus": "电池、光伏、储能与电力电子", "risk": "产能过剩与价格竞争"},
    {"id": "medicine", "name": "创新药与医疗器械", "focus": "创新药、CXO 与高端器械", "risk": "研发失败与政策变化"},
]


THEME_DETAILS = {
    "ai_compute": {
        "sh688256": ("国产 AI 芯片", "算力芯片与软件生态", "高估值与供应链约束"),
        "sh603019": ("服务器", "高性能计算与液冷服务器", "资本开支波动"),
        "sz000977": ("AI 服务器", "国内服务器核心厂商", "订单与毛利率波动"),
        "sz300308": ("光模块", "高速光模块与海外算力链", "海外需求与贸易风险"),
        "sz002230": ("大模型应用", "语音与行业大模型", "商业化兑现周期"),
    },
    "semiconductor": {
        "sh688981": ("晶圆制造", "先进与成熟制程制造平台", "扩产周期与外部限制"),
        "sh603501": ("图像传感器", "CIS 设计与汽车电子", "消费电子周期"),
        "sz002371": ("半导体设备", "刻蚀与薄膜设备平台", "研发投入与验证周期"),
        "sh688012": ("刻蚀设备", "国产半导体核心设备", "估值与订单节奏"),
        "sh600584": ("封装测试", "先进封装与测试", "行业景气波动"),
    },
    "new_energy": {
        "sz300750": ("动力电池", "全球动力与储能电池龙头", "价格竞争与海外政策"),
        "sz002594": ("整车与电池", "新能源整车垂直一体化", "竞争加剧与毛利压力"),
        "sh601012": ("光伏组件", "单晶硅片与组件", "产能过剩与价格下行"),
        "sz300274": ("逆变器", "光伏与储能电力电子", "海外市场与库存周期"),
        "sz002129": ("硅片", "光伏硅片与半导体材料", "周期底部持续时间"),
    },
    "medicine": {
        "sh600276": ("创新药", "肿瘤与慢病创新管线", "临床与商业化风险"),
        "sz300760": ("医疗器械", "监护、影像与体外诊断", "海外与集采影响"),
        "sh603259": ("CXO", "全球医药研发服务", "地缘与订单波动"),
        "sz000661": ("生物制品", "生长激素与疫苗", "单品依赖与政策风险"),
        "sz002422": ("创新药", "输液、仿制药与创新管线", "研发投入与放量节奏"),
    },
}


PAPER_DATA_CACHE: dict[str, pd.DataFrame] = {}
MARKET_DATA_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def sanitize_json(value: Any) -> Any:
    """Convert pandas/numpy values and NaN to strict JSON-compatible values."""
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return sanitize_json(value.item())
    return value


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def safe_project_path(relative: str, roots: tuple[str, ...]) -> Path:
    candidate = (PROJECT_ROOT / unquote(relative)).resolve()
    allowed = [(PROJECT_ROOT / root).resolve() for root in roots]
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise ValueError("Path is outside the allowed project area")
    return candidate


def csv_records(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if limit is not None:
        frame = frame.head(limit)
    frame = frame.where(pd.notna(frame), None)
    return frame.to_dict(orient="records")


def dataset_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_root = PROJECT_ROOT / "data" / "raw"
    for path in sorted(raw_root.rglob("*.csv")):
        metadata_path = path.with_suffix(".metadata.json")
        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(read_text(metadata_path))
            except json.JSONDecodeError:
                metadata = {}
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            first = next(reader, [])
            count = 1 if first else 0
            last = first
            for last in reader:
                count += 1
        date_idx = next((header.index(col) for col in ("trade_date", "datetime", "date") if col in header), None)
        source = metadata.get("source") or "local snapshot"
        interval = metadata.get("interval")
        if not interval:
            lower_name = path.name.casefold()
            if "15m" in lower_name:
                interval = "15m"
            elif "60m" in lower_name or "1h" in lower_name:
                interval = "60m"
            elif "daily" in str(source).casefold() or "btc_usdt_gate_1d" in lower_name or "_1d_" in lower_name or path.parent.name == "sh600519":
                interval = "1d"
            else:
                interval = "unknown"
        rows.append(
            {
                "name": path.stem,
                "path": path.relative_to(PROJECT_ROOT).as_posix(),
                "symbol": metadata.get("symbol") or path.parent.name,
                "interval": interval,
                "source": source,
                "adjust": metadata.get("adjust") or metadata.get("adjustment") or "unspecified",
                "rows": metadata.get("rows") or count,
                "first_date": metadata.get("first_trade_date") or (first[date_idx] if first and date_idx is not None else None),
                "last_date": metadata.get("last_closed_trade_date") or metadata.get("last_trade_date") or (last[date_idx] if last and date_idx is not None else None),
                "retrieved_at": metadata.get("retrieved_at"),
                "size_kb": round(path.stat().st_size / 1024, 1),
            }
        )
    return rows


def overview() -> dict[str, Any]:
    datasets = dataset_catalog()
    latest = max((path.stat().st_mtime for path in (PROJECT_ROOT / "data").rglob("*") if path.is_file()), default=time.time())
    return {
        "updated_at": datetime.fromtimestamp(latest).isoformat(timespec="minutes"),
        "datasets": datasets,
    }


def theme_screen() -> dict[str, Any]:
    candidates = sorted((PROJECT_ROOT / "data" / "processed" / "theme").glob("screen_*.csv"))
    if not candidates:
        return {"items": [], "source": None}
    path = candidates[-1]
    return {"items": csv_records(path, 50), "source": path.relative_to(PROJECT_ROOT).as_posix()}


def asset_universe() -> dict[str, Any]:
    return {
        "sources": [
            {"id": "tencent", "name": "腾讯 A 股日线", "asset_type": "stocks", "network": True},
            {"id": "gate", "name": "Gate.io 虚拟货币", "asset_type": "crypto", "network": True},
            {"id": "local_stock", "name": "本地股票快照", "asset_type": "local_stock", "network": False},
            {"id": "local_crypto", "name": "本地虚拟货币快照", "asset_type": "local_crypto", "network": False},
        ],
        "groups": ASSET_UNIVERSE,
    }


def theme_candidates(theme_id: str) -> dict[str, Any]:
    theme = next((item for item in THEME_LIBRARY if item["id"] == theme_id), None)
    if theme is None:
        raise ValueError("未知主题")
    members: list[dict[str, Any]] = []
    if theme_id in {"robotics", "low_altitude"}:
        screen = theme_screen().get("items", [])
        keyword = "人形机器人" if theme_id == "robotics" else "无人机/低空"
        for item in screen:
            if keyword not in str(item.get("direction", "")):
                continue
            members.append({
                "symbol": item.get("symbol"), "name": item.get("name"), "segment": item.get("segment"),
                "logic": item.get("logic"), "risk": "主题波动与估值回撤",
            })
    if not members:
        group = next((item for item in ASSET_UNIVERSE["stocks"] if item["id"] == theme_id), None)
        details = THEME_DETAILS.get(theme_id, {})
        for asset in (group or {}).get("assets", []):
            segment, logic, risk = details.get(asset["symbol"], (theme["focus"], "主题核心观察标的", theme["risk"]))
            members.append({**asset, "segment": segment, "logic": logic, "risk": risk})
    return {"theme": theme, "items": members[:12]}


def normalize_market_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    date_column = next((column for column in ("trade_date", "datetime", "date") if column in frame), None)
    if date_column is None:
        raise ValueError("Dataset has no recognized date column")
    if not {"open", "close"}.issubset(frame.columns):
        raise ValueError("Dataset must contain open and close columns")
    frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
    frame = frame.dropna(subset=[date_column]).set_index(date_column).sort_index()
    return frame


def normalize_symbol(value: str) -> str:
    value = value.strip().casefold().replace(".", "")
    if value.startswith(("sh", "sz", "bj")) and len(value) == 8 and value[2:].isdigit():
        return value
    if len(value) == 6 and value.isdigit():
        if value.startswith(("6", "9")):
            return f"sh{value}"
        if value.startswith(("0", "3")):
            return f"sz{value}"
        if value.startswith(("4", "8")):
            return f"bj{value}"
    raise ValueError("请输入 6 位 A 股代码，例如 600519 或 002245")


def normalize_crypto_symbol(value: str) -> str:
    symbol = value.strip().upper().replace("/USDT", "").replace("-USDT", "").replace("USDT", "")
    if not symbol.isalnum() or not 2 <= len(symbol) <= 12:
        raise ValueError("请选择有效的虚拟货币标的")
    return symbol


def asset_display_label(payload: dict[str, Any], source: str, symbol: str, fallback: str) -> str:
    custom = str(payload.get("custom_label") or payload.get("label") or "").strip()
    if custom:
        if len(custom) > 40 or any(ord(character) < 32 for character in custom):
            raise ValueError("自定义名称不能超过 40 个字符或包含控制字符")
        return custom
    asset_type = "stocks" if source in {"tencent", "remote"} else "crypto" if source == "gate" else None
    if asset_type:
        for group in ASSET_UNIVERSE[asset_type]:
            asset = next((item for item in group["assets"] if item["symbol"] == symbol), None)
            if asset:
                return str(asset["name"])
    return fallback


def _online_daily(source: str, symbol: str) -> pd.DataFrame:
    key = (source, symbol)
    cached = MARKET_DATA_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    if source == "tencent":
        data = fetch_tencent_daily(symbol, 1000)
    elif source == "gate":
        data, _ = fetch_gate_candles("1d", 1000, symbol=symbol)
    else:
        raise ValueError("Only online sources support sector context")
    MARKET_DATA_CACHE[key] = data.copy()
    return data


def load_asset_data(payload: dict[str, Any]) -> tuple[pd.DataFrame, str, str, int]:
    source = str(payload.get("source", "tencent"))
    if source in {"local", "local_stock", "local_crypto"}:
        relative = str(payload.get("dataset", ""))
        roots = ("data/raw", "data/processed/paper_trading")
        path = safe_project_path(relative, roots)
        if path.suffix.casefold() != ".csv" or not path.exists():
            raise ValueError("请选择有效的本地日线快照")
        data = normalize_market_frame(path)
        symbol = next((item["symbol"] for item in dataset_catalog() if item["path"] == relative), path.parent.name)
        label = path.stem
        periods_per_year = 365 if "btc" in relative.casefold() or "usdt" in relative.casefold() else 252
    elif source in {"tencent", "remote"}:
        symbol = normalize_symbol(str(payload.get("symbol", "")))
        data = _online_daily("tencent", symbol)
        label = asset_display_label(payload, source, symbol, symbol)
        periods_per_year = 252
    elif source == "gate":
        symbol = normalize_crypto_symbol(str(payload.get("symbol", "")))
        data = _online_daily("gate", symbol)
        label = asset_display_label(payload, source, symbol, f"{symbol}/USDT")
        periods_per_year = 365
    else:
        raise ValueError("未知数据源")
    return data, symbol, label, periods_per_year


def add_relative_strength_context(
    data: pd.DataFrame,
    payload: dict[str, Any],
    source: str,
    symbol: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach aligned benchmark and sector closes for relative-strength signals."""
    if source not in {"tencent", "gate"}:
        return data, {"available": False, "reason": "本地快照未包含板块成员与基准行情"}
    asset_type = "stocks" if source == "tencent" else "crypto"
    group_id = str(payload.get("group") or payload.get("group_id") or "")
    group = next((item for item in ASSET_UNIVERSE[asset_type] if item["id"] == group_id), None)
    if group is None:
        return data, {"available": False, "reason": "未识别所选板块"}

    members = [item["symbol"] for item in group["assets"] if item["symbol"] != symbol]
    benchmark_symbol = "sh000300" if source == "tencent" else "BTC"
    requested = list(dict.fromkeys([benchmark_symbol, *members]))
    fetched: dict[str, pd.DataFrame] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=min(5, len(requested))) as executor:
        futures = {executor.submit(_online_daily, source, item): item for item in requested}
        for future in as_completed(futures):
            item = futures[future]
            try:
                fetched[item] = future.result()
            except Exception:
                failures.append(item)

    enriched = data.copy()
    peer_count = 0
    for member in members:
        peer = fetched.get(member)
        if peer is None:
            continue
        aligned = peer["close"].reindex(enriched.index).ffill()
        if aligned.notna().sum() >= 120:
            enriched[f"peer_close_{member}"] = aligned
            peer_count += 1

    benchmark = fetched.get(benchmark_symbol)
    benchmark_label = benchmark_symbol
    if benchmark is not None:
        enriched["benchmark_close"] = benchmark["close"].reindex(enriched.index).ffill()
    elif source == "gate" and peer_count:
        peer_columns = [column for column in enriched if column.startswith("peer_close_")]
        normalized = enriched[peer_columns].div(enriched[peer_columns].apply(lambda column: column.dropna().iloc[0]))
        enriched["benchmark_close"] = normalized.mean(axis=1)
        benchmark_label = "板块等权基准"

    available = "benchmark_close" in enriched and enriched["benchmark_close"].notna().sum() >= 120 and peer_count > 0
    if not available:
        enriched = enriched.drop(
            columns=[column for column in enriched if column == "benchmark_close" or column.startswith("peer_close_")],
            errors="ignore",
        )
    return enriched, {
        "available": available,
        "group_id": group["id"],
        "group_name": group["name"],
        "benchmark": benchmark_label,
        "peer_count": peer_count,
        "failed_symbols": failures,
        "reason": None if available else "板块成员或基准行情不足",
    }


def prepare_strategy_data(payload: dict[str, Any]) -> tuple[pd.DataFrame, str, str, int, dict[str, Any]]:
    data, symbol, label, periods_per_year = load_asset_data(payload)
    source = str(payload.get("source", "tencent"))
    data, relative_context = add_relative_strength_context(data, payload, source, symbol)
    return data, symbol, label, periods_per_year, relative_context


def strategy_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    buy_cost = float(payload.get("buy_cost", 0.0005))
    sell_cost = float(payload.get("sell_cost", 0.0010))
    if not (0 <= buy_cost <= 0.05 and 0 <= sell_cost <= 0.05):
        raise ValueError("One-way costs must be between 0 and 5%")
    source = str(payload.get("source", "tencent"))
    data, symbol, label, periods_per_year, relative_context = prepare_strategy_data(payload)
    result = generate_candidates(data, costs=Costs(buy=buy_cost, sell=sell_cost), periods_per_year=periods_per_year)
    result.update({
        "symbol": symbol,
        "label": label,
        "source": source,
        "group": payload.get("group") or payload.get("group_id"),
        "bars": len(data),
        "periods_per_year": periods_per_year,
        "relative_strength_context": relative_context,
    })
    return result


def okx_strategy_preview(payload: dict[str, Any]) -> dict[str, Any]:
    instrument = str(payload.get("inst_id") or "").strip().upper()
    strategy_id = str(payload.get("strategy_id") or "").strip()
    raw_parameters = payload.get("parameters")
    if not strategy_id or not isinstance(raw_parameters, dict) or not raw_parameters:
        raise ValueError("请选择策略并填写参数")
    parameters: dict[str, float | int] = {}
    for key, raw_value in raw_parameters.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(key)):
            raise ValueError("策略参数名称无效")
        value = float(raw_value)
        if not math.isfinite(value) or abs(value) > 1_000_000:
            raise ValueError(f"参数 {key} 超出允许范围")
        parameters[str(key)] = int(value) if value.is_integer() else value
    rows = okx_public_candles(instrument, limit=300)
    frame = pd.DataFrame(rows)
    frame["trade_date"] = pd.to_datetime(frame.pop("timestamp"), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    frame = frame.set_index("trade_date").sort_index()
    ledger = build_candidate_ledger(frame, strategy_id, parameters)
    desired = float(ledger["signal_close"].iloc[-1])
    previous = float(ledger["signal_close"].iloc[-2])
    action = "buy" if desired > previous + 1e-9 else "sell" if desired < previous - 1e-9 else "hold"
    return {
        "provider": "okx_demo",
        "demo": True,
        "inst_id": instrument,
        "strategy_id": strategy_id,
        "parameters": parameters,
        "bar_time": frame.index[-1].isoformat(),
        "close": float(frame["close"].iloc[-1]),
        "previous_target": previous,
        "target_fraction": desired,
        "action": action,
        "notice": "使用最后一根已完成 OKX 日线计算；信号预览不会自动下单。",
    }


def environment_check(network: bool) -> dict[str, Any]:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "check_environment.py")]
    if network:
        command.append("--network")
    started = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    return {
        "ok": process.returncode == 0,
        "network": network,
        "duration": round(time.perf_counter() - started, 2),
        "output": (process.stdout + process.stderr).strip(),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "QuantDashboard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def end_headers(self) -> None:  # noqa: N802
        # The dashboard is edited locally during research. Avoid serving an old
        # app.js after a restart, which can leave newly added views stuck loading.
        path = urlparse(self.path).path
        if path == "/" or path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(sanitize_json(payload), ensure_ascii=False, allow_nan=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, exc: Exception, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"error": str(exc)}, status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/overview":
                self.send_json(overview())
                return
            if parsed.path == "/api/theme":
                self.send_json(theme_screen())
                return
            if parsed.path == "/api/theme-options":
                self.send_json({"items": THEME_LIBRARY})
                return
            if parsed.path.startswith("/api/theme-candidates/"):
                self.send_json(theme_candidates(parsed.path.rsplit("/", 1)[-1]))
                return
            if parsed.path == "/api/asset-universe":
                self.send_json(asset_universe())
                return
            if parsed.path == "/api/datasets":
                self.send_json({"items": dataset_catalog()})
                return
            if parsed.path == "/api/ping":
                self.send_json({
                    "ok": True,
                    "service": "quant-research-dashboard",
                    "time": datetime.now().isoformat(timespec="seconds"),
                })
                return
            if parsed.path == "/api/paper/account":
                self.send_json(account_view(load_account()))
                return
            if parsed.path == "/api/brokers":
                self.send_json(broker_catalog(account_view(load_account())))
                return
            if parsed.path == "/api/terminal/market":
                query = parse_qs(parsed.query)
                self.send_json(market_dashboard(ASSET_UNIVERSE, force=query.get("refresh", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/terminal/indices":
                query = parse_qs(parsed.query)
                self.send_json(index_dashboard(force=query.get("refresh", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/terminal/limit-ladder":
                query = parse_qs(parsed.query)
                self.send_json(limit_ladder(ASSET_UNIVERSE, force=query.get("refresh", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/terminal/concepts":
                query = parse_qs(parsed.query)
                self.send_json(concept_analysis(ASSET_UNIVERSE, force=query.get("refresh", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/terminal/industry":
                query = parse_qs(parsed.query)
                self.send_json(industry_analysis(ASSET_UNIVERSE, force=query.get("refresh", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/terminal/watchlist":
                self.send_json({"items": get_watchlist()})
                return
            if parsed.path == "/api/terminal/monitor":
                self.send_json(monitor_view())
                return
            if parsed.path.startswith("/api/terminal/stock/"):
                symbol = normalize_symbol(parsed.path.rsplit("/", 1)[-1])
                self.send_json(stock_analysis(symbol))
                return
            if parsed.path == "/":
                self.path = "/index.html"
            return super().do_GET()
        except FileNotFoundError as exc:
            self.send_error_json(exc, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # keep API errors visible to the local UI
            self.send_error_json(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/strategy-candidates":
                self.send_json(strategy_candidates(payload))
                return
            if parsed.path == "/api/terminal/strategy-scan":
                self.send_json(strategy_scan(ASSET_UNIVERSE, payload))
                return
            if parsed.path == "/api/terminal/backtest":
                self.send_json(portfolio_backtest(ASSET_UNIVERSE, payload))
                return
            if parsed.path == "/api/terminal/watchlist":
                self.send_json({"items": update_watchlist(payload)})
                return
            if parsed.path == "/api/terminal/monitor":
                self.send_json(update_monitor(payload))
                return
            if parsed.path == "/api/environment-check":
                self.send_json(environment_check(bool(payload.get("network", False))))
                return
            if parsed.path == "/api/paper/start":
                data, symbol, label, periods, _ = prepare_strategy_data(payload)
                replay_path = PROJECT_ROOT / "data" / "processed" / "paper_trading" / "market.csv"
                replay_path.parent.mkdir(parents=True, exist_ok=True)
                data.to_csv(replay_path, encoding="utf-8-sig", index_label="trade_date")
                configuration = {
                    **payload,
                    "symbol": symbol,
                    "label": label,
                    "periods_per_year": periods,
                    "replay_dataset": replay_path.relative_to(PROJECT_ROOT).as_posix(),
                }
                result = start_account(data, configuration)
                PAPER_DATA_CACHE["default"] = data
                self.send_json(result)
                return
            if parsed.path == "/api/brokers/sync":
                self.send_json(sync_broker(str(payload.get("provider") or "")))
                return
            if parsed.path == "/api/brokers/configure":
                self.send_json(configure_broker(payload))
                return
            if parsed.path == "/api/brokers/okx-demo/strategy-preview":
                self.send_json(okx_strategy_preview(payload))
                return
            if parsed.path == "/api/brokers/okx-demo/order":
                self.send_json(okx_demo_place_order(payload))
                return
            if parsed.path == "/api/paper/advance":
                account = load_account()
                if account is None:
                    raise ValueError("请先创建模拟账户")
                data = PAPER_DATA_CACHE.get("default")
                if data is None:
                    replay_path = safe_project_path(account["replay_dataset"], ("data/processed/paper_trading",))
                    data = normalize_market_frame(replay_path)
                    PAPER_DATA_CACHE["default"] = data
                self.send_json(advance_account(account, data, int(payload.get("steps", 1))))
                return
            if parsed.path == "/api/paper/reset":
                reset_account()
                PAPER_DATA_CACHE.pop("default", None)
                self.send_json({"exists": False})
                return
            self.send_error_json(FileNotFoundError("Endpoint not found"), HTTPStatus.NOT_FOUND)
        except subprocess.TimeoutExpired:
            self.send_error_json(RuntimeError("Environment check timed out"), HTTPStatus.REQUEST_TIMEOUT)
        except Exception as exc:
            self.send_error_json(exc)

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        relative = unquote(parsed.path).lstrip("/") or "index.html"
        candidate = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in candidate.parents and candidate != STATIC_ROOT.resolve():
            return str(STATIC_ROOT / "404")
        return str(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the local quant research dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Quant dashboard: http://{args.host}:{args.port}")
    print("Simulation mode; OKX orders are Demo-only and live trading is disabled.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
