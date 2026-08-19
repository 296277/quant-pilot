from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard.paper_trading import (
    advance_account,
    cancel_order,
    load_account,
    orders_csv,
    place_manual_order,
    reset_account,
    restart_account,
    start_account,
)


def trending_stock(rows: int = 320) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=rows)
    close = np.linspace(10.0, 30.0, rows) + np.sin(np.arange(rows) / 15.0) * 0.2
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "close": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "volume": 1_000_000.0,
        },
        index=index,
    )


class PaperTradingTests(unittest.TestCase):
    def configuration(self) -> dict:
        return {
            "source": "tencent",
            "symbol": "sz000001",
            "label": "测试股票",
            "periods_per_year": 252,
            "strategy_id": "adaptive_trend",
            "strategy_name": "自适应趋势跟随",
            "strategy_family": "趋势",
            "parameters": {"fast": 5, "slow": 20},
            "initial_cash": 100_000,
            "buy_cost": 0.0005,
            "sell_cost": 0.001,
            "slippage": 0.0005,
            "replay_dataset": "data/processed/paper_trading/market.csv",
        }

    def test_stock_replay_uses_lots_and_persists(self) -> None:
        data = trending_stock()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            started = start_account(data, self.configuration(), path=path)
            self.assertTrue(started["exists"])
            self.assertEqual(started["progress"]["current"], 0)

            account = load_account(path)
            advanced = advance_account(account, data, 20, path=path)
            self.assertEqual(advanced["progress"]["current"], 20)
            self.assertEqual(len(advanced["equity_history"]), 21)
            filled_buys = [order for order in advanced["orders"] if order["side"] == "buy" and order["status"] == "filled"]
            self.assertTrue(filled_buys)
            self.assertEqual(filled_buys[0]["quantity"] % 100, 0)
            self.assertEqual(load_account(path)["current_index"], advanced["current_index"])

    def test_reset_removes_account(self) -> None:
        data = trending_stock()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            start_account(data, self.configuration(), path=path)
            self.assertIsNotNone(load_account(path))
            reset_account(path)
            self.assertIsNone(load_account(path))

    def test_fractional_target_does_not_use_all_cash(self) -> None:
        data = trending_stock()
        data["high"] = data["close"] * 1.001
        configuration = self.configuration()
        configuration.update({
            "strategy_id": "turtle_atr",
            "strategy_name": "海龟突破 + ATR",
            "parameters": {
                "entry_window": 20,
                "exit_window": 10,
                "atr_period": 20,
                "stop_atr": 2.0,
                "risk_fraction": 0.005,
                "max_exposure": 1.0,
            },
        })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            start_account(data, configuration, path=path)
            advanced = advance_account(load_account(path), data, 80, path=path)
            buys = [order for order in advanced["orders"] if order["side"] == "buy" and order["status"] == "filled"]
            self.assertTrue(buys)
            self.assertGreater(advanced["cash"], 0)
            self.assertGreater(advanced["applied_target_fraction"], 0)
            self.assertLess(advanced["applied_target_fraction"], 1)

    def test_manual_stock_orders_enforce_lots_cash_and_t_plus_one(self) -> None:
        data = trending_stock()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            start_account(data, self.configuration(), path=path)
            account = load_account(path)
            current_price = float(data["close"].iloc[account["current_index"] - 1])
            bought = place_manual_order(account, data, {"side": "buy", "quantity": 155, "order_type": "market", "price": current_price}, path=path)
            order = bought["orders"][-1]
            self.assertEqual(order["status"], "partial")
            self.assertEqual(order["quantity"], 100)
            self.assertEqual(order["requested_quantity"], 155)
            rejected = place_manual_order(load_account(path), data, {"side": "sell", "quantity": 100, "order_type": "market", "price": current_price}, path=path)
            self.assertEqual(rejected["orders"][-1]["status"], "rejected")
            self.assertEqual(rejected["orders"][-1]["rejection_reason"], "t_plus_one")

    def test_limit_order_can_be_cancelled_and_exported(self) -> None:
        data = trending_stock()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            start_account(data, self.configuration(), path=path)
            pending = place_manual_order(load_account(path), data, {"side": "buy", "quantity": 100, "order_type": "limit", "price": 1}, path=path)
            order_id = pending["orders"][-1]["id"]
            self.assertEqual(pending["orders"][-1]["status"], "pending")
            cancelled = cancel_order(load_account(path), order_id, path=path)
            self.assertEqual(cancelled["orders"][-1]["status"], "cancelled")
            exported = orders_csv(load_account(path))
            self.assertIn("signal_source", exported)
            self.assertIn("cancelled_by_user", exported)

    def test_realized_and_unrealized_pnl_are_separate_and_restart_clears_orders(self) -> None:
        data = trending_stock()
        config = self.configuration()
        config["periods_per_year"] = 365
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "account.json"
            start_account(data, config, path=path)
            place_manual_order(load_account(path), data, {"side": "buy", "quantity": 10.5, "price": 20}, path=path)
            account = load_account(path)
            account["position"]["last_buy_date"] = None
            account["current_date"] = "2025-01-01"
            from dashboard.paper_trading import save_account
            save_account(account, path)
            sold = place_manual_order(load_account(path), data, {"side": "sell", "quantity": 4.25, "price": 22}, path=path)
            self.assertNotEqual(sold["metrics"]["realized_pnl"], 0)
            self.assertNotEqual(sold["metrics"]["unrealized_pnl"], 0)
            restarted = restart_account(data, load_account(path), path=path)
            self.assertEqual(restarted["orders"], [])
            self.assertEqual(restarted["metrics"]["realized_pnl"], 0)


if __name__ == "__main__":
    unittest.main()
