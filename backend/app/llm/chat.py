"""Chat orchestration: context → LLM → parse → auto-execute → persist (PLAN §9)."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

from ..market import normalize_ticker
from ..services.errors import AlreadyInWatchlistError, NotInWatchlistError
from . import client, dart
from .prompt import SYSTEM_PROMPT, build_context
from .schema import ChatLLMResponse, ParseError, parse_llm_output

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
FALLBACK_MESSAGE = (
    "Sorry, I couldn't process that request right now. No trades or watchlist changes "
    "were made. Please try again."
)

LLMCallable = Callable[[list[dict]], str]


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, IndexError, TypeError):
        return getattr(obj, key, default)


def _error_text(exc: BaseException) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    return str(exc) or exc.__class__.__name__


def _default_store() -> Any:
    from .. import db  # lazy: keeps app.llm importable/testable without the DB module

    return db


def build_messages(history: list[Any], context: str, user_message: str) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "system", "content": context})
    for row in history[-HISTORY_LIMIT:]:
        role = _field(row, "role")
        content = _field(row, "content")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


async def _execute_trade(services: Any, ticker: str, side: str, quantity: int) -> dict:
    result: dict = {"ticker": ticker, "side": side, "quantity": quantity, "price": None}
    try:
        ticker = normalize_ticker(ticker)
        result["ticker"] = ticker
    except ValueError:
        return {**result, "success": False, "error": "Invalid ticker"}
    if quantity <= 0:
        return {**result, "success": False, "error": "Quantity must be a positive integer"}
    try:
        res = await services.trade(ticker, side, quantity)
    except Exception as exc:
        logger.info("chat trade %s %s %s failed", side, quantity, ticker, exc_info=True)
        return {**result, "success": False, "error": _error_text(exc)}
    res = res or {}
    if res.get("success"):
        return {**result, "price": res.get("price"), "success": True}
    return {**result, "success": False, "error": res.get("error") or "Trade failed"}


async def _execute_change(
    services: Any, ticker: str, action: str, name: str | None, names: dict[str, str]
) -> dict:
    result: dict = {"ticker": ticker, "action": action}
    try:
        ticker = normalize_ticker(ticker)
        result["ticker"] = ticker
    except ValueError:
        return {**result, "success": False, "error": "Invalid ticker"}
    try:
        if action == "add":
            res = await services.add_watchlist(ticker, name=name)
        else:
            res = await services.remove_watchlist(ticker)
    except (AlreadyInWatchlistError, NotInWatchlistError):
        # Chat-only idempotency (team-lead decision): the desired state already holds.
        res = {}
    except Exception as exc:
        logger.info("chat watchlist %s %s failed", action, ticker, exc_info=True)
        return {**result, "success": False, "error": _error_text(exc)}
    res = res if isinstance(res, dict) else {}
    if res.get("success") is False:
        return {**result, "success": False, "error": res.get("error") or "Watchlist change failed"}
    resolved = res.get("name") or name or names.get(ticker)
    if resolved:
        result["name"] = resolved
    return {**result, "success": True}


async def handle_chat(
    message: str,
    services: Any,
    *,
    store: Any = None,
    llm: LLMCallable | None = None,
) -> dict:
    """Process one chat turn. Returns ``{"message", "trades", "watchlist_changes"}``."""
    message = (message or "").strip()
    store = store if store is not None else _default_store()

    # 1. Context (failures degrade to an empty context rather than a 500).
    try:
        portfolio = await _maybe_await(services.portfolio()) or {}
    except Exception:
        logger.warning("chat: could not load portfolio", exc_info=True)
        portfolio = {}
    try:
        watchlist = await _maybe_await(services.watchlist()) or []
    except Exception:
        logger.warning("chat: could not load watchlist", exc_info=True)
        watchlist = []
    positions = portfolio.get("positions", []) or []
    names: dict[str, str] = {}
    for item in [*watchlist, *positions]:
        t, n = _field(item, "ticker"), _field(item, "name")
        if t and n:
            names[t] = n
    context = build_context(portfolio, watchlist)

    # 2. History (last 20 stored messages, oldest → newest).
    try:
        history = list(store.recent_chat_messages(HISTORY_LIMIT) or [])
    except Exception:
        logger.warning("chat: could not load history", exc_info=True)
        history = []

    # 3. Optional OpenDART fundamentals.
    if not client.is_mock():
        extra = await dart.enrichment(message, names, [_field(p, "ticker") for p in positions])
        if extra:
            context = context + "\n\n" + extra

    # 4-5. LLM call + parse.
    rejected: list[dict] = []
    try:
        if client.is_mock():
            raw = client.mock_completion(message)
        else:
            call = llm or client.litellm_completion
            raw = await asyncio.to_thread(call, build_messages(history, context, message))
        parsed, rejected = parse_llm_output(raw)
    except ParseError:
        logger.warning("chat: unparseable LLM output", exc_info=True)
        parsed = ChatLLMResponse(message=FALLBACK_MESSAGE)
    except Exception:
        logger.exception("chat: LLM call failed")
        parsed = ChatLLMResponse(message=FALLBACK_MESSAGE)

    # 6. Auto-execute (trades first, then watchlist changes), sequentially.
    trades: list[dict] = []
    changes: list[dict] = []
    for t in parsed.trades:
        trades.append(await _execute_trade(services, t.ticker, t.side, t.quantity))
    for c in parsed.watchlist_changes:
        changes.append(await _execute_change(services, c.ticker, c.action, c.name, names))
    for r in rejected:
        kind = r.pop("kind")
        (trades if kind == "trade" else changes).append(r)

    actions = {"trades": trades, "watchlist_changes": changes}

    # 7. Persist.
    try:
        store.add_chat_message("user", message, None)
        store.add_chat_message("assistant", parsed.message, actions)
    except Exception:
        logger.exception("chat: could not persist messages")

    return {"message": parsed.message, **actions}
