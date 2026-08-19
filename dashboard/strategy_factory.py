"""Generate auditable strategy candidates for a selected asset.

Candidate parameters are derived from the first 70% training segment. Signals
are calculated after a bar closes and positions are applied at the next open.
The module is independent from the workspace's historical strategy files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Costs:
    buy: float = 0.0005
    sell: float = 0.0010


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain.div(loss.replace(0, np.nan))
    return 100 - 100 / (1 + rs)


def _true_range(data: pd.DataFrame) -> pd.Series:
    previous = data["close"].shift(1)
    return pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous).abs(),
            (data["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(data: pd.DataFrame, period: int) -> pd.Series:
    return _true_range(data).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _adx(data: pd.DataFrame, period: int) -> pd.Series:
    up = data["high"].diff()
    down = -data["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(data, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean().div(atr.replace(0, np.nan))
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean().div(atr.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs().div((plus_di + minus_di).replace(0, np.nan))
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _state_signal(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    state = 0.0
    values: list[float] = []
    for should_enter, should_exit in zip(entry.fillna(False), exit_.fillna(False)):
        if state == 0 and bool(should_enter):
            state = 1.0
        elif state > 0 and bool(should_exit):
            state = 0.0
        values.append(state)
    return pd.Series(values, index=entry.index, dtype=float)


def _state_with_atr_stop(
    entry: pd.Series,
    exit_: pd.Series,
    close: pd.Series,
    atr: pd.Series,
    stop_atr: float,
) -> tuple[pd.Series, pd.Series]:
    state = 0.0
    highest = np.nan
    values: list[float] = []
    stops: list[float] = []
    for enter, leave, price, volatility in zip(
        entry.fillna(False), exit_.fillna(False), close, atr
    ):
        stop = np.nan
        if state == 0 and bool(enter) and pd.notna(volatility):
            state = 1.0
            highest = float(price)
        elif state > 0:
            highest = max(float(highest), float(price))
            stop = highest - stop_atr * float(volatility) if pd.notna(volatility) else np.nan
            if bool(leave) or (pd.notna(stop) and float(price) < stop):
                state = 0.0
                highest = np.nan
                stop = np.nan
        values.append(state)
        stops.append(stop)
    return (
        pd.Series(values, index=close.index, dtype=float),
        pd.Series(stops, index=close.index, dtype=float),
    )


def _ledger(data: pd.DataFrame, desired_close: pd.Series, costs: Costs) -> pd.DataFrame:
    frame = data.copy().sort_index()
    frame["signal_close"] = desired_close.reindex(frame.index).fillna(0).clip(0, 1)
    frame["position_open"] = frame["signal_close"].shift(1).fillna(0.0)
    change = frame["position_open"].diff().fillna(frame["position_open"])
    frame["buy_turnover"] = change.clip(lower=0)
    frame["sell_turnover"] = (-change).clip(lower=0)
    if frame["position_open"].iloc[-1] > 0:
        frame.iloc[-1, frame.columns.get_loc("sell_turnover")] += frame["position_open"].iloc[-1]
    frame["asset_forward_return"] = frame["open"].shift(-1).div(frame["open"]).sub(1).fillna(0)
    frame["transaction_cost"] = frame["buy_turnover"] * costs.buy + frame["sell_turnover"] * costs.sell
    frame["strategy_return"] = frame["position_open"] * frame["asset_forward_return"] - frame["transaction_cost"]
    frame["benchmark_return"] = frame["asset_forward_return"].copy()
    frame.iloc[0, frame.columns.get_loc("benchmark_return")] -= costs.buy
    frame.iloc[-1, frame.columns.get_loc("benchmark_return")] -= costs.sell
    frame["strategy_equity"] = (1 + frame["strategy_return"]).cumprod()
    frame["benchmark_equity"] = (1 + frame["benchmark_return"]).cumprod()
    return frame


def _trades(ledger: pd.DataFrame, costs: Costs) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    entry_date = None
    entry_price = None
    for date, row in ledger.iterrows():
        if row["buy_turnover"] > 0 and entry_price is None:
            entry_date = pd.Timestamp(date)
            entry_price = float(row["open"])
        if row["sell_turnover"] > 0 and entry_price is not None:
            net = float(row["open"]) / entry_price - 1 - costs.buy - costs.sell
            records.append(
                {
                    "entry_date": entry_date,
                    "exit_date": pd.Timestamp(date),
                    "entry_price": entry_price,
                    "exit_price": float(row["open"]),
                    "holding_days": int((pd.Timestamp(date) - entry_date).days),
                    "net_return": net,
                    "won": bool(net > 0),
                }
            )
            entry_date = None
            entry_price = None
    return pd.DataFrame(records)


def _metrics(ledger: pd.DataFrame, costs: Costs, periods: int = 252) -> dict[str, Any]:
    returns = ledger["strategy_return"].fillna(0).astype(float)
    equity = (1 + returns).cumprod()
    benchmark = (1 + ledger["benchmark_return"].fillna(0).astype(float)).cumprod()
    std = returns.std(ddof=0)
    drawdown = equity.div(equity.cummax()).sub(1)
    trades = _trades(ledger, costs)
    years = len(returns) / periods
    return {
        "start": str(pd.Timestamp(ledger.index.min()).date()),
        "end": str(pd.Timestamp(ledger.index.max()).date()),
        "bars": len(ledger),
        "total_return": float(equity.iloc[-1] - 1),
        "benchmark_return": float(benchmark.iloc[-1] - 1),
        "excess_return": float(equity.iloc[-1] - benchmark.iloc[-1]),
        "annual_return": float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else None,
        "sharpe": float(returns.mean() / std * np.sqrt(periods)) if std > 0 else None,
        "max_drawdown": float(drawdown.min()),
        "exposure": float(ledger["position_open"].mean()),
        "trades": len(trades),
        "win_rate": float(trades["won"].mean()) if len(trades) else None,
        "cost_drag": float(ledger["transaction_cost"].sum()),
    }


def _trend(data: pd.DataFrame, fast: int, slow: int, costs: Costs) -> tuple[pd.DataFrame, dict[str, Any]]:
    ema_fast = data["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = data["close"].ewm(span=slow, adjust=False).mean()
    desired = ((ema_fast > ema_slow) & (data["close"] > ema_slow)).astype(float)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = ema_fast, ema_slow
    return ledger, {"fast": fast, "slow": slow}


def _breakout(data: pd.DataFrame, entry_window: int, exit_window: int, costs: Costs) -> tuple[pd.DataFrame, dict[str, Any]]:
    upper = data["high"].rolling(entry_window).max().shift(1)
    lower = data["low"].rolling(exit_window).min().shift(1)
    desired = _state_signal(data["close"] > upper, data["close"] < lower)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = upper, lower
    return ledger, {"entry_window": entry_window, "exit_window": exit_window}


def _bollinger(data: pd.DataFrame, window: int, width: float, costs: Costs) -> tuple[pd.DataFrame, dict[str, Any]]:
    middle = data["close"].rolling(window).mean()
    deviation = data["close"].rolling(window).std(ddof=0)
    lower = middle - width * deviation
    desired = _state_signal(data["close"] < lower, data["close"] >= middle)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = middle, lower
    return ledger, {"window": window, "width": width}


def _momentum(data: pd.DataFrame, lookback: int, filter_window: int, costs: Costs) -> tuple[pd.DataFrame, dict[str, Any]]:
    momentum = data["close"].pct_change(lookback)
    trend = data["close"].rolling(filter_window).mean()
    desired = ((momentum > 0) & (data["close"] > trend)).astype(float)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = momentum, trend
    return ledger, {"lookback": lookback, "filter_window": filter_window}


def _rsi_reversion(data: pd.DataFrame, period: int, entry: int, exit_: int, costs: Costs) -> tuple[pd.DataFrame, dict[str, Any]]:
    rsi = _rsi(data["close"], period)
    desired = _state_signal(rsi < entry, rsi > exit_)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = rsi, pd.Series(exit_, index=data.index)
    return ledger, {"period": period, "entry": entry, "exit": exit_}


def _supertrend_line(data: pd.DataFrame, period: int, multiplier: float) -> tuple[pd.Series, pd.Series]:
    volatility = _atr(data, period)
    midpoint = (data["high"] + data["low"]) / 2
    basic_upper = midpoint + multiplier * volatility
    basic_lower = midpoint - multiplier * volatility
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    trend_line = pd.Series(np.nan, index=data.index, dtype=float)
    close = data["close"]
    for index in range(1, len(data)):
        if pd.isna(volatility.iloc[index]):
            continue
        previous_upper = final_upper.iloc[index - 1]
        previous_lower = final_lower.iloc[index - 1]
        if pd.isna(previous_upper):
            previous_upper = basic_upper.iloc[index]
        if pd.isna(previous_lower):
            previous_lower = basic_lower.iloc[index]
        final_upper.iloc[index] = (
            basic_upper.iloc[index]
            if basic_upper.iloc[index] < previous_upper or close.iloc[index - 1] > previous_upper
            else previous_upper
        )
        final_lower.iloc[index] = (
            basic_lower.iloc[index]
            if basic_lower.iloc[index] > previous_lower or close.iloc[index - 1] < previous_lower
            else previous_lower
        )
        previous_trend = trend_line.iloc[index - 1]
        if pd.isna(previous_trend):
            trend_line.iloc[index] = final_lower.iloc[index] if close.iloc[index] >= final_lower.iloc[index] else final_upper.iloc[index]
        elif np.isclose(previous_trend, previous_upper, equal_nan=False):
            trend_line.iloc[index] = final_upper.iloc[index] if close.iloc[index] <= final_upper.iloc[index] else final_lower.iloc[index]
        else:
            trend_line.iloc[index] = final_lower.iloc[index] if close.iloc[index] >= final_lower.iloc[index] else final_upper.iloc[index]
    return trend_line, volatility


def _supertrend_adx(
    data: pd.DataFrame,
    atr_period: int,
    multiplier: float,
    adx_period: int,
    adx_threshold: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    line, volatility = _supertrend_line(data, atr_period, multiplier)
    strength = _adx(data, adx_period)
    desired = _state_signal(
        (data["close"] > line) & (strength >= adx_threshold),
        data["close"] < line,
    )
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = line, strength
    return ledger, {
        "atr_period": atr_period,
        "atr_multiplier": multiplier,
        "adx_period": adx_period,
        "adx_threshold": adx_threshold,
    }


def _turtle_atr(
    data: pd.DataFrame,
    entry_window: int,
    exit_window: int,
    atr_period: int,
    stop_atr: float,
    risk_fraction: float,
    max_exposure: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    upper = data["high"].rolling(entry_window).max().shift(1)
    lower = data["low"].rolling(exit_window).min().shift(1)
    volatility = _atr(data, atr_period)
    position = 0.0
    entry_price = np.nan
    entry_atr = np.nan
    desired: list[float] = []
    stops: list[float] = []
    for price, top, bottom, current_atr in zip(data["close"], upper, lower, volatility):
        stop = entry_price - stop_atr * entry_atr if position > 0 else np.nan
        if position == 0 and pd.notna(top) and pd.notna(current_atr) and price > top:
            atr_risk = stop_atr * float(current_atr) / float(price)
            position = min(max_exposure, risk_fraction / max(atr_risk, 1e-9))
            entry_price = float(price)
            entry_atr = float(current_atr)
            stop = entry_price - stop_atr * entry_atr
        elif position > 0 and ((pd.notna(bottom) and price < bottom) or price < stop):
            position = 0.0
            entry_price = np.nan
            entry_atr = np.nan
            stop = np.nan
        desired.append(position)
        stops.append(stop)
    ledger = _ledger(data, pd.Series(desired, index=data.index), costs)
    ledger["indicator_a"] = upper
    ledger["indicator_b"] = pd.Series(stops, index=data.index)
    return ledger, {
        "entry_window": entry_window,
        "exit_window": exit_window,
        "atr_period": atr_period,
        "stop_atr": stop_atr,
        "risk_fraction": risk_fraction,
        "max_exposure": max_exposure,
    }


def _bollinger_rsi(
    data: pd.DataFrame,
    window: int,
    width: float,
    rsi_period: int,
    rsi_entry: float,
    rsi_exit: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    middle = data["close"].rolling(window).mean()
    deviation = data["close"].rolling(window).std(ddof=0)
    lower = middle - width * deviation
    rsi = _rsi(data["close"], rsi_period)
    desired = _state_signal(
        (data["close"] < lower) & (rsi < rsi_entry),
        (data["close"] >= middle) | (rsi >= rsi_exit),
    )
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = lower, rsi
    return ledger, {
        "window": window,
        "width": width,
        "rsi_period": rsi_period,
        "rsi_entry": rsi_entry,
        "rsi_exit": rsi_exit,
    }


def _macd_volume(
    data: pd.DataFrame,
    fast: int,
    slow: int,
    signal_period: int,
    volume_window: int,
    volume_multiplier: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = data["close"]
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal = macd.ewm(span=signal_period, adjust=False).mean()
    volume = pd.to_numeric(data.get("volume", pd.Series(1.0, index=data.index)), errors="coerce").fillna(0)
    volume_average = volume.rolling(volume_window).mean()
    trend = close.ewm(span=slow, adjust=False).mean()
    desired = _state_signal(
        (macd > signal) & (macd > 0) & (volume > volume_average * volume_multiplier) & (close > trend),
        (macd < signal) | (close < trend),
    )
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = macd, signal
    return ledger, {
        "fast": fast,
        "slow": slow,
        "signal": signal_period,
        "volume_window": volume_window,
        "volume_multiplier": volume_multiplier,
    }


def _squeeze_breakout(
    data: pd.DataFrame,
    window: int,
    boll_width: float,
    keltner_width: float,
    atr_period: int,
    stop_atr: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = data["close"]
    middle = close.rolling(window).mean()
    deviation = close.rolling(window).std(ddof=0)
    boll_upper = middle + boll_width * deviation
    boll_lower = middle - boll_width * deviation
    volatility = _atr(data, atr_period)
    keltner_middle = close.ewm(span=window, adjust=False).mean()
    keltner_upper = keltner_middle + keltner_width * volatility
    keltner_lower = keltner_middle - keltner_width * volatility
    squeeze = (boll_upper < keltner_upper) & (boll_lower > keltner_lower)
    recent_squeeze = squeeze.rolling(8).max().shift(1).fillna(0).astype(bool)
    entry = (~squeeze) & recent_squeeze & (close > boll_upper) & (close > close.shift(1))
    desired, trailing_stop = _state_with_atr_stop(entry, close < middle, close, volatility, stop_atr)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = boll_upper, trailing_stop
    return ledger, {
        "window": window,
        "boll_width": boll_width,
        "keltner_width": keltner_width,
        "atr_period": atr_period,
        "stop_atr": stop_atr,
    }


def _multi_timeframe(
    data: pd.DataFrame,
    weekly_fast: int,
    weekly_slow: int,
    daily_ema: int,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = data["close"]
    weekly = close.resample("W-FRI").last()
    weekly_fast_line = weekly.ewm(span=weekly_fast, adjust=False).mean()
    weekly_slow_line = weekly.ewm(span=weekly_slow, adjust=False).mean()
    weekly_up = (weekly_fast_line > weekly_slow_line).reindex(data.index, method="ffill").eq(True)
    weekly_slow_daily = weekly_slow_line.reindex(data.index, method="ffill")
    daily_line = close.ewm(span=daily_ema, adjust=False).mean()
    desired = _state_signal(
        weekly_up & (close > daily_line) & (close.pct_change(5) > 0),
        (~weekly_up) | (close < daily_line),
    )
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = daily_line, weekly_slow_daily
    return ledger, {"weekly_fast": weekly_fast, "weekly_slow": weekly_slow, "daily_ema": daily_ema}


def _relative_strength(
    data: pd.DataFrame,
    lookback: int,
    top_fraction: float,
    trend_window: int,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    peer_columns = [column for column in data.columns if column.startswith("peer_close_")]
    if "benchmark_close" not in data or not peer_columns:
        raise ValueError("Relative-strength strategy requires benchmark and sector-member data")
    selected_return = data["close"].pct_change(lookback)
    benchmark_return = data["benchmark_close"].pct_change(lookback)
    peer_returns = [data[column].pct_change(lookback).rename(column) for column in peer_columns]
    cross_section = pd.concat([selected_return.rename("selected"), *peer_returns], axis=1)
    percentile = cross_section.rank(axis=1, pct=True)["selected"]
    trend = data["close"].ewm(span=trend_window, adjust=False).mean()
    entry = (selected_return > benchmark_return) & (percentile >= 1 - top_fraction) & (data["close"] > trend)
    exit_ = (selected_return <= benchmark_return) | (percentile < 0.5) | (data["close"] < trend)
    desired = _state_signal(entry, exit_)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = selected_return - benchmark_return, percentile
    return ledger, {"lookback": lookback, "top_fraction": top_fraction, "trend_window": trend_window}


def _regime_adaptive(
    data: pd.DataFrame,
    adx_period: int,
    adx_threshold: float,
    breakout_window: int,
    breakout_exit: int,
    boll_window: int,
    boll_width: float,
    rsi_period: int,
    rsi_entry: float,
    rsi_exit: float,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = data["close"]
    strength = _adx(data, adx_period)
    upper = data["high"].rolling(breakout_window).max().shift(1)
    lower_channel = data["low"].rolling(breakout_exit).min().shift(1)
    middle = close.rolling(boll_window).mean()
    lower_boll = middle - boll_width * close.rolling(boll_window).std(ddof=0)
    rsi = _rsi(close, rsi_period)
    state = 0.0
    mode = "none"
    desired: list[float] = []
    for price, adx_value, top, bottom, mid, band, rsi_value in zip(
        close, strength, upper, lower_channel, middle, lower_boll, rsi
    ):
        trending = pd.notna(adx_value) and adx_value >= adx_threshold
        if state == 0:
            if trending and pd.notna(top) and price > top:
                state, mode = 1.0, "trend"
            elif not trending and pd.notna(band) and pd.notna(rsi_value) and price < band and rsi_value < rsi_entry:
                state, mode = 1.0, "range"
        elif mode == "trend" and ((pd.notna(bottom) and price < bottom) or not trending):
            state, mode = 0.0, "none"
        elif mode == "range" and ((pd.notna(mid) and price >= mid) or (pd.notna(rsi_value) and rsi_value >= rsi_exit)):
            state, mode = 0.0, "none"
        desired.append(state)
    ledger = _ledger(data, pd.Series(desired, index=data.index), costs)
    ledger["indicator_a"], ledger["indicator_b"] = strength, upper
    return ledger, {
        "adx_period": adx_period,
        "adx_threshold": adx_threshold,
        "breakout_window": breakout_window,
        "breakout_exit": breakout_exit,
        "boll_window": boll_window,
        "boll_width": boll_width,
        "rsi_period": rsi_period,
        "rsi_entry": rsi_entry,
        "rsi_exit": rsi_exit,
    }


def _voting_strategy(
    data: pd.DataFrame,
    fast: int,
    slow: int,
    breakout_window: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
    rsi_period: int,
    entry_votes: int,
    exit_votes: int,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = data["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    channel = data["high"].rolling(breakout_window).max().shift(1)
    macd = close.ewm(span=macd_fast, adjust=False).mean() - close.ewm(span=macd_slow, adjust=False).mean()
    signal = macd.ewm(span=macd_signal, adjust=False).mean()
    rsi = _rsi(close, rsi_period)
    volume = pd.to_numeric(data.get("volume", pd.Series(1.0, index=data.index)), errors="coerce").fillna(0)
    volume_average = volume.rolling(20).mean()
    votes = pd.concat(
        [
            (ema_fast > ema_slow).astype(int),
            (close > channel).astype(int),
            (macd > signal).astype(int),
            ((rsi > 50) & (rsi < 72)).astype(int),
            (volume > volume_average).astype(int),
        ],
        axis=1,
    ).sum(axis=1)
    desired = _state_signal(votes >= entry_votes, votes <= exit_votes)
    ledger = _ledger(data, desired, costs)
    ledger["indicator_a"], ledger["indicator_b"] = votes, pd.Series(entry_votes, index=data.index)
    return ledger, {
        "fast": fast,
        "slow": slow,
        "breakout_window": breakout_window,
        "macd_fast": macd_fast,
        "macd_slow": macd_slow,
        "macd_signal": macd_signal,
        "rsi_period": rsi_period,
        "entry_votes": entry_votes,
        "exit_votes": exit_votes,
    }


def _builders(
    frame: pd.DataFrame,
    parameters: dict[str, Any],
    strategy_id: str,
    costs: Costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    p = parameters
    builders: dict[str, Callable[[], tuple[pd.DataFrame, dict[str, Any]]]] = {
        "adaptive_trend": lambda: _trend(frame, int(p["fast"]), int(p["slow"]), costs),
        "channel_breakout": lambda: _breakout(frame, int(p["entry_window"]), int(p["exit_window"]), costs),
        "bollinger_reversion": lambda: _bollinger(frame, int(p["window"]), float(p["width"]), costs),
        "rsi_reversion": lambda: _rsi_reversion(frame, int(p["period"]), int(p["entry"]), int(p["exit"]), costs),
        "filtered_momentum": lambda: _momentum(frame, int(p["lookback"]), int(p["filter_window"]), costs),
        "supertrend_adx": lambda: _supertrend_adx(frame, int(p["atr_period"]), float(p["atr_multiplier"]), int(p["adx_period"]), float(p["adx_threshold"]), costs),
        "turtle_atr": lambda: _turtle_atr(frame, int(p["entry_window"]), int(p["exit_window"]), int(p["atr_period"]), float(p["stop_atr"]), float(p["risk_fraction"]), float(p["max_exposure"]), costs),
        "bollinger_rsi": lambda: _bollinger_rsi(frame, int(p["window"]), float(p["width"]), int(p["rsi_period"]), float(p["rsi_entry"]), float(p["rsi_exit"]), costs),
        "macd_volume": lambda: _macd_volume(frame, int(p["fast"]), int(p["slow"]), int(p["signal"]), int(p["volume_window"]), float(p["volume_multiplier"]), costs),
        "squeeze_breakout": lambda: _squeeze_breakout(frame, int(p["window"]), float(p["boll_width"]), float(p["keltner_width"]), int(p["atr_period"]), float(p["stop_atr"]), costs),
        "multi_timeframe": lambda: _multi_timeframe(frame, int(p["weekly_fast"]), int(p["weekly_slow"]), int(p["daily_ema"]), costs),
        "relative_strength": lambda: _relative_strength(frame, int(p["lookback"]), float(p["top_fraction"]), int(p["trend_window"]), costs),
        "regime_adaptive": lambda: _regime_adaptive(frame, int(p["adx_period"]), float(p["adx_threshold"]), int(p["breakout_window"]), int(p["breakout_exit"]), int(p["boll_window"]), float(p["boll_width"]), int(p["rsi_period"]), float(p["rsi_entry"]), float(p["rsi_exit"]), costs),
        "signal_voting": lambda: _voting_strategy(frame, int(p["fast"]), int(p["slow"]), int(p["breakout_window"]), int(p["macd_fast"]), int(p["macd_slow"]), int(p["macd_signal"]), int(p["rsi_period"]), int(p["entry_votes"]), int(p["exit_votes"]), costs),
    }
    if strategy_id not in builders:
        raise ValueError(f"Unknown generated strategy: {strategy_id}")
    return builders[strategy_id]()


def build_candidate_ledger(
    data: pd.DataFrame,
    strategy_id: str,
    parameters: dict[str, Any],
    *,
    costs: Costs = Costs(),
) -> pd.DataFrame:
    """Rebuild a generated candidate as a full execution ledger."""
    ledger, _ = _builders(data.copy().sort_index(), parameters, strategy_id, costs)
    return ledger


def _profile(train: pd.DataFrame, periods: int) -> dict[str, Any]:
    annual_vol = float(train["close"].pct_change().std(ddof=0) * np.sqrt(periods))
    trend_strength = float(train["close"].iloc[-1] / train["close"].iloc[max(0, len(train) - 120)] - 1)
    if annual_vol >= 0.50:
        tier, trend, breakout, boll, rsi, momentum = "高波动", (20, 80), (40, 15), (30, 2.2), (14, 24, 52), (40, 100)
        adx_threshold, atr_multiplier, volume_multiplier, risk_fraction = 27, 3.5, 1.35, 0.0075
    elif annual_vol >= 0.32:
        tier, trend, breakout, boll, rsi, momentum = "中等波动", (15, 60), (30, 10), (25, 2.0), (14, 28, 55), (30, 80)
        adx_threshold, atr_multiplier, volume_multiplier, risk_fraction = 24, 3.0, 1.25, 0.01
    else:
        tier, trend, breakout, boll, rsi, momentum = "低波动", (10, 40), (20, 10), (20, 1.8), (14, 30, 58), (20, 60)
        adx_threshold, atr_multiplier, volume_multiplier, risk_fraction = 21, 2.5, 1.15, 0.0125
    return {
        "annual_volatility": annual_vol,
        "trend_strength_120": trend_strength,
        "volatility_tier": tier,
        "trend": trend,
        "breakout": breakout,
        "bollinger": boll,
        "rsi": rsi,
        "momentum": momentum,
        "adx_threshold": adx_threshold,
        "atr_multiplier": atr_multiplier,
        "volume_multiplier": volume_multiplier,
        "risk_fraction": risk_fraction,
    }


def _sample_series(ledger: pd.DataFrame, split: int) -> list[dict[str, Any]]:
    stride = max(1, len(ledger) // 300)
    sampled = ledger.iloc[::stride]
    return [
        {
            "date": index.isoformat(),
            "close": row.get("close"),
            "equity": row.get("strategy_equity"),
            "benchmark": row.get("benchmark_equity"),
            "position": row.get("position_open"),
            "indicator_a": row.get("indicator_a"),
            "indicator_b": row.get("indicator_b"),
            "is_test": bool(ledger.index.get_loc(index) >= split),
        }
        for index, row in sampled.iterrows()
    ]


PARAMETER_SPECS: dict[str, dict[str, Any]] = {
    "fast": {"label": "快周期", "min": 2, "max": 200, "step": 1, "integer": True},
    "slow": {"label": "慢周期", "min": 5, "max": 400, "step": 1, "integer": True},
    "entry_window": {"label": "入场窗口", "min": 5, "max": 250, "step": 1, "integer": True},
    "exit_window": {"label": "退出窗口", "min": 2, "max": 150, "step": 1, "integer": True},
    "window": {"label": "计算窗口", "min": 5, "max": 250, "step": 1, "integer": True},
    "width": {"label": "波动带宽", "min": 0.5, "max": 5, "step": 0.1},
    "period": {"label": "指标周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "entry": {"label": "入场阈值", "min": 1, "max": 80, "step": 1},
    "exit": {"label": "退出阈值", "min": 20, "max": 99, "step": 1},
    "lookback": {"label": "回看周期", "min": 5, "max": 300, "step": 1, "integer": True},
    "filter_window": {"label": "过滤周期", "min": 10, "max": 400, "step": 1, "integer": True},
    "atr_period": {"label": "ATR 周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "atr_multiplier": {"label": "ATR 倍数", "min": 0.5, "max": 10, "step": 0.1},
    "adx_period": {"label": "ADX 周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "adx_threshold": {"label": "ADX 阈值", "min": 5, "max": 60, "step": 1},
    "stop_atr": {"label": "ATR 止损", "min": 0.5, "max": 10, "step": 0.1},
    "risk_fraction": {"label": "单次风险比例", "min": 0.001, "max": 0.1, "step": 0.001},
    "max_exposure": {"label": "最大仓位", "min": 0.05, "max": 1, "step": 0.05},
    "rsi_period": {"label": "RSI 周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "rsi_entry": {"label": "RSI 入场", "min": 1, "max": 80, "step": 1},
    "rsi_exit": {"label": "RSI 退出", "min": 20, "max": 99, "step": 1},
    "signal": {"label": "信号周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "volume_window": {"label": "均量窗口", "min": 2, "max": 250, "step": 1, "integer": True},
    "volume_multiplier": {"label": "放量倍数", "min": 0.5, "max": 5, "step": 0.05},
    "boll_width": {"label": "布林带宽", "min": 0.5, "max": 5, "step": 0.1},
    "keltner_width": {"label": "Keltner 带宽", "min": 0.5, "max": 5, "step": 0.1},
    "weekly_fast": {"label": "周线快周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "weekly_slow": {"label": "周线慢周期", "min": 5, "max": 200, "step": 1, "integer": True},
    "daily_ema": {"label": "日线 EMA", "min": 2, "max": 250, "step": 1, "integer": True},
    "top_fraction": {"label": "板块前列比例", "min": 0.1, "max": 1, "step": 0.05},
    "trend_window": {"label": "趋势窗口", "min": 5, "max": 300, "step": 1, "integer": True},
    "breakout_window": {"label": "突破窗口", "min": 5, "max": 250, "step": 1, "integer": True},
    "breakout_exit": {"label": "突破退出窗口", "min": 2, "max": 150, "step": 1, "integer": True},
    "boll_window": {"label": "布林窗口", "min": 5, "max": 250, "step": 1, "integer": True},
    "macd_fast": {"label": "MACD 快周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "macd_slow": {"label": "MACD 慢周期", "min": 5, "max": 200, "step": 1, "integer": True},
    "macd_signal": {"label": "MACD 信号周期", "min": 2, "max": 100, "step": 1, "integer": True},
    "entry_votes": {"label": "入场票数", "min": 1, "max": 5, "step": 1, "integer": True},
    "exit_votes": {"label": "退出票数", "min": 0, "max": 4, "step": 1, "integer": True},
}


def strategy_parameter_schema(parameters: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": key, **PARAMETER_SPECS[key]} for key in parameters if key in PARAMETER_SPECS]


def validate_strategy_parameters(strategy_id: str, parameters: dict[str, Any]) -> dict[str, float | int]:
    if not isinstance(parameters, dict) or not parameters or len(parameters) > 20:
        raise ValueError("请选择策略并填写有效参数")
    normalized: dict[str, float | int] = {}
    for key, raw_value in parameters.items():
        spec = PARAMETER_SPECS.get(str(key))
        if spec is None:
            raise ValueError(f"不支持的策略参数：{key}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"参数 {key} 必须是数字") from exc
        if not np.isfinite(value) or value < spec["min"] or value > spec["max"]:
            raise ValueError(f"参数 {key} 必须在 {spec['min']} 到 {spec['max']} 之间")
        normalized[str(key)] = int(round(value)) if spec.get("integer") else value

    required = {
        "adaptive_trend": ("fast", "slow"),
        "channel_breakout": ("entry_window", "exit_window"),
        "bollinger_reversion": ("window", "width"),
        "rsi_reversion": ("period", "entry", "exit"),
        "filtered_momentum": ("lookback", "filter_window"),
        "supertrend_adx": ("atr_period", "atr_multiplier", "adx_period", "adx_threshold"),
        "turtle_atr": ("entry_window", "exit_window", "atr_period", "stop_atr", "risk_fraction", "max_exposure"),
        "bollinger_rsi": ("window", "width", "rsi_period", "rsi_entry", "rsi_exit"),
        "macd_volume": ("fast", "slow", "signal", "volume_window", "volume_multiplier"),
        "squeeze_breakout": ("window", "boll_width", "keltner_width", "atr_period", "stop_atr"),
        "multi_timeframe": ("weekly_fast", "weekly_slow", "daily_ema"),
        "relative_strength": ("lookback", "top_fraction", "trend_window"),
        "regime_adaptive": ("adx_period", "adx_threshold", "breakout_window", "breakout_exit", "boll_window", "boll_width", "rsi_period", "rsi_entry", "rsi_exit"),
        "signal_voting": ("fast", "slow", "breakout_window", "macd_fast", "macd_slow", "macd_signal", "rsi_period", "entry_votes", "exit_votes"),
    }.get(strategy_id)
    if required is None:
        raise ValueError(f"未知策略：{strategy_id}")
    missing = [key for key in required if key not in normalized]
    extra = [key for key in normalized if key not in required]
    if missing or extra:
        raise ValueError(f"策略参数不完整：缺少 {', '.join(missing) or '无'}；多余 {', '.join(extra) or '无'}")
    pairs = [("fast", "slow"), ("weekly_fast", "weekly_slow"), ("macd_fast", "macd_slow"), ("entry_window", "exit_window"), ("breakout_window", "breakout_exit"), ("entry", "exit"), ("rsi_entry", "rsi_exit"), ("entry_votes", "exit_votes")]
    for high_key, low_key in pairs:
        if high_key in normalized and low_key in normalized:
            if high_key in {"entry_window", "breakout_window", "entry_votes"}:
                valid = normalized[high_key] > normalized[low_key]
            else:
                valid = normalized[high_key] < normalized[low_key]
            if not valid:
                relation = "大于" if high_key in {"entry_window", "breakout_window", "entry_votes"} else "小于"
                raise ValueError(f"参数 {high_key} 必须{relation} {low_key}")
    return normalized


def evaluate_candidate(
    data: pd.DataFrame,
    strategy_id: str,
    parameters: dict[str, Any],
    *,
    costs: Costs = Costs(),
    periods_per_year: int = 252,
) -> dict[str, Any]:
    frame = data.copy().sort_index()
    for column in ("open", "close", "high", "low"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "close", "high", "low"])
    if len(frame) < 220:
        raise ValueError(f"At least 220 daily bars are required; received {len(frame)}")
    normalized = validate_strategy_parameters(strategy_id, parameters)
    split = int(len(frame) * 0.70)
    ledger, effective_parameters = _builders(frame, normalized, strategy_id, costs)
    full_metrics = _metrics(ledger, costs, periods_per_year)
    test_metrics = _metrics(ledger.iloc[split:].copy(), costs, periods_per_year)
    score = (test_metrics["sharpe"] or 0.0) + 2 * test_metrics["excess_return"] + test_metrics["max_drawdown"]
    trades = _trades(ledger, costs)
    return {
        "id": strategy_id,
        "parameters": effective_parameters,
        "parameter_schema": strategy_parameter_schema(effective_parameters),
        "full": full_metrics,
        "test": test_metrics,
        "research_score": float(score),
        "series": _sample_series(ledger, split),
        "trades": trades.tail(60).to_dict(orient="records"),
    }


def _definition(
    strategy_id: str,
    name: str,
    family: str,
    description: str,
    risk: str,
    entry_rule: str,
    exit_rule: str,
    position_rule: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": strategy_id,
        "name": name,
        "family": family,
        "description": description,
        "risk": risk,
        "entry_rule": entry_rule,
        "exit_rule": exit_rule,
        "position_rule": position_rule,
        "parameters": parameters,
    }


def generate_candidates(data: pd.DataFrame, *, costs: Costs = Costs(), periods_per_year: int = 252) -> dict[str, Any]:
    frame = data.copy().sort_index()
    for column in ("open", "close", "high", "low"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["open", "close", "high", "low"])
    if len(frame) < 220:
        raise ValueError(f"At least 220 daily bars are required; received {len(frame)}")
    split = int(len(frame) * 0.70)
    profile = _profile(frame.iloc[:split], periods_per_year)
    trend_fast, trend_slow = profile["trend"]
    breakout_entry, breakout_exit = profile["breakout"]
    boll_window, boll_width = profile["bollinger"]
    rsi_period, rsi_entry, rsi_exit = profile["rsi"]
    momentum_lookback, momentum_filter = profile["momentum"]
    definitions = [
        _definition("adaptive_trend", "自适应趋势跟随", "趋势", "EMA 方向与价格位置双重确认，适合持续性行情。", "震荡市容易反复切换并累积交易成本。", "快 EMA 高于慢 EMA 且收盘价位于慢 EMA 上方。", "快慢 EMA 关系反转或价格跌回慢 EMA 下方。", "满仓或空仓。", {"fast": trend_fast, "slow": trend_slow}),
        _definition("channel_breakout", "唐奇安通道突破", "突破", "突破前期高点入场、跌破短通道退出，强调捕捉大波段。", "假突破时可能快速回撤，交易次数通常较少。", "收盘价突破前期最高价。", "收盘价跌破短周期最低价。", "满仓或空仓。", {"entry_window": breakout_entry, "exit_window": breakout_exit}),
        _definition("bollinger_reversion", "布林超跌回归", "均值回归", "价格跌出波动带后等待回归中轨，偏逆向。", "单边下跌中可能过早接入，需关注最大回撤。", "收盘价跌破布林下轨。", "价格回到布林中轨。", "满仓或空仓。", {"window": boll_window, "width": boll_width}),
        _definition("rsi_reversion", "RSI 超卖修复", "超跌", "RSI 进入超卖区后等待修复，持仓逻辑直观。", "极端弱势中 RSI 可长期钝化，暴露时间可能偏高。", "RSI 低于训练段对应的超卖阈值。", "RSI 修复至退出阈值。", "满仓或空仓。", {"period": rsi_period, "entry": rsi_entry, "exit": rsi_exit}),
        _definition("filtered_momentum", "长趋势动量过滤", "动量", "中期动量为正且站上长期均线时持有，减少逆势参与。", "趋势反转时存在退出滞后，也可能错过快速 V 形反弹。", "中期收益为正且价格高于长期均线。", "任一条件失效。", "满仓或空仓。", {"lookback": momentum_lookback, "filter_window": momentum_filter}),
        _definition("supertrend_adx", "SuperTrend + ADX", "趋势风控", "仅在 ADX 确认趋势时跟随 SuperTrend，并以 ATR 波动带作为动态防线。", "ADX 与 SuperTrend 都有滞后，趋势末端仍可能回吐。", "价格站上 SuperTrend 且 ADX 超过趋势阈值。", "收盘价跌破 ATR 动态 SuperTrend 线。", "满仓或空仓；ATR 线动态收紧退出位置。", {"atr_period": 10, "atr_multiplier": profile["atr_multiplier"], "adx_period": 14, "adx_threshold": profile["adx_threshold"]}),
        _definition("turtle_atr", "海龟突破 + ATR", "突破风控", "通道突破捕捉趋势，按 ATR 止损距离计算风险仓位。", "横盘期可能连续假突破；低波动时仓位上限仍需约束。", "收盘价突破前期最高价。", "跌破短通道或入场价下方 N 倍 ATR。", "单次价格风险约占资金固定比例，仓位不超过上限。", {"entry_window": breakout_entry, "exit_window": breakout_exit, "atr_period": 20, "stop_atr": 2.0, "risk_fraction": profile["risk_fraction"], "max_exposure": 1.0}),
        _definition("bollinger_rsi", "布林带 + RSI", "双重均值回归", "只有价格跌破布林下轨且 RSI 同时超卖才入场，减少单指标过早抄底。", "持续下跌时两个指标仍会同时钝化，不能替代止损纪律。", "跌破布林下轨且 RSI 低于超卖阈值。", "回归中轨或 RSI 修复。", "满仓或空仓。", {"window": boll_window, "width": boll_width, "rsi_period": rsi_period, "rsi_entry": rsi_entry, "rsi_exit": rsi_exit}),
        _definition("macd_volume", "MACD + 成交量放大", "量价动量", "MACD 多头动量叠加成交量放大和长期方向确认。", "异常放量可能来自消息冲击，随后快速反转。", "MACD 位于零轴上方并上穿信号线，成交量显著高于均量。", "MACD 转弱或价格跌破趋势线。", "满仓或空仓。", {"fast": 12, "slow": 26, "signal": 9, "volume_window": 20, "volume_multiplier": profile["volume_multiplier"]}),
        _definition("squeeze_breakout", "波动率挤压突破", "波动突破", "布林带收进 Keltner 通道识别蓄势，释放后只跟随向上突破。", "挤压释放方向可能反复，跳空会放大实际滑点。", "近期出现挤压，释放后价格突破布林上轨。", "跌回中轨或触发 ATR 跟踪止损。", "满仓或空仓。", {"window": 20, "boll_width": 2.0, "keltner_width": 1.5, "atr_period": 14, "stop_atr": 2.5}),
        _definition("multi_timeframe", "周线 + 日线多周期趋势", "多周期", "周线过滤方向，日线负责进入和退出，降低逆大周期交易。", "周线确认较慢，快速反转阶段会延迟退出。", "周线快线高于慢线，日线站上 EMA 且短期动量为正。", "周线方向反转或日线跌破 EMA。", "满仓或空仓。", {"weekly_fast": 10, "weekly_slow": 30, "daily_ema": 20}),
        _definition("regime_adaptive", "市场状态自适应", "状态切换", "ADX 判断趋势/震荡状态，趋势市使用通道突破，震荡市使用布林带与 RSI 回归。", "市场状态切换存在识别延迟，临界区可能频繁换挡。", "趋势状态等待突破；震荡状态等待布林与 RSI 双重超卖。", "按当前子策略退出；趋势状态消失时先降为现金。", "两个子策略互斥，任一时点最多满仓。", {"adx_period": 14, "adx_threshold": profile["adx_threshold"], "breakout_window": breakout_entry, "breakout_exit": breakout_exit, "boll_window": boll_window, "boll_width": boll_width, "rsi_period": rsi_period, "rsi_entry": rsi_entry, "rsi_exit": rsi_exit}),
        _definition("signal_voting", "多信号投票组合", "信号组合", "趋势、突破、MACD、RSI 与成交量五类信号投票，避免单一指标决定仓位。", "高度相关的技术信号可能同时失效，投票不等于真正分散。", "五个子信号中至少三个同时支持做多。", "支持票数降至一个或更少。", "满仓或空仓；不使用未来票数。", {"fast": trend_fast, "slow": trend_slow, "breakout_window": breakout_entry, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "rsi_period": 14, "entry_votes": 3, "exit_votes": 1}),
    ]
    skipped: list[dict[str, str]] = []
    peer_columns = [column for column in frame.columns if column.startswith("peer_close_")]
    if "benchmark_close" in frame and peer_columns:
        definitions.append(
            _definition("relative_strength", "板块相对强弱", "横截面选股", "比较所选股票、板块成员与基准指数的滚动收益，仅持有板块前列且跑赢基准的标的。", "板块样本较少、成分变更和基准选择会影响结果，存在幸存者偏差。", "滚动收益跑赢基准，且强度位于板块前列并站上趋势线。", "不再跑赢基准、排名跌出前半或跌破趋势线。", "当前面板对所选股票执行；切换股票可比较同板块排名。", {"lookback": 60, "top_fraction": 0.4, "trend_window": 50})
        )
    else:
        skipped.append({"id": "relative_strength", "name": "板块相对强弱", "reason": "需要在线板块成员与基准行情"})

    candidates = []
    for definition in definitions:
        ledger, parameters = _builders(frame, definition["parameters"], definition["id"], costs)
        full_metrics = _metrics(ledger, costs, periods_per_year)
        test_ledger = ledger.iloc[split:].copy()
        test_metrics = _metrics(test_ledger, costs, periods_per_year)
        sharpe = test_metrics["sharpe"] or 0.0
        score = sharpe + 2 * test_metrics["excess_return"] + test_metrics["max_drawdown"]
        trades = _trades(ledger, costs)
        candidates.append(
            {
                **{key: definition[key] for key in ("id", "name", "family", "description", "risk", "entry_rule", "exit_rule", "position_rule")},
                "parameters": parameters,
                "parameter_schema": strategy_parameter_schema(parameters),
                "full": full_metrics,
                "test": test_metrics,
                "research_score": float(score),
                "series": _sample_series(ledger, split),
                "trades": trades.tail(60).to_dict(orient="records"),
            }
        )
    candidates.sort(key=lambda item: item["research_score"], reverse=True)
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank
    return {
        "profile": {key: value for key, value in profile.items() if key in {"annual_volatility", "trend_strength_120", "volatility_tier"}},
        "split": {
            "train_start": str(frame.index.min().date()),
            "train_end": str(frame.index[split - 1].date()),
            "test_start": str(frame.index[split].date()),
            "test_end": str(frame.index.max().date()),
            "train_bars": split,
            "test_bars": len(frame) - split,
        },
        "latest": {"date": str(frame.index.max().date()), "close": float(frame["close"].iloc[-1]), "change": float(frame["close"].pct_change().iloc[-1])},
        "candidates": candidates,
        "skipped_strategies": skipped,
    }
