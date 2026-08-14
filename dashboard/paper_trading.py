"""Persistent local paper-trading account for historical market replay."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from dashboard.strategy_factory import Costs, build_candidate_ledger


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = PROJECT_ROOT / "data" / "processed" / "paper_trading" / "account.json"


def load_account(path: Path = DEFAULT_STATE_FILE) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_account(account: dict[str, Any], path: Path = DEFAULT_STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(account, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def reset_account(path: Path = DEFAULT_STATE_FILE) -> None:
    if path.exists():
        path.unlink()


def _validate_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _metrics(account: dict[str, Any]) -> dict[str, Any]:
    history = account.get("equity_history", [])
    equity = float(history[-1]["equity"]) if history else float(account["initial_cash"])
    initial = float(account["initial_cash"])
    peak = initial
    max_drawdown = 0.0
    for point in history:
        value = float(point["equity"])
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    position = account["position"]
    market_value = float(position.get("market_value", 0.0))
    unrealized = market_value - float(position.get("cost_value", 0.0)) if position.get("quantity", 0) else 0.0
    completed = [order for order in account.get("orders", []) if order["status"] == "filled"]
    return {
        "equity": equity,
        "cash": float(account["cash"]),
        "market_value": market_value,
        "total_pnl": equity - initial,
        "total_return": equity / initial - 1.0,
        "unrealized_pnl": unrealized,
        "max_drawdown": max_drawdown,
        "filled_orders": len(completed),
    }


def account_view(account: dict[str, Any] | None) -> dict[str, Any]:
    if account is None:
        return {"exists": False}
    result = dict(account)
    result["exists"] = True
    result["metrics"] = _metrics(account)
    result["progress"] = {
        "current": max(0, int(account["current_index"]) - int(account["start_index"])),
        "total": int(account["end_index"]) - int(account["start_index"]),
    }
    return result


def start_account(
    data: pd.DataFrame,
    configuration: dict[str, Any],
    *,
    path: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any]:
    initial_cash = _validate_number(configuration.get("initial_cash", 100_000), "initial_cash", 1_000, 1_000_000_000)
    buy_cost = _validate_number(configuration.get("buy_cost", 0.0005), "buy_cost", 0, 0.05)
    sell_cost = _validate_number(configuration.get("sell_cost", 0.001), "sell_cost", 0, 0.05)
    slippage = _validate_number(configuration.get("slippage", 0.0005), "slippage", 0, 0.05)
    if len(data) < 220:
        raise ValueError("Paper replay requires at least 220 daily bars")
    start_index = int(len(data) * 0.70)
    parameters = dict(configuration.get("parameters") or {})
    build_candidate_ledger(
        data,
        str(configuration["strategy_id"]),
        parameters,
        costs=Costs(buy=buy_cost, sell=sell_cost),
    )
    initial_date = str(pd.Timestamp(data.index[start_index - 1]).date())
    account = {
        "version": 2,
        "mode": "historical_replay",
        "status": "ready",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": configuration["source"],
        "symbol": configuration["symbol"],
        "label": configuration.get("label") or configuration["symbol"],
        "dataset": configuration.get("dataset"),
        "replay_dataset": configuration.get("replay_dataset"),
        "periods_per_year": int(configuration.get("periods_per_year", 252)),
        "market_type": "crypto" if int(configuration.get("periods_per_year", 252)) == 365 else "stock",
        "strategy_id": configuration["strategy_id"],
        "strategy_name": configuration["strategy_name"],
        "strategy_family": configuration.get("strategy_family"),
        "parameters": parameters,
        "initial_cash": initial_cash,
        "cash": initial_cash,
        "buy_cost": buy_cost,
        "sell_cost": sell_cost,
        "slippage": slippage,
        "start_index": start_index,
        "current_index": start_index,
        "end_index": len(data),
        "current_date": initial_date,
        "applied_target_fraction": 0.0,
        "position": {
            "quantity": 0.0,
            "average_cost": 0.0,
            "cost_value": 0.0,
            "market_value": 0.0,
            "last_price": float(data["close"].iloc[start_index - 1]),
            "last_buy_date": None,
        },
        "orders": [],
        "equity_history": [{"date": initial_date, "equity": initial_cash, "cash": initial_cash, "market_value": 0.0}],
    }
    save_account(account, path)
    return account_view(account)


def _append_order(
    account: dict[str, Any],
    *,
    date: str,
    side: str,
    status: str,
    price: float,
    quantity: float,
    fee: float = 0.0,
    reason: str = "strategy_signal",
) -> None:
    account["orders"].append(
        {
            "id": len(account["orders"]) + 1,
            "date": date,
            "side": side,
            "status": status,
            "price": price,
            "quantity": quantity,
            "notional": price * quantity,
            "fee": fee,
            "reason": reason,
        }
    )


def advance_account(
    account: dict[str, Any],
    data: pd.DataFrame,
    steps: int,
    *,
    path: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any]:
    steps = int(steps)
    if steps <= 0:
        raise ValueError("steps must be positive")
    costs = Costs(buy=float(account["buy_cost"]), sell=float(account["sell_cost"]))
    ledger = build_candidate_ledger(data, account["strategy_id"], account["parameters"], costs=costs)
    end = min(int(account["current_index"]) + steps, int(account["end_index"]))
    for index in range(int(account["current_index"]), end):
        row = ledger.iloc[index]
        date = str(pd.Timestamp(ledger.index[index]).date())
        target = min(1.0, max(0.0, float(row["position_open"])))
        applied_target = float(account.get("applied_target_fraction", 1.0 if account["position"].get("quantity", 0) else 0.0))
        open_price = float(row["open"])
        close_price = float(row["close"])
        previous_close = float(ledger["close"].iloc[index - 1])
        position = account["position"]
        quantity = float(position["quantity"])
        volume = float(row.get("volume", 1.0) or 0.0)
        is_stock = account["market_type"] == "stock"

        if target > applied_target + 1e-9:
            blocked = volume <= 0 or (is_stock and open_price >= previous_close * 1.095)
            if blocked:
                _append_order(account, date=date, side="buy", status="blocked", price=open_price, quantity=0, reason="suspended_or_limit_up")
            else:
                fill_price = open_price * (1 + float(account["slippage"]))
                available = float(account["cash"])
                equity_at_open = available + quantity * open_price
                allocation_change = target - applied_target
                budget = min(available, equity_at_open * allocation_change)
                raw_quantity = budget / (fill_price * (1 + float(account["buy_cost"])))
                trade_quantity = math.floor(raw_quantity / 100) * 100 if is_stock else math.floor(raw_quantity * 100_000_000) / 100_000_000
                if trade_quantity > 0:
                    gross = fill_price * trade_quantity
                    fee = gross * float(account["buy_cost"])
                    account["cash"] = available - gross - fee
                    previous_cost = float(position.get("cost_value", 0.0))
                    new_quantity = quantity + trade_quantity
                    position.update({
                        "quantity": new_quantity,
                        "average_cost": (previous_cost + gross + fee) / new_quantity,
                        "cost_value": previous_cost + gross + fee,
                        "last_buy_date": date,
                    })
                    _append_order(account, date=date, side="buy", status="filled", price=fill_price, quantity=trade_quantity, fee=fee)
                    account["applied_target_fraction"] = target
                else:
                    account["applied_target_fraction"] = target

        elif target < applied_target - 1e-9 and quantity > 0:
            t1_blocked = is_stock and position.get("last_buy_date") == date
            blocked = volume <= 0 or (is_stock and open_price <= previous_close * 0.905) or t1_blocked
            if blocked:
                reason = "t_plus_one" if t1_blocked else "suspended_or_limit_down"
                _append_order(account, date=date, side="sell", status="blocked", price=open_price, quantity=quantity, reason=reason)
            else:
                fill_price = open_price * (1 - float(account["slippage"]))
                if target <= 1e-9:
                    trade_quantity = quantity
                else:
                    fraction_to_sell = (applied_target - target) / max(applied_target, 1e-9)
                    raw_quantity = quantity * fraction_to_sell
                    trade_quantity = math.floor(raw_quantity / 100) * 100 if is_stock else math.floor(raw_quantity * 100_000_000) / 100_000_000
                gross = fill_price * trade_quantity
                fee = gross * float(account["sell_cost"])
                account["cash"] = float(account["cash"]) + gross - fee
                remaining = quantity - trade_quantity
                previous_cost = float(position.get("cost_value", 0.0))
                remaining_cost = previous_cost * remaining / quantity if quantity else 0.0
                _append_order(account, date=date, side="sell", status="filled", price=fill_price, quantity=trade_quantity, fee=fee)
                position.update({
                    "quantity": remaining,
                    "average_cost": remaining_cost / remaining if remaining else 0.0,
                    "cost_value": remaining_cost,
                    "last_buy_date": None if remaining == 0 else position.get("last_buy_date"),
                })
                account["applied_target_fraction"] = target
        elif target <= 1e-9 and quantity <= 0:
            account["applied_target_fraction"] = 0.0

        position["last_price"] = close_price
        position["market_value"] = float(position["quantity"]) * close_price
        equity = float(account["cash"]) + float(position["market_value"])
        account["equity_history"].append(
            {"date": date, "equity": equity, "cash": float(account["cash"]), "market_value": float(position["market_value"])}
        )
        account["current_date"] = date
        account["current_index"] = index + 1

    account["status"] = "completed" if int(account["current_index"]) >= int(account["end_index"]) else "running"
    save_account(account, path)
    return account_view(account)
