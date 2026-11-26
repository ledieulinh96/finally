"""Atomic trade execution (PLAN.md §7: one ``BEGIN IMMEDIATE`` transaction)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .connection import PORTFOLIO_ID, DBPath, new_id, now_iso, transaction
from .repository import get_cash, insert_snapshot, read_cash

PriceLookup = Callable[[str], int | None]


@dataclass(frozen=True, slots=True)
class TradeResult:
    success: bool
    error: str | None
    ticker: str
    side: str
    quantity: int
    price: int
    cash_balance: float
    opened: bool = False
    closed: bool = False
    total_value: float | None = None

    def to_response(self) -> dict[str, Any]:
        """PLAN §8 ``POST /api/portfolio/trade`` response body."""
        if not self.success:
            return {"success": False, "error": self.error}
        return {
            "success": True,
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "cash_balance": self.cash_balance,
        }


def _safe_lookup(lookup: PriceLookup | None, ticker: str) -> int | None:
    if lookup is None:
        return None
    try:
        price = lookup(ticker)
    except Exception:
        return None
    return price if price and price > 0 else None


def execute_trade(
    ticker: str,
    side: str,
    quantity: int,
    price: int,
    price_lookup: PriceLookup | None = None,
    *,
    path: DBPath | None = None,
) -> TradeResult:
    """Execute a market order at ``price`` atomically and record a snapshot."""

    def fail(error: str, cash: float | None = None) -> TradeResult:
        if cash is None:
            cash = get_cash(path=path)
        return TradeResult(False, error, ticker, side, quantity, price, cash)

    if side not in ("buy", "sell"):
        return fail("Invalid side")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        return fail("Invalid quantity")
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        return fail("Invalid price")

    ts = now_iso()
    with transaction(path) as conn:
        cash = read_cash(conn)
        row = conn.execute(
            "SELECT quantity, avg_cost FROM positions WHERE ticker = ?", (ticker,)
        ).fetchone()
        held = int(row["quantity"]) if row else 0
        avg_cost = float(row["avg_cost"]) if row else 0.0
        cost = quantity * price
        opened = closed = False

        if side == "buy":
            if cost > cash:
                return fail("Insufficient cash", cash)
            cash -= cost
            new_qty = held + quantity
            new_avg = (held * avg_cost + quantity * price) / new_qty
            if row:
                conn.execute(
                    "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? "
                    "WHERE ticker = ?",
                    (new_qty, new_avg, ts, ticker),
                )
            else:
                conn.execute(
                    "INSERT INTO positions (ticker, quantity, avg_cost, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (ticker, new_qty, new_avg, ts),
                )
                opened = True
        else:
            if quantity > held:
                return fail("Insufficient shares", cash)
            cash += cost
            new_qty = held - quantity
            if new_qty == 0:
                conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker,))
                closed = True
            else:
                conn.execute(
                    "UPDATE positions SET quantity = ?, updated_at = ? WHERE ticker = ?",
                    (new_qty, ts, ticker),
                )

        conn.execute(
            "UPDATE portfolio_state SET cash_balance = ?, updated_at = ? WHERE id = ?",
            (cash, ts, PORTFOLIO_ID),
        )
        conn.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (new_id(), ticker, side, quantity, price, ts),
        )

        total = cash
        for pos in conn.execute("SELECT ticker, quantity, avg_cost FROM positions"):
            t = pos["ticker"]
            mark = price if t == ticker else _safe_lookup(price_lookup, t)
            total += pos["quantity"] * (mark if mark is not None else pos["avg_cost"])
        insert_snapshot(conn, total)

    return TradeResult(True, None, ticker, side, quantity, price, cash, opened, closed, total)
