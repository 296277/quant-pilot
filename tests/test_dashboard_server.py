from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dashboard.server import (
    asset_display_label,
    data_health,
    okx_strategy_preview,
    strategy_candidates,
    strategy_recalculate,
)
from tests.test_strategy_factory import sample_stock


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

    def test_language_switcher_is_persistent_and_translates_dynamic_content(self) -> None:
        static_root = Path(__file__).resolve().parents[1] / "dashboard" / "static"
        index = (static_root / "index.html").read_text(encoding="utf-8")
        i18n = (static_root / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('id="languageSelect"', index)
        self.assertIn('<option value="zh-CN">简体中文</option>', index)
        self.assertIn('<option value="en-US">English</option>', index)
        self.assertIn('<script src="/i18n.js" defer></script>', index)
        self.assertIn("quantpilot-language", i18n)
        self.assertIn("MutationObserver", i18n)
        self.assertIn("Market Dashboard", i18n)
        self.assertIn("Market Regime Adaptive", i18n)

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

    def test_data_health_exposes_status_for_each_source(self) -> None:
        result = data_health(refresh=False)
        self.assertEqual({item["id"] for item in result["sources"]}, {"a_share_quotes", "indices", "limit_pool", "gate_crypto", "local_files"})
        self.assertEqual(sum(result["summary"].values()), len(result["sources"]))

    def test_strategy_candidates_preserves_recalculation_request_and_data_status(self) -> None:
        prepared = (sample_stock(), "sz000001", "平安银行", 252, None)
        payload = {"source": "tencent", "group": "large_cap", "symbol": "sz000001", "buy_cost": 0.0005, "sell_cost": 0.001}
        with patch("dashboard.server.prepare_strategy_data", return_value=prepared):
            result = strategy_candidates(payload)
        self.assertEqual(result["request"]["symbol"], "sz000001")
        self.assertEqual(result["data_status"]["status"], "delayed")
        self.assertEqual(result["data_status"]["trade_date"], str(sample_stock().index.max().date()))

    def test_strategy_recalculation_returns_metrics_and_actual_trade_date(self) -> None:
        data = sample_stock()
        prepared = (data, "sz000001", "平安银行", 252, None)
        payload = {"source": "tencent", "group": "large_cap", "symbol": "sz000001", "strategy_id": "adaptive_trend", "parameters": {"fast": 12, "slow": 55}}
        with patch("dashboard.server.prepare_strategy_data", return_value=prepared):
            result = strategy_recalculate(payload)
        self.assertIn("full", result)
        self.assertIn("test", result)
        self.assertTrue(result["series"])
        self.assertEqual(result["data_status"]["trade_date"], str(data.index.max().date()))


if __name__ == "__main__":
    unittest.main()
