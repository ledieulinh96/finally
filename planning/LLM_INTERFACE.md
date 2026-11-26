# LLM Interface (Seam 3: `app/llm` → backend)

Owner: `llm`. Consumer: `backend` (mounts `POST /api/chat`).

## Entry point

```python
from app.llm import handle_chat

result: dict = await handle_chat(message, services)
```

- `message: str`: the user's text. The **route** validates it (non-empty, at most 2,000 chars, 422 otherwise) with its own Pydantic body model. `handle_chat` trims it and does not re-validate the length.
- `services`: the `PortfolioService` (`app.state.services`). `handle_chat` uses only:
  - `portfolio()` and `watchlist()`. These can be sync or async; both are accepted.
  - `await trade(ticker, side, quantity) -> dict` (PLAN §8 trade shape; `{"success": False, "error": ...}` on failure).
  - `await add_watchlist(ticker, name=None) -> dict` and `await remove_watchlist(ticker) -> dict`. They may raise. Any exception is caught and recorded as `{"success": False, "error": <exc.detail or str(exc)>}`.
- Optional keyword args (for tests): `store=` (an object with `add_chat_message(role, content, actions)` and `recent_chat_messages(limit)`; the default is `app.db`) and `llm=` (a callable `list[dict] -> str` that returns raw JSON; the default is the LiteLLM call).

**Returns** the PLAN §8 `POST /api/chat` shape. It never raises for LLM, parse or network failures:

```json
{
  "message": "Bought 10 shares of 005930 Samsung Electronics at ₩75,400.",
  "trades": [{"ticker": "005930", "side": "buy", "quantity": 10, "price": 75400, "success": true}],
  "watchlist_changes": [{"ticker": "035420", "action": "add", "name": "NAVER", "success": true}]
}
```

Failed items carry `"success": false, "error": "..."`. **Chat-only idempotency:** if chat adds a ticker that is already watched (`AlreadyInWatchlistError`) or removes one that isn't watched (`NotInWatchlistError`), the result is `{"success": true}` with no error. REST keeps 409/404. a failed trade has `"price": null`. These same `trades` and `watchlist_changes` lists are stored as the assistant row's `actions` JSON.

## Flow

1. Load context: `services.portfolio()` and `services.watchlist()`.
2. Load history: `store.recent_chat_messages(20)`, oldest to newest. The new message is appended after it, so the prompt holds up to 21 messages.
3. Optional OpenDART enrichment. It runs only if `OPENDART_API_KEY` is set and a fundamentals keyword matches. It covers tickers that are mentioned or held, keeps a 24 h in-memory cache, and swallows all errors.
4. Call the LLM. If `LLM_MOCK=true`, it uses the PLAN §9 fixtures instead. Otherwise it calls LiteLLM `openrouter/openai/gpt-oss-120b` with Cerebras and `response_format=ChatLLMResponse`, run in `asyncio.to_thread`.
5. Parse with Pydantic. On failure, return a friendly message and no actions.
6. Execute trades, then watchlist changes, sequentially through `services`.
7. Persist the user message and then the assistant message (with `actions`).
8. Return.

## Env
`OPENROUTER_API_KEY`, `LLM_MOCK`, `OPENDART_API_KEY` (optional). These are read at call time, so `.env` loading is the backend's job (`load_dotenv` in `main`).

## Dependencies
The dependencies are `litellm` and `pydantic`. The OpenDART client uses only the stdlib (`urllib`, `zipfile`, `xml`), so there is no `httpx` runtime dependency.

## OpenDART name resolver (optional)
`from app.llm.dart import resolve_name`: an `async (ticker) -> str | None` function for `PortfolioService.add_name_resolver`. It returns a display-friendly `corp_name_eng` ("SAMSUNG ELECTRONICS CO,.LTD" → "Samsung Electronics"), or None when there is no key or on any failure.

`stock_code → corp_code` comes from `corpCode.xml`, which is cached on disk at `<dir of DB_PATH>/dart_corp_codes.json` and refreshed after 30 days.

## Modules
- `schema.py`: Pydantic models and a lenient parser. Malformed items become failed actions, while well-formed items still execute.
- `prompt.py`: the system prompt and the context text.
- `client.py`: LiteLLM and the mock fixtures.
- `dart.py`: OpenDART.
- `chat.py`: `handle_chat`.
