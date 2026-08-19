"""Persistent local paper-trading account for historical market replay."""

from __future__ import annotations

import json
import csv
import io
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


def restart_account(data: pd.DataFrame, account: dict[str, Any], *, path: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    """Restart the same paper account configuration from the holdout start."""
    configuration = {key: account.get(key) for key in (
        "source", "symbol", "label", "dataset", "strategy_id", "strategy_name", "strategy_family",
        "parameters", "initial_cash", "buy_cost", "sell_cost", "slippage", "periods_per_year",
        "replay_dataset", "limit_up_pct", "limit_down_pct",
    )}
    return start_account(data, configuration, path=path)


def _validate_number(value: Any, name: str, minimum: float, maximum: float) -> float:
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def _metrics(account: dict[str, Any]) -> dict[str, Any]:
    history = account.get("equity_history", [])
    equity = float(account.get("cash", account["initial_cash"])) + float(account.get("position", {}).get("market_value", 0.0))
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
    realized = float(account.get("realized_pnl", 0.0))
    completed = [order for order in account.get("orders", []) if order["status"] in {"filled", "partial"}]
    return {
        "equity": equity,
        "cash": float(account["cash"]),
        "market_value": market_value,
        "total_pnl": realized + unrealized,
        "realized_pnl": realized,
        "total_return": equity / initial - 1.0,
        "unrealized_pnl": unrealized,
        "fees_paid": float(account.get("fees_paid", 0.0)),
        "max_drawdown": max_drawdown,
        "filled_orders": len(completed),
        "pending_orders": sum(order["status"] == "pending" for order in account.get("orders", [])),
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
    limit_up_pct = _validate_number(configuration.get("limit_up_pct", 0.095), "limit_up_pct", 0.01, 0.30)
    limit_down_pct = _validate_number(configuration.get("limit_down_pct", 0.095), "limit_down_pct", 0.01, 0.30)
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
        "version": 3,
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
        "realized_pnl": 0.0,
        "fees_paid": 0.0,
        "lot_size": 100 if int(configuration.get("periods_per_year", 252)) == 252 else 0.000001,
        "min_order_quantity": 100 if int(configuration.get("periods_per_year", 252)) == 252 else 0.000001,
        "limit_up_pct": limit_up_pct,
        "limit_down_pct": limit_down_pct,
        "position": {
            "quantity": 0.0,
            "average_cost": 0.0,
            "cost_value": 0.0,
            "market_value": 0.0,
            "last_price": float(data["close"].iloc[start_index - 1]),
            "last_buy_date": None,
        },
        "orders": [],
        "equity_history": [{"date": initial_date, "equity": initial_cash, "cash": initial_cash, "market_value": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0}],
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
    signal_source: str = "strategy",
    requested_quantity: float | None = None,
    rejection_reason: str | None = None,
    realized_pnl: float = 0.0,
) -> None:
    account["orders"].append(
        {
            "id": len(account["orders"]) + 1,
            "date": date,
            "side": side,
            "status": status,
            "price": price,
            "quantity": quantity,
            "requested_quantity": quantity if requested_quantity is None else requested_quantity,
            "notional": price * quantity,
            "fee": fee,
            "reason": reason,
            "signal_source": signal_source,
            "rejection_reason": rejection_reason,
            "realized_pnl": realized_pnl,
        }
    )


def _step_quantity(account: dict[str, Any], quantity: float) -> float:
    lot = float(account.get("lot_size", 100))
    if lot >= 1:
        return math.floor(quantity / lot) * lot
    return math.floor(quantity / lot) * lot


def _fill_manual_order(
    account: dict[str, Any],
    *,
    side: str,
    requested_quantity: float,
    price: float,
    date: str,
    signal_source: str = "manual",
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    position = account["position"]
    is_stock = account["market_type"] == "stock"
    requested_quantity = float(requested_quantity)
    quantity = _step_quantity(account, requested_quantity)
    rejection = None
    fee = 0.0
    realized = 0.0
    if quantity <= 0:
        rejection = "below_minimum_or_lot"
    elif side == "buy":
        affordable = float(account["cash"]) / (price * (1 + float(account["buy_cost"]))) if price > 0 else 0.0
        fill_quantity = min(quantity, _step_quantity(account, affordable))
        if fill_quantity <= 0:
            rejection = "insufficient_cash"
        else:
            quantity = fill_quantity
            gross = price * quantity
            fee = gross * float(account["buy_cost"])
            previous_cost = float(position.get("cost_value", 0.0))
            account["cash"] = float(account["cash"]) - gross - fee
            new_quantity = float(position["quantity"]) + quantity
            position.update({
                "quantity": new_quantity,
                "average_cost": (previous_cost + gross + fee) / new_quantity,
                "cost_value": previous_cost + gross + fee,
                "last_buy_date": date,
            })
            account["fees_paid"] = float(account.get("fees_paid", 0.0)) + fee
    elif side == "sell":
        available = float(position.get("quantity", 0.0))
        if is_stock and position.get("last_buy_date") == date:
            rejection = "t_plus_one"
        elif available <= 0:
            rejection = "insufficient_position"
        else:
            quantity = min(quantity, available)
            quantity = _step_quantity(account, quantity)
            if quantity <= 0:
                rejection = "below_minimum_or_lot"
            else:
                gross = price * quantity
                fee = gross * float(account["sell_cost"])
                previous_cost = float(position.get("cost_value", 0.0))
                cost_basis = previous_cost * quantity / available
                realized = gross - fee - cost_basis
                account["cash"] = float(account["cash"]) + gross - fee
                remaining = available - quantity
                position.update({
                    "quantity": remaining,
                    "average_cost": (previous_cost - cost_basis) / remaining if remaining else 0.0,
                    "cost_value": previous_cost - cost_basis,
                    "last_buy_date": None if remaining <= 0 else position.get("last_buy_date"),
                })
                account["realized_pnl"] = float(account.get("realized_pnl", 0.0)) + realized
                account["fees_paid"] = float(account.get("fees_paid", 0.0)) + fee
    else:
        raise ValueError("side must be buy or sell")
    status = "rejected" if rejection else "partial" if quantity < requested_quantity else "filled"
    if existing is None:
        _append_order(account, date=date, side=side, status=status, price=price, quantity=0 if rejection else quantity,
                      fee=fee, reason="manual_order" if not rejection else rejection, signal_source=signal_source,
                      requested_quantity=requested_quantity, rejection_reason=rejection, realized_pnl=realized)
        order = account["orders"][-1]
    else:
        existing.update({"status": status, "price": price, "quantity": 0 if rejection else quantity,
                         "requested_quantity": requested_quantity, "notional": 0 if rejection else price * quantity,
                         "fee": fee, "reason": "manual_order" if not rejection else rejection,
                         "rejection_reason": rejection, "realized_pnl": realized})
        order = existing
    return order


def place_manual_order(
    account: dict[str, Any],
    data: pd.DataFrame,
    configuration: dict[str, Any],
    *,
    path: Path = DEFAULT_STATE_FILE,
) -> dict[str, Any]:
    side = str(configuration.get("side") or "").lower()
    requested = _validate_number(configuration.get("quantity", 0), "quantity", 0.00000001, 1_000_000_000)
    if int(account["current_index"]) <= 0:
        raise ValueError("模拟账户尚未有可用行情")
    index = min(int(account["current_index"]) - 1, len(data) - 1)
    date = str(pd.Timestamp(data.index[index]).date())
    order_type = str(configuration.get("order_type") or "market").lower()
    if order_type not in {"market", "limit"}:
        raise ValueError("order_type must be market or limit")
    if order_type == "market":
        reference = float(data["close"].iloc[index])
        price = reference * (1 + float(account["slippage"]) if side == "buy" else 1 - float(account["slippage"]))
    else:
        price = _validate_number(configuration.get("price"), "price", 0.00000001, 1_000_000_000)
    if order_type == "limit":
        _append_order(account, date=date, side=side, status="pending", price=price, quantity=0,
                      reason="limit_order_waiting", signal_source="manual", requested_quantity=requested)
        account["orders"][-1]["limit_price"] = price
        save_account(account, path)
        return account_view(account)
    if account["market_type"] == "stock" and index > 0:
        previous = float(data["close"].iloc[index - 1])
        limit = float(account.get("limit_up_pct", 0.095)) if side == "buy" else float(account.get("limit_down_pct", 0.095))
        if (side == "buy" and price >= previous * (1 + limit)) or (side == "sell" and price <= previous * (1 - limit)):
            _append_order(account, date=date, side=side, status="rejected", price=price, quantity=0,
                          reason="price_limit", signal_source="manual", requested_quantity=requested,
                          rejection_reason="price_limit")
        else:
            _fill_manual_order(account, side=side, requested_quantity=requested, price=price, date=date)
    else:
        _fill_manual_order(account, side=side, requested_quantity=requested, price=price, date=date)
    account["position"]["last_price"] = float(data["close"].iloc[index])
    account["position"]["market_value"] = float(account["position"]["quantity"]) * account["position"]["last_price"]
    save_account(account, path)
    return account_view(account)


def cancel_order(account: dict[str, Any], order_id: int, *, path: Path = DEFAULT_STATE_FILE) -> dict[str, Any]:
    for order in account.get("orders", []):
        if int(order.get("id", -1)) == int(order_id):
            if order.get("status") != "pending":
                raise ValueError("只有待成交订单可以撤单")
            order["status"] = "cancelled"
            order["reason"] = "cancelled_by_user"
            order["rejection_reason"] = "cancelled_by_user"
            save_account(account, path)
            return account_view(account)
    raise ValueError("未找到订单")


def orders_csv(account: dict[str, Any]) -> str:
    fields = ["id", "date", "side", "status", "price", "quantity", "requested_quantity", "notional", "fee", "realized_pnl", "signal_source", "reason", "rejection_reason"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(account.get("orders", []))
    return output.getvalue()


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
    account.setdefault("realized_pnl", 0.0)
    account.setdefault("fees_paid", 0.0)
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

        # Limit orders created by the manual trading panel are evaluated against
        # the replay bar before the strategy signal is applied.
        for pending in account.get("orders", []):
            if pending.get("status") != "pending":
                continue
            limit_price = float(pending.get("limit_price", pending.get("price", 0)))
            triggered = (pending["side"] == "buy" and float(row["low"]) <= limit_price) or (pending["side"] == "sell" and float(row["high"]) >= limit_price)
            if triggered:
                _fill_manual_order(account, side=pending["side"], requested_quantity=float(pending.get("requested_quantity", 0)), price=limit_price, date=date, existing=pending)
        quantity = float(position["quantity"])

        if target > applied_target + 1e-9:
            blocked = volume <= 0 or (is_stock and open_price >= previous_close * 1.095)
            if blocked:
                _append_order(account, date=date, side="buy", status="blocked", price=open_price, quantity=0, reason="suspended_or_limit_up", signal_source=f"strategy:{account['strategy_id']}", rejection_reason="suspended_or_limit_up")
            else:
                fill_price = open_price * (1 + float(account["slippage"]))
                available = float(account["cash"])
                equity_at_open = available + quantity * open_price
                allocation_change = target - applied_target
                budget = min(available, equity_at_open * allocation_change)
                raw_quantity = budget / (fill_price * (1 + float(account["buy_cost"])))
                trade_quantity = _step_quantity(account, raw_quantity)
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
                    account["fees_paid"] = float(account.get("fees_paid", 0.0)) + fee
                    _append_order(account, date=date, side="buy", status="filled", price=fill_price, quantity=trade_quantity, fee=fee, requested_quantity=raw_quantity, signal_source=f"strategy:{account['strategy_id']}")
                    account["applied_target_fraction"] = target
                else:
                    account["applied_target_fraction"] = target

        elif target < applied_target - 1e-9 and quantity > 0:
            t1_blocked = is_stock and position.get("last_buy_date") == date
            blocked = volume <= 0 or (is_stock and open_price <= previous_close * 0.905) or t1_blocked
            if blocked:
                reason = "t_plus_one" if t1_blocked else "suspended_or_limit_down"
                _append_order(account, date=date, side="sell", status="blocked", price=open_price, quantity=quantity, reason=reason, signal_source=f"strategy:{account['strategy_id']}", rejection_reason=reason)
            else:
                fill_price = open_price * (1 - float(account["slippage"]))
                if target <= 1e-9:
                    trade_quantity = quantity
                else:
                    fraction_to_sell = (applied_target - target) / max(applied_target, 1e-9)
                    raw_quantity = quantity * fraction_to_sell
                    trade_quantity = _step_quantity(account, raw_quantity)
                gross = fill_price * trade_quantity
                fee = gross * float(account["sell_cost"])
                account["cash"] = float(account["cash"]) + gross - fee
                remaining = quantity - trade_quantity
                previous_cost = float(position.get("cost_value", 0.0))
                remaining_cost = previous_cost * remaining / quantity if quantity else 0.0
                cost_basis = previous_cost - remaining_cost
                realized = gross - fee - cost_basis
                account["realized_pnl"] = float(account.get("realized_pnl", 0.0)) + realized
                account["fees_paid"] = float(account.get("fees_paid", 0.0)) + fee
                _append_order(account, date=date, side="sell", status="filled", price=fill_price, quantity=trade_quantity, fee=fee, requested_quantity=raw_quantity if target > 1e-9 else quantity, signal_source=f"strategy:{account['strategy_id']}", realized_pnl=realized)
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
            {"date": date, "equity": equity, "cash": float(account["cash"]), "market_value": float(position["market_value"]),
             "realized_pnl": float(account.get("realized_pnl", 0.0)),
             "unrealized_pnl": float(position["market_value"]) - float(position.get("cost_value", 0.0)) if position.get("quantity", 0) else 0.0}
        )
        account["current_date"] = date
        account["current_index"] = index + 1

    account["status"] = "completed" if int(account["current_index"]) >= int(account["end_index"]) else "running"
    save_account(account, path)
    return account_view(account)
