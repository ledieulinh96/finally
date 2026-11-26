"""SQLite path resolution, connections and lazy, idempotent initialization."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.market.seed_data import DEFAULT_TICKERS, SEED_PARAMS

DBPath = str | os.PathLike[str]

_BACKEND_DIR = Path(__file__).resolve().parents[2]
SCHEMA_PATH = _BACKEND_DIR / "schema" / "schema.sql"
DEFAULT_DB_PATH = _BACKEND_DIR.parent / "db" / "finally.db"

DEFAULT_CASH = 10_000_000.0
PORTFOLIO_ID = "default"

_init_lock = threading.Lock()
_initialized: set[Path] = set()


def now_iso() -> str:
    """Current UTC time as ISO-8601 with millisecond precision and a ``Z`` suffix."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def new_id() -> str:
    return str(uuid.uuid4())


def get_db_path() -> Path:
    """``DB_PATH`` env var (read at call time), else ``<repo>/db/finally.db``."""
    env = os.environ.get("DB_PATH")
    return Path(env) if env else DEFAULT_DB_PATH


def _resolve(path: DBPath | None) -> Path:
    return Path(path) if path is not None else get_db_path()


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: DBPath | None = None) -> Path:
    """Create the schema and seed default data. Idempotent; returns the path used."""
    db_path = _resolve(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        ts = now_iso()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO portfolio_state (id, cash_balance, updated_at) VALUES (?, ?, ?)",
            (PORTFOLIO_ID, DEFAULT_CASH, ts),
        )
        # Seed the default watchlist only once per database (tracked via
        # user_version), so tickers the user removed do not reappear on restart.
        if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist (ticker, name, added_at) VALUES (?, ?, ?)",
                [(t, SEED_PARAMS[t].name, ts) for t in DEFAULT_TICKERS],
            )
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
    finally:
        conn.close()
    with _init_lock:
        _initialized.add(db_path.resolve())
    return db_path


def connect(path: DBPath | None = None) -> sqlite3.Connection:
    """Open a configured connection, lazily initializing the DB on first use.

    Autocommit mode (``isolation_level=None``); use ``BEGIN`` explicitly for
    multi-statement transactions. The caller must close the connection.
    """
    db_path = _resolve(path)
    key = db_path.resolve()
    if key not in _initialized or not db_path.exists():
        init_db(db_path)
    return _open(db_path)


@contextmanager
def connection(path: DBPath | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(path: DBPath | None = None) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT`` (``ROLLBACK`` on exception)."""
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
