"""Self-contained public market-data clients used by the dashboard."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


SHANGHAI = ZoneInfo("Asia/Shanghai")
def _current_bar_start(interval: str) -> pd.Timestamp:
    """Return the start time (Asia/Shanghai wall clock) of the bar now forming."""
    now = pd.Timestamp.now(tz=SHANGHAI).tz_localize(None)
    if interval == "1d":
        return now.normalize()
    minutes = int(interval.rstrip("m"))
    return now.floor(f"{minutes}min")


def _drop_incomplete_candle(
    data: pd.DataFrame, interval: str, *, bar_label: str = "start"
) -> pd.DataFrame:
    """Exclude the currently-forming candle so signals never use an unfinished bar.

    ``bar_label="start"`` is for candles whose timestamp is the bar start (crypto,
    daily stocks). ``bar_label="end"`` is for A-share minute bars, whose Eastmoney
    timestamp is the bar end (e.g. 15:00 means the 14:00-15:00 bar).
    """
    if len(data) == 0:
        return data
    now = pd.Timestamp.now(tz=SHANGHAI).tz_localize(None)
    if bar_label == "end":
        if data.index[-1] > now:
            data = data.iloc[:-1].copy()
        return data
    boundary = _current_bar_start(interval)
    if data.index[-1] >= boundary:
        data = data.iloc[:-1].copy()
    return data


def fetch_market_candles(
    symbol: str,
    interval: str = "1d",
    limit: int = 1000,
    chart_path: Path | None = None,
    *,
    bar_label: str = "start",
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fetch completed Gate.io USDT spot candles without external helper scripts."""
    asset = str(symbol or "").strip().upper().replace("/USDT", "").replace("-USDT", "")
    if not asset.isalnum() or not 2 <= len(asset) <= 12:
        raise ValueError("Invalid crypto symbol")
    gate_interval = {"60m": "1h"}.get(interval, interval)
    if gate_interval not in {"15m", "30m", "1h", "4h", "8h", "1d", "7d"}:
        raise ValueError(f"Unsupported Gate.io interval: {interval}")
    query = urllib.parse.urlencode({
        "currency_pair": f"{asset}_USDT",
        "interval": gate_interval,
        "limit": str(min(max(limit, 20), 1000)),
    })
    request = urllib.request.Request(
        f"https://api.gateio.ws/api/v4/spot/candlesticks?{query}",
        headers={"Accept": "application/json", "User-Agent": "Quant-Dashboard/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        rows = json.loads(response.read().decode("utf-8"))
    if not isinstance(rows, list):
        raise RuntimeError(f"Gate.io returned an invalid response for {asset}")
    records = []
    for row in rows:
        try:
            records.append({
                "bar_start": pd.to_datetime(int(row[0]), unit="s"),
                "open": float(row[5]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[6]),
            })
        except (IndexError, TypeError, ValueError):
            continue
    data = pd.DataFrame(records)
    if data.empty:
        raise RuntimeError(f"No usable {interval} candles returned for {asset}")
    data = data.set_index("bar_start").sort_index()
    data = _drop_incomplete_candle(data, interval, bar_label=bar_label)
    payload: dict[str, object] = {
        "source": "gate.io",
        "symbol": asset,
        "interval": interval,
        "rows": len(data),
    }
    return data, payload


def fetch_tencent_daily(
    symbol: str,
    limit: int = 1000,
    *,
    bar_label: str = "start",
    timeout: int = 25,
) -> pd.DataFrame:
    """Fetch A-share daily candles from Tencent's public kline endpoint.

    Tencent's ``day`` series retains roughly 1000 bars (about four years),
    longer than the minute windows. Timestamps are trading dates; the bar for
    the current (still forming) trading day is dropped.
    """
    url = (
        "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/kline"
        f"?param={symbol},day,,,{min(max(limit, 20), 1000)}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = (payload.get("data", {}).get(symbol, {}) or {}).get("day") or []
    if not rows:
        raise RuntimeError(f"No daily candles returned by Tencent for {symbol}")
    records = []
    for row in rows:
        try:
            records.append(
                {
                    "bar_start": pd.to_datetime(row[0]),
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (IndexError, ValueError, TypeError):
            continue
    data = pd.DataFrame(records).set_index("bar_start").sort_index()
    if data.empty:
        raise RuntimeError(f"No usable daily candles returned by Tencent for {symbol}")
    return _drop_incomplete_candle(data, "1d", bar_label=bar_label)


def fetch_tencent_minutes(
    symbol: str,
    interval: str = "60m",
    limit: int = 1000,
    *,
    bar_label: str = "end",
) -> pd.DataFrame:
    """Fetch A-share minute candles from Tencent's public mkline endpoint.

    Tencent retains roughly six months of 60-minute bars (about 480 rows),
    longer than Eastmoney's ~320-bar window. Row timestamps are bar end times
    (e.g. 11:30 means the 10:30-11:30 bar), matching Eastmoney's minute
    convention; prices matched Eastmoney qfq exactly over the overlap checked
    for this project.
    """
    minute = interval.rstrip("m")
    url = (
        "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/mkline"
        f"?param={symbol},m{minute},,,{min(max(limit, 20), 1000)}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = (payload.get("data", {}).get(symbol, {}) or {}).get(f"m{minute}") or []
    if not rows:
        raise RuntimeError(f"No {interval} candles returned by Tencent for {symbol}")
    records = []
    for row in rows:
        try:
            records.append(
                {
                    "bar_start": pd.to_datetime(row[0], format="%Y%m%d%H%M"),
                    "open": float(row[1]),
                    "close": float(row[2]),
                    "high": float(row[3]),
                    "low": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        except (IndexError, ValueError, TypeError):
            continue
    data = pd.DataFrame(records).set_index("bar_start").sort_index()
    if data.empty:
        raise RuntimeError(f"No usable {interval} candles returned by Tencent for {symbol}")
    return _drop_incomplete_candle(data, interval, bar_label=bar_label)


def fetch_gate_candles(
    interval: str = "1d",
    limit: int = 1000,
    chart_path: Path | None = None,
    *,
    symbol: str = "BTC",
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Backward-compatible wrapper for Gate.io crypto candles."""
    return fetch_market_candles(symbol, interval, limit, chart_path, bar_label="start")
