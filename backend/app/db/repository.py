"""Repositories: watchlist, portfolio state, positions, trades, snapshots, chat."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .connection import PORTFOLIO_ID, DBPath, connection, new_id, now_iso, parse_iso

# ---------------------------------------------------------------- watchlist


def list_watchlist(*, path: DBPath | None = None) -> list[dict[str, Any]]:
    with connection(path) as conn:
        rows = conn.execute(
            "SELECT ticker, name, added_at FROM watchlist ORDER BY added_at, rowid"
        ).fetchall()
    return [dict(r) for r in rows]


def watchlist_tickers(*, path: DBPath | None = None) -> list[str]:
    return [r["ticker"] for r in list_watchlist(path=path)]


def add_watchlist(ticker: str, name: str, *, path: DBPath | None = None) -> bool:
    """Add a ticker. Returns False (no change) if it is already present."""
    with connection(path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, name, added_at) VALUES (?, ?, ?)",
            (ticker, name, now_iso()),
        )
        return cur.rowcount == 1


def remove_watchlist(ticker: str, *, path: DBPath | None = None) -> bool:
    """Remove a ticker. Returns False if it was not present."""
    with connection(path) as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker,))
        return cur.rowcount == 1


# ---------------------------------------------------------------- portfolio


def read_cash(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT cash_balance FROM portfolio_state WHERE id = ?", (PORTFOLIO_ID,)
    ).fetchone()
    return float(row["cash_balance"])


def get_cash(*, path: DBPath | None = None) -> float:
    with connection(path) as conn:
        return read_cash(conn)


def position_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "ticker": row["ticker"],
        "quantity": int(row["quantity"]),
        "avg_cost": float(row["avg_cost"]),
        "updated_at": row["updated_at"],
    }


def list_positions(*, path: DBPath | None = None) -> list[dict[str, Any]]:
    with connection(path) as conn:
        rows = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions ORDER BY ticker"
        ).fetchall()
    return [position_row(r) for r in rows]


def get_position(ticker: str, *, path: DBPath | None = None) -> dict[str, Any] | None:
    with connection(path) as conn:
        row = conn.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions WHERE ticker = ?",
            (ticker,),
        ).fetchone()
    return position_row(row) if row else None


def position_tickers(*, path: DBPath | None = None) -> list[str]:
    return [p["ticker"] for p in list_positions(path=path)]


def list_trades(limit: int = 50, *, path: DBPath | None = None) -> list[dict[str, Any]]:
    """Most recent trades, newest first."""
    with connection(path) as conn:
        rows = conn.execute(
            "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
            "ORDER BY executed_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "ticker": r["ticker"],
            "side": r["side"],
            "quantity": int(r["quantity"]),
            "price": float(r["price"]),
            "executed_at": r["executed_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------- snapshots


def insert_snapshot(conn: sqlite3.Connection, total_value: float) -> None:
    conn.execute(
        "INSERT INTO portfolio_snapshots (id, total_value, recorded_at) VALUES (?, ?, ?)",
        (new_id(), float(total_value), now_iso()),
    )


def record_snapshot(total_value: float, *, path: DBPath | None = None) -> None:
    with connection(path) as conn:
        insert_snapshot(conn, total_value)


def last_snapshot_time(*, path: DBPath | None = None) -> datetime | None:
    with connection(path) as conn:
        row = conn.execute("SELECT MAX(recorded_at) AS t FROM portfolio_snapshots").fetchone()
    return parse_iso(row["t"]) if row["t"] else None


def list_snapshots(limit: int | None = None, *, path: DBPath | None = None) -> list[dict[str, Any]]:
    """Snapshots oldest → newest; with ``limit``, only the most recent ``limit``."""
    with connection(path) as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT total_value, recorded_at FROM portfolio_snapshots "
                "ORDER BY recorded_at, rowid"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT total_value, recorded_at FROM ("
                "  SELECT total_value, recorded_at, rowid AS rid FROM portfolio_snapshots"
                "  ORDER BY recorded_at DESC, rowid DESC LIMIT ?"
                ") ORDER BY recorded_at, rid",
                (limit,),
            ).fetchall()
    return [{"total_value": float(r["total_value"]), "recorded_at": r["recorded_at"]} for r in rows]


# ---------------------------------------------------------------- chat


def add_chat_message(
    role: str,
    content: str,
    actions: dict[str, Any] | None = None,
    *,
    path: DBPath | None = None,
) -> str:
    """Store a chat message; returns its id. ``actions`` is stored as JSON text."""
    msg_id = new_id()
    encoded = json.dumps(actions, ensure_ascii=False) if actions is not None else None
    with connection(path) as conn:
        conn.execute(
            "INSERT INTO chat_messages (id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, role, content, encoded, now_iso()),
        )
    return msg_id


def recent_chat_messages(limit: int = 20, *, path: DBPath | None = None) -> list[dict[str, Any]]:
    """The most recent ``limit`` messages, oldest → newest."""
    with connection(path) as conn:
        rows = conn.execute(
            "SELECT id, role, content, actions, created_at FROM ("
            "  SELECT *, rowid AS rid FROM chat_messages"
            "  ORDER BY created_at DESC, rowid DESC LIMIT ?"
            ") ORDER BY created_at, rid",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "actions": json.loads(r["actions"]) if r["actions"] else None,
            "created_at": r["created_at"],
        }
        for r in rows
    ]
