"""LLM backends: LiteLLM → OpenRouter (Cerebras) and the deterministic mock."""

from __future__ import annotations

import json
import os

from .schema import ChatLLMResponse

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_S = 45

MOCK_DEFAULT = {
    "message": (
        "Your portfolio looks well-diversified across Korean tech and industrial sectors. "
        "Samsung Electronics (005930) is your largest position. "
        "Consider adding exposure to financials for balance."
    ),
    "trades": [],
    "watchlist_changes": [],
}

MOCK_BUY = {
    "message": (
        "Buying 1 share of 005930 Samsung Electronics and adding 035420 NAVER to your watchlist."
    ),
    "trades": [{"ticker": "005930", "side": "buy", "quantity": 1}],
    "watchlist_changes": [{"ticker": "035420", "action": "add"}],
}


def is_mock() -> bool:
    return os.environ.get("LLM_MOCK", "").strip().lower() in ("1", "true", "yes")


def mock_completion(user_message: str) -> str:
    """PLAN §9 fixtures: 'buy' anywhere (case-insensitive) → trade fixture."""
    fixture = MOCK_BUY if "buy" in user_message.lower() else MOCK_DEFAULT
    return json.dumps(fixture)


def litellm_completion(messages: list[dict]) -> str:
    """Blocking structured-output call. Run it via ``asyncio.to_thread``."""
    from litellm import completion  # imported lazily: slow import, unused in mock mode

    response = completion(
        model=MODEL,
        messages=messages,
        response_format=ChatLLMResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=TIMEOUT_S,
    )
    return response.choices[0].message.content or ""
