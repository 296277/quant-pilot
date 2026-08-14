from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dashboard.server import asset_display_label, okx_strategy_preview


class DashboardServerTests(unittest.TestCase):
    def test_industry_renderer_is_not_shadowed_by_terminal_script(self) -> None:
        static_root = Path(__file__).resolve().parents[1] / "dashboard" / "static"
        app_script = (static_root / "app.js").read_text(encoding="utf-8")
        terminal_script = (static_root / "terminal.js").read_text(encoding="utf-8")
        self.assertIn("async function renderIndustry", app_script)
        self.assertNotIn("function renderIndustry", terminal_script)

    def test_public_panel_has_no_abupy_or_history_archive_entry(self) -> None:
        index = (Path(__file__).resolve().parents[1] / "dashboard" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("AbuPy", index)
        self.assertNotIn('id="view-history"', index)

    def test_okx_trading_workspace_precedes_large_account_tables(self) -> None:
        app_script = (Path(__file__).resolve().parents[1] / "dashboard" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("${tradingWorkspace}${accountSnapshot}", app_script)
        self.assertIn("restoreOkxStrategyDraft();", app_script)

    def test_known_symbol_uses_universe_name(self) -> None:
        label = asset_display_label({}, "tencent", "sz002230", "sz002230")
        self.assertEqual(label, "科大讯飞")

    def test_custom_label_takes_priority(self) -> None:
        label = asset_display_label({"custom_label": "我的观察标的"}, "tencent", "sz002230", "sz002230")
        self.assertEqual(label, "我的观察标的")

    def test_invalid_custom_label_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            asset_display_label({"custom_label": "x" * 41}, "tencent", "sz002230", "sz002230")

    def test_okx_strategy_preview_does_not_place_an_order(self) -> None:
        rows = []
        for index in range(300):
            close = 100 + index * 0.2 + np.sin(index / 8)
            rows.append({"timestamp": 1_700_000_000_000 + index * 86_400_000, "open": close - 0.1, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})
        with patch("dashboard.server.okx_public_candles", return_value=rows):
            preview = okx_strategy_preview({"inst_id": "BTC-USDT", "strategy_id": "adaptive_trend", "parameters": {"fast": 20, "slow": 80}})
        self.assertTrue(preview["demo"])
        self.assertIn(preview["action"], {"buy", "sell", "hold"})
        self.assertIn("target_fraction", preview)


if __name__ == "__main__":
    unittest.main()
