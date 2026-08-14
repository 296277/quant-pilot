from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import market_terminal


class MarketTerminalTests(unittest.TestCase):
    def test_limit_threshold_covers_a_share_boards(self) -> None:
        self.assertEqual(market_terminal._limit_threshold({"code": "600000", "name": "浦发银行"}), 0.095)
        self.assertEqual(market_terminal._limit_threshold({"code": "300750", "name": "宁德时代"}), 0.195)
        self.assertEqual(market_terminal._limit_threshold({"code": "688981", "name": "中芯国际"}), 0.195)
        self.assertEqual(market_terminal._limit_threshold({"code": "920001", "name": "北交样例"}), 0.295)
        self.assertEqual(market_terminal._limit_threshold({"code": "600001", "name": "ST测试"}), 0.047)

    def test_stock_symbol_normalization(self) -> None:
        self.assertEqual(market_terminal._stock_symbol("600519"), "sh600519")
        self.assertEqual(market_terminal._stock_symbol("002230"), "sz002230")
        self.assertEqual(market_terminal._stock_symbol("920001"), "bj920001")

    def test_tencent_snapshot_maps_public_fields(self) -> None:
        fields = [""] * 39
        fields[0:7] = ["1", "贵州茅台", "600519", "1400", "1366", "1390", "1000"]
        fields[30:39] = ["20260813161402", "34", "2.5", "1410", "1380", "1400/1000/1000000", "1000", "1000000", "1.5"]
        quote = f'v_sh600519="{"~".join(fields)}";'
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "snapshot.json"
            with patch.object(market_terminal, "SNAPSHOT_FILE", cache), patch.object(market_terminal, "_http_text", return_value=quote):
                result = market_terminal.fetch_market_snapshot(force=True)
        item = result["items"][0]
        self.assertEqual(item["symbol"], "sh600519")
        self.assertEqual(item["name"], "贵州茅台")
        self.assertAlmostEqual(item["change"], 0.025)
        self.assertAlmostEqual(item["turnover"], 0.015)

    def test_eastmoney_fallback_maps_public_fields(self) -> None:
        response = {
            "data": {
                "total": 1,
                "diff": [{"f12": "600519", "f14": "贵州茅台", "f2": 1400, "f3": 2.5, "f4": 34, "f5": 10, "f6": 1000, "f8": 1.5, "f10": 1.2, "f15": 1410, "f16": 1380, "f17": 1390, "f18": 1366, "f20": 100000, "f21": 80000}],
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "snapshot.json"
            with patch.object(market_terminal, "SNAPSHOT_FILE", cache), patch.object(market_terminal, "_refresh_tencent_snapshot", side_effect=ConnectionError("Tencent unavailable")), patch.object(market_terminal, "_http_json", return_value=response):
                result = market_terminal.fetch_market_snapshot(force=True)
        item = result["items"][0]
        self.assertEqual(item["symbol"], "sh600519")
        self.assertEqual(item["name"], "贵州茅台")
        self.assertAlmostEqual(item["change"], 0.025)
        self.assertAlmostEqual(item["turnover"], 0.015)

    def test_snapshot_fallback_translates_disconnected_upstream(self) -> None:
        cached = {
            "epoch": 1,
            "retrieved_at": "2026-08-13T12:00:00",
            "source": "东方财富公开市场快照",
            "total": 1,
            "items": [{"symbol": "sh600519"}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "snapshot.json"
            cache.write_text(__import__("json").dumps(cached), encoding="utf-8")
            with (
                patch.object(market_terminal, "SNAPSHOT_FILE", cache),
                patch.object(market_terminal, "SNAPSHOT_PAGE_ATTEMPTS", 1),
                patch.object(market_terminal, "_refresh_tencent_snapshot", side_effect=ConnectionError("Tencent unavailable")),
                patch.object(market_terminal, "_http_json", side_effect=ConnectionError("Remote end closed connection without response")),
                patch.object(market_terminal.time, "sleep"),
            ):
                result = market_terminal.fetch_market_snapshot(force=True)
        self.assertTrue(result["stale"])
        self.assertIn("访问频率限制", result["warning"])
        self.assertNotIn("Remote end closed", result["warning"])

    def test_index_dashboard_uses_independent_cache(self) -> None:
        summary = {"symbol": "sh000001", "name": "上证指数", "price": 3000, "change": 0.01, "series": []}
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "indices.json"
            with (
                patch.object(market_terminal, "INDICES_FILE", cache),
                patch.object(market_terminal, "INDICES_SPEC", [("sh000001", "上证指数")]),
                patch.object(market_terminal, "_index_summary", return_value=summary) as fetch,
            ):
                first = market_terminal.index_dashboard(force=True)
                second = market_terminal.index_dashboard()
        self.assertEqual(first["indices"][0]["price"], 3000)
        self.assertEqual(second["indices"][0]["symbol"], "sh000001")
        self.assertEqual(fetch.call_count, 1)

    def test_industry_analysis_ranks_configured_groups(self) -> None:
        universe = {
            "stocks": [
                {"id": "alpha", "name": "行业甲", "assets": [{"symbol": "sh600001", "name": "甲一"}, {"symbol": "sh600002", "name": "甲二"}]},
                {"id": "beta", "name": "行业乙", "assets": [{"symbol": "sz000001", "name": "乙一"}]},
            ]
        }
        snapshot = {
            "retrieved_at": "2026-08-14T09:00:00",
            "source": "腾讯公开报价（项目观察池）",
            "items": [
                {"symbol": "sh600001", "change": 0.03, "amount": 300, "turnover": 0.02, "volume_ratio": 1},
                {"symbol": "sh600002", "change": 0.01, "amount": 200, "turnover": 0.01, "volume_ratio": 1},
                {"symbol": "sz000001", "change": -0.01, "amount": 100, "turnover": 0.01, "volume_ratio": 1},
            ],
        }
        with patch.object(market_terminal, "fetch_market_snapshot", return_value=snapshot):
            result = market_terminal.industry_analysis(universe)
        self.assertEqual(result["industries"][0]["id"], "alpha")
        self.assertAlmostEqual(result["industries"][0]["change"], 0.02)
        self.assertEqual(result["industries"][0]["amount"], 500)
        self.assertEqual(result["industries"][0]["up"], 2)

    def test_watchlist_add_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "watchlist.json"
            with patch.object(market_terminal, "WATCHLIST_FILE", path):
                added = market_terminal.update_watchlist({"action": "add", "symbol": "sh600519", "name": "贵州茅台"})
                self.assertEqual(added[0]["name"], "贵州茅台")
                removed = market_terminal.update_watchlist({"action": "remove", "symbol": "sh600519"})
                self.assertEqual(removed, [])

    def test_monitor_add_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rules = Path(temporary) / "rules.json"
            events = Path(temporary) / "events.json"
            with patch.object(market_terminal, "MONITOR_RULES_FILE", rules), patch.object(market_terminal, "MONITOR_EVENTS_FILE", events):
                state = market_terminal.update_monitor({"action": "add", "symbol": "sh600519", "name": "贵州茅台", "type": "price_above", "threshold": 1500})
                self.assertEqual(len(state["rules"]), 1)
                state = market_terminal.update_monitor({"action": "delete", "id": state["rules"][0]["id"]})
                self.assertEqual(state["rules"], [])


if __name__ == "__main__":
    unittest.main()
