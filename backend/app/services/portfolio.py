"""PortfolioService — the single entry point for trades, watchlist and valuation.

Used by both the REST routes and the LLM chat flow so validation and side
effects (tracker re-sync, snapshots, name registry) are identical. See
``planning/SERVICES_INTERFACE.md``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from os import PathLike

from .. import db
from ..market import MarketDataSource, NameRegistry, PriceCache, TickerTracker, normalize_ticker
from .errors import (
    AlreadyInWatchlistError,
    InvalidTickerError,
    NotInWatchlistError,
    UnknownTickerError,
)

logger = logging.getLogger(__name__)

NameResolver = Callable[[str], Awaitable[str | None]]


def _num(x: float) -> int | float:
    """KRW amounts: int when integral (the common case), else 2dp."""
    x = float(x)
    return int(round(x)) if abs(x - round(x)) < 1e-6 else round(x, 2)


class PortfolioService:
    def __init__(
        self,
        cache: PriceCache,
        names: NameRegistry,
        tracker: TickerTracker,
        source: MarketDataSource,
        db_path: str | PathLike | None = None,
    ) -> None:
        self.cache = cache
        self.names = names
        self.tracker = tracker
        self.source = source
        self.db_path = db_path
        self._name_resolvers: list[NameResolver] = []
        self._snapshot_lock = asyncio.Lock()

    # ------------------------------------------------------------------ helpers
    def name(self, ticker: str) -> str:
        return self.names.get(ticker)

    def price(self, ticker: str) -> int | None:
        return self.cache.price(ticker)

    def add_name_resolver(self, fn: NameResolver) -> None:
        self._name_resolvers.append(fn)

    async def _db(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, path=self.db_path, **kwargs)

    async def tracked_wanted(self) -> tuple[list[str], list[str]]:
        watch = await self._db(db.watchlist_tickers)
        held = await self._db(db.position_tickers)
        return watch, held

    async def resync(self) -> set[str]:
        """Make the tracked set watchlist ∪ positions. Returns unpriceable tickers."""
        watch, held = await self.tracked_wanted()
        return await self.tracker.sync(watch, held)

    async def load_names(self) -> None:
        """Seed the NameRegistry from the watchlist table."""
        for row in await self._db(db.list_watchlist):
            self.names.set(row["ticker"], row.get("name"))

    async def _resolve_name(self, ticker: str) -> str:
        if self.names.known(ticker):
            return self.names.get(ticker)
        for resolver in self._name_resolvers:
            try:
                name = await resolver(ticker)
            except Exception:  # resolvers are best-effort
                logger.warning("Name resolver failed for %s", ticker, exc_info=True)
                continue
            if name and name.strip():
                return name.strip()
        return ticker

    # -------------------------------------------------------------------- trade
    async def trade(self, ticker: str, side: str, quantity: int) -> dict:
        try:
            t = normalize_ticker(ticker)
        except ValueError:
            return {"success": False, "error": "Invalid ticker"}
        side = side.strip().lower() if isinstance(side, str) else side
        if side not in ("buy", "sell"):
            return {"success": False, "error": "Invalid side"}
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            return {"success": False, "error": "Invalid quantity"}

        ensured = False
        price = self.cache.price(t)
        if price is None:
            ensured = True
            await self.tracker.ensure(t)
            price = self.cache.price(t)
        if price is None:
            await self.resync()
            return {"success": False, "error": "No price available"}

        result = await self._db(db.execute_trade, t, side, quantity, price, self.cache.price)
        if result.opened or result.closed or ensured:
            await self.resync()
        if not result.success:
            return {"success": False, "error": result.error or "Trade failed"}
        return {
            "success": True,
            "ticker": t,
            "side": side,
            "quantity": quantity,
            "price": price,
            "cash_balance": _num(result.cash_balance),
        }

    # ---------------------------------------------------------------- watchlist
    async def watchlist(self) -> list[dict]:
        out = []
        for row in await self._db(db.list_watchlist):
            t = row["ticker"]
            q = self.cache.get(t)
            out.append(
                {
                    "ticker": t,
                    "name": row.get("name") or self.names.get(t),
                    "price": q.price if q else None,
                    "prev_price": q.prev_price if q else None,
                    "session_open": q.session_open if q else None,
                    "session_change_pct": q.session_change_pct if q else None,
                    "direction": q.direction if q else "flat",
                }
            )
        return out

    async def add_watchlist(self, ticker: str, name: str | None = None) -> dict:
        try:
            t = normalize_ticker(ticker)
        except ValueError as e:
            raise InvalidTickerError("Invalid ticker") from e
        if t in await self._db(db.watchlist_tickers):
            raise AlreadyInWatchlistError(f"{t} is already in the watchlist")
        if not await self.tracker.ensure(t):
            await self.resync()
            raise UnknownTickerError(f"Unknown ticker {t}")

        final_name = name.strip() if name and name.strip() else await self._resolve_name(t)
        added = await self._db(db.add_watchlist, t, final_name)
        if not added:  # lost a race with a concurrent add
            raise AlreadyInWatchlistError(f"{t} is already in the watchlist")
        if final_name != t:
            self.names.set(t, final_name)
        await self.resync()
        return {"ticker": t, "name": final_name, "price": self.cache.price(t)}

    async def remove_watchlist(self, ticker: str) -> dict:
        try:
            t = normalize_ticker(ticker)
        except ValueError as e:
            raise InvalidTickerError("Invalid ticker") from e
        if not await self._db(db.remove_watchlist, t):
            raise NotInWatchlistError(f"{t} is not in the watchlist")
        await self.resync()
        return {"ticker": t, "removed": True}

    # ---------------------------------------------------------------- portfolio
    def _value_positions(self, positions: list[dict]) -> list[dict]:
        out = []
        for p in positions:
            t = p["ticker"]
            qty = int(p["quantity"])
            avg = float(p["avg_cost"])
            cached = self.cache.price(t)
            current = cached if cached is not None else avg
            market_value = qty * current
            pnl = (current - avg) * qty
            pnl_pct = round((current - avg) / avg * 100, 2) if avg else 0.0
            out.append(
                {
                    "ticker": t,
                    "name": self.names.get(t),
                    "quantity": qty,
                    "avg_cost": _num(avg),
                    "current_price": _num(current),
                    "market_value": _num(market_value),
                    "unrealized_pnl": _num(pnl),
                    "pnl_pct": pnl_pct,
                }
            )
        return out

    async def portfolio(self) -> dict:
        cash = await self._db(db.get_cash)
        positions = self._value_positions(await self._db(db.list_positions))
        total = cash + sum(p["market_value"] for p in positions)
        return {"cash_balance": _num(cash), "total_value": _num(total), "positions": positions}

    async def total_value(self) -> float:
        cash = await self._db(db.get_cash)
        positions = self._value_positions(await self._db(db.list_positions))
        return cash + sum(p["market_value"] for p in positions)

    async def history(self) -> list[dict]:
        rows = await self._db(db.list_snapshots)
        return [
            {"total_value": _num(r["total_value"]), "recorded_at": r["recorded_at"]} for r in rows
        ]

    async def chat_history(self, limit: int = 50) -> list[dict]:
        """Stored chat, oldest first: ``[{id, role, content, trades, watchlist_changes, created_at}]``."""
        rows = await self._db(db.recent_chat_messages, limit)
        out = []
        for r in rows:
            actions = r.get("actions") or {}
            out.append(
                {
                    "id": r["id"],
                    "role": r["role"],
                    "content": r["content"],
                    "trades": actions.get("trades") or [],
                    "watchlist_changes": actions.get("watchlist_changes") or [],
                    "created_at": r["created_at"],
                }
            )
        return out

    # ---------------------------------------------------------------- snapshots
    async def snapshot_if_due(self, min_age: float = 60.0) -> bool:
        """Record a snapshot unless the latest one is younger than ``min_age`` s."""
        async with self._snapshot_lock:  # check-then-write must not interleave
            last = await self._db(db.last_snapshot_time) if min_age > 0 else None
            if last is not None and (datetime.now(UTC) - last).total_seconds() < min_age:
                return False
            await self._db(db.record_snapshot, await self.total_value())
            return True

    async def run_snapshots(self, interval: float = 60.0) -> None:
        """Background loop: snapshot every ``interval`` s (skipped if one is recent).

        Sleeps first — the lifespan takes the startup snapshot synchronously so
        it cannot race the first requests.
        """
        delay = interval
        while True:
            await asyncio.sleep(delay)
            try:
                await self.snapshot_if_due(interval)
                last = await self._db(db.last_snapshot_time)
                age = (datetime.now(UTC) - last).total_seconds() if last else interval
                delay = max(1.0, interval - age)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Snapshot task error")
                delay = interval
