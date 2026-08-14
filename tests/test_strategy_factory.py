from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from dashboard.strategy_factory import Costs, _ledger, build_candidate_ledger, generate_candidates


def sample_stock(rows: int = 320) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=rows)
    trend = np.linspace(20.0, 34.0, rows)
    cycle = np.sin(np.arange(rows) / 11.0) * 1.8
    close = trend + cycle
    return pd.DataFrame(
        {
            "open": close * (1 + np.cos(np.arange(rows) / 7.0) * 0.002),
            "close": close,
            "high": close * 1.012,
            "low": close * 0.988,
            "volume": 1_000_000,
        },
        index=index,
    )


def sample_stock_with_sector(rows: int = 320) -> pd.DataFrame:
    data = sample_stock(rows)
    step = np.arange(rows)
    data["benchmark_close"] = np.linspace(20.0, 29.0, rows) + np.sin(step / 17.0)
    data["peer_close_a"] = np.linspace(18.0, 27.0, rows) + np.sin(step / 13.0) * 1.4
    data["peer_close_b"] = np.linspace(22.0, 26.0, rows) + np.cos(step / 19.0) * 1.2
    data["peer_close_c"] = np.linspace(16.0, 23.0, rows) + np.sin(step / 9.0) * 0.8
    return data


class StrategyFactoryTests(unittest.TestCase):
    def test_signal_is_executed_at_next_open(self) -> None:
        data = sample_stock(20)
        desired = pd.Series([0, 0, 1, 1, 0] + [0] * 15, index=data.index, dtype=float)
        ledger = _ledger(data, desired, Costs())
        self.assertEqual(ledger["position_open"].iloc[2], 0.0)
        self.assertEqual(ledger["position_open"].iloc[3], 1.0)
        self.assertEqual(ledger["position_open"].iloc[5], 0.0)

    def test_held_out_prices_do_not_change_generated_parameters(self) -> None:
        original = sample_stock()
        altered = original.copy()
        split = int(len(original) * 0.70)
        altered.iloc[split:, altered.columns.get_loc("close")] *= np.linspace(1.0, 2.0, len(altered) - split)
        altered.iloc[split:, altered.columns.get_loc("open")] *= np.linspace(1.0, 2.0, len(altered) - split)
        altered.iloc[split:, altered.columns.get_loc("high")] *= np.linspace(1.0, 2.0, len(altered) - split)
        altered.iloc[split:, altered.columns.get_loc("low")] *= np.linspace(1.0, 2.0, len(altered) - split)
        first = generate_candidates(original)
        second = generate_candidates(altered)
        self.assertEqual(first["profile"], second["profile"])
        self.assertEqual(
            {item["id"]: item["parameters"] for item in first["candidates"]},
            {item["id"]: item["parameters"] for item in second["candidates"]},
        )

    def test_generates_complete_candidate_catalog(self) -> None:
        result = generate_candidates(sample_stock_with_sector())
        ids = {item["id"] for item in result["candidates"]}
        requested = {
            "supertrend_adx",
            "turtle_atr",
            "bollinger_rsi",
            "macd_volume",
            "squeeze_breakout",
            "multi_timeframe",
            "relative_strength",
            "regime_adaptive",
            "signal_voting",
        }
        self.assertEqual(len(result["candidates"]), 14)
        self.assertTrue(requested.issubset(ids))
        self.assertEqual(result["split"]["train_bars"], 224)

    def test_local_data_skips_relative_strength_with_reason(self) -> None:
        result = generate_candidates(sample_stock())
        self.assertEqual(len(result["candidates"]), 13)
        self.assertEqual(result["skipped_strategies"][0]["id"], "relative_strength")

    def test_every_candidate_rebuilds_without_lookahead(self) -> None:
        original = sample_stock_with_sector(360)
        result = generate_candidates(original)
        cutoff = 224
        changed = original.copy()
        multiplier = np.linspace(1.5, 3.0, len(changed) - cutoff - 1)
        for column in ("open", "close", "high", "low", "benchmark_close", "peer_close_a", "peer_close_b", "peer_close_c"):
            changed.iloc[cutoff + 1 :, changed.columns.get_loc(column)] *= multiplier
        for candidate in result["candidates"]:
            first = build_candidate_ledger(original, candidate["id"], candidate["parameters"])
            second = build_candidate_ledger(changed, candidate["id"], candidate["parameters"])
            pd.testing.assert_series_equal(
                first["signal_close"].iloc[: cutoff + 1],
                second["signal_close"].iloc[: cutoff + 1],
                check_names=False,
            )

    def test_turtle_uses_fractional_atr_risk_position(self) -> None:
        data = sample_stock_with_sector(360)
        data["high"] = data["close"] * 1.001
        result = generate_candidates(data)
        candidate = next(item for item in result["candidates"] if item["id"] == "turtle_atr")
        ledger = build_candidate_ledger(data, candidate["id"], candidate["parameters"])
        active = ledger.loc[ledger["position_open"] > 0, "position_open"]
        self.assertFalse(active.empty)
        self.assertTrue((active < 1.0).any())


if __name__ == "__main__":
    unittest.main()
