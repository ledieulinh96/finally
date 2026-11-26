"""LLM chat integration (PLAN §9). Entry point: ``await handle_chat(message, services)``."""

from .chat import FALLBACK_MESSAGE, handle_chat
from .client import MOCK_BUY, MOCK_DEFAULT, MODEL
from .schema import ChatLLMResponse, TradeRequest, WatchlistChange, parse_llm_output

__all__ = [
    "FALLBACK_MESSAGE",
    "MOCK_BUY",
    "MOCK_DEFAULT",
    "MODEL",
    "ChatLLMResponse",
    "TradeRequest",
    "WatchlistChange",
    "handle_chat",
    "parse_llm_output",
]
