"""SQLite persistence layer (sync ``sqlite3``). See ``planning/DB_INTERFACE.md``.

Each function opens its own short-lived connection, so all are thread-safe and
can be called directly or via ``asyncio.to_thread``. Every function accepts an
optional keyword-only ``path`` (default: env ``DB_PATH`` or ``<repo>/db/finally.db``).
"""

from .connection import (
    DEFAULT_CASH,
    DEFAULT_DB_PATH,
    connect,
    get_db_path,
    init_db,
)
from .repository import (
    add_chat_message,
    add_watchlist,
    get_cash,
    get_position,
    last_snapshot_time,
    list_positions,
    list_snapshots,
    list_trades,
    list_watchlist,
    position_tickers,
    recent_chat_messages,
    record_snapshot,
    remove_watchlist,
    watchlist_tickers,
)
from .trading import TradeResult, execute_trade

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_DB_PATH",
    "TradeResult",
    "add_chat_message",
    "add_watchlist",
    "connect",
    "execute_trade",
    "get_cash",
    "get_db_path",
    "get_position",
    "init_db",
    "last_snapshot_time",
    "list_positions",
    "list_snapshots",
    "list_trades",
    "list_watchlist",
    "position_tickers",
    "recent_chat_messages",
    "record_snapshot",
    "remove_watchlist",
    "watchlist_tickers",
]
