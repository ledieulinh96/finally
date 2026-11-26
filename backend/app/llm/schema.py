"""Structured-output schema for the chat LLM and a lenient parser."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(description="6-character KRX code, e.g. '005930'")
    side: Literal["buy", "sell"]
    quantity: int = Field(description="Whole number of shares, > 0")


class WatchlistChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(description="6-character KRX code, e.g. '035420'")
    action: Literal["add", "remove"]
    name: str | None = Field(default=None, description="Optional English company name")


class ChatLLMResponse(BaseModel):
    """The JSON object the LLM must return (PLAN §9)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="Conversational response shown to the user")
    trades: list[TradeRequest] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)


class ParseError(ValueError):
    """The LLM output could not be interpreted at all."""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost {...} block (models sometimes add prose).
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ParseError("no JSON object in LLM output") from None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON: {exc}") from None


def parse_llm_output(raw: str | None) -> tuple[ChatLLMResponse, list[dict]]:
    """Parse raw LLM output.

    Returns the parsed response (with only the well-formed actions) plus a list of
    rejected action items, already annotated as failures, for items that were
    malformed. Raises ParseError if there is no usable ``message``.
    """
    if not raw or not raw.strip():
        raise ParseError("empty LLM output")
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ParseError("LLM output is not a JSON object")
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ParseError("missing 'message'")

    trades: list[TradeRequest] = []
    changes: list[WatchlistChange] = []
    rejected: list[dict] = []

    for item in data.get("trades") or []:
        try:
            trades.append(TradeRequest.model_validate(item))
        except Exception:
            rejected.append(_rejected_trade(item))
    for item in data.get("watchlist_changes") or []:
        try:
            changes.append(WatchlistChange.model_validate(item))
        except Exception:
            rejected.append(_rejected_change(item))

    return ChatLLMResponse(
        message=message.strip(), trades=trades, watchlist_changes=changes
    ), rejected


def _rejected_trade(item: Any) -> dict:
    d = item if isinstance(item, dict) else {}
    return {
        "kind": "trade",
        "ticker": str(d.get("ticker", "")),
        "side": str(d.get("side", "")),
        "quantity": d.get("quantity"),
        "price": None,
        "success": False,
        "error": "Invalid trade request",
    }


def _rejected_change(item: Any) -> dict:
    d = item if isinstance(item, dict) else {}
    return {
        "kind": "watchlist",
        "ticker": str(d.get("ticker", "")),
        "action": str(d.get("action", "")),
        "success": False,
        "error": "Invalid watchlist change",
    }
