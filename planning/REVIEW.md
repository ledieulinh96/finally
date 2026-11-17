# FinAlly — Plan Review

**Reviewer:** Claude Code (review agent)
**Date:** 2026-11-13
**Document reviewed:** `planning/PLAN.md`

---

## 1. Architecture Decisions

### Sound choices
The single-container, single-port architecture (Section 3) is genuinely the right call for a demo/course project. SSE over WebSockets is appropriate — there is no need for client→server push other than the existing REST API calls. Static Next.js export removes an entire category of CORS/proxy misconfiguration bugs. SQLite is well-suited to single-user, low-write-volume workloads.

### Hidden complexity: SQLite + SSE concurrency
SSE keeps many long-lived connections open simultaneously. Each SSE push loop must read from the in-memory price cache (Section 6) — not SQLite — which is correct. However, every trade and every `/api/portfolio/history` call writes to SQLite. With multiple browser tabs open (realistic during demos), WAL mode must be explicitly enabled, otherwise writers block readers for the full transaction duration. The plan does not mention `PRAGMA journal_mode=WAL`. Agents will likely omit this, causing sporadic 500 errors under even light concurrent access.

### Hidden complexity: yfinance in a container
yfinance makes outbound HTTPS requests to Yahoo Finance at poll time. Inside a Docker container with no network, `USE_YFINANCE=true` will hang or raise connection errors. The plan does not mention that the container must be run without `--network none`, nor does the health check (`GET /api/health`) indicate whether the yfinance poller has successfully fetched at least one round of prices. If the first poll fails silently (bad network, Yahoo rate-limit), the price cache starts empty and SSE pushes nothing. The fallback behavior when the cache is empty on first SSE connection is unspecified.

### In-process background tasks and uvicorn workers
Section 11 specifies `uvicorn` with no worker count. If agents add `--workers N` (a natural instinct for "production"), the in-memory price cache and GBM simulator state are not shared across worker processes, so each worker has independent, diverging prices. The plan should explicitly state `--workers 1` or note that multi-worker deployments require an external cache (Redis). As written, an agent could easily introduce this bug.

### No `docker-compose.yml` in core build
Section 4 explicitly omits `docker-compose.yml`. The test infrastructure in Section 12 requires `docker-compose.test.yml`. An agent writing tests will have to introduce Compose for testing but not for running, which is a minor inconsistency but should be called out so the test agent does not accidentally create a top-level `docker-compose.yml`.

---

## 2. Gaps and Ambiguities

### SSE push cadence vs. yfinance poll cadence
Section 6 says SSE pushes at ~500ms cadence. yfinance polls every 15 seconds. When `USE_YFINANCE=true`, the SSE loop will push the same stale price 30 times between polls, generating ~30 redundant `direction: "flat"` events per ticker per poll cycle. The plan does not say whether to suppress no-change events or push them anyway. Frontend sparklines will appear to have data points that are identical, which may look odd. A simple "only push on cache change, or push heartbeat every N seconds" policy should be specified.

### Company name on `POST /api/watchlist`
Section 8 shows the request body as `{ticker, name}`. Section 7 (watchlist schema) stores `name` as a column. But Section 6 says: "if `OPENDART_API_KEY` is absent, the name falls back to the yfinance `shortName` field." This implies the backend can resolve the name itself. So is `name` required in the POST body or optional? If the user types a ticker into the trade bar and presses "Add," there is no UX moment to enter a name. The frontend cannot know the name before the backend resolves it. This should be: `name` is optional in the request; backend resolves it via yfinance/OpenDART; falls back to ticker code if resolution fails.

### `GET /api/portfolio/history` side-effect
Section 7 states: "`GET /api/portfolio/history` also appends a snapshot at call time." This means a GET endpoint has a write side-effect — a violation of REST semantics and a hazard if the frontend polls this endpoint (every snapshot recorded as a fresh data point, inflating the chart). The plan should either use a background timer at a low cadence (e.g., every 60 seconds) or remove the GET side-effect and accept that the chart only updates on trades.

### Positions table in `GET /api/portfolio` — no `name` field in schema
Section 8 shows `name: "Samsung Electronics"` in the portfolio response. The `positions` table (Section 7) has no `name` column. The backend must JOIN against `watchlist` for the name. But a position can exist for a ticker that has since been removed from the watchlist. The plan does not say what to show for `name` in that case. Agents will either crash with a NULL or omit the field.

### Trade bar ticker validation
Section 10 describes a "ticker field" in the trade bar but does not specify whether the frontend validates that the ticker exists in the watchlist or price cache before submitting. A user might type `AAPL` (not a KRX code) and submit. The backend should return a clear error. Section 8 shows `{ "success": false, "error": "Insufficient cash" }` as the only error example — no example for "ticker not found" or "ticker not in watchlist."

### KRW integer enforcement
Section 7 defines prices as "KRW integers" and Section 10 states "Prices are integers — no decimal display needed." But the `avg_cost` and `price` columns are `REAL`. The GBM simulator (Section 6) says it generates "KRW as whole integers." There is no enforcement at the database or API layer. If a future agent implements GBM naively in Python, floating-point rounding will produce fractional KRW values (e.g., 75001.9999). The plan should specify where rounding to `int` is applied.

### Session open vs. market open
`session_open` is defined as "price at server startup" (Section 6). If the server restarts mid-day, `session_open` resets. This is a known limitation for the simulator but is especially problematic with yfinance: the yfinance `previousClose` or `open` field is the actual market open, not the server start time. Using server-start time as the basis for `session_change_pct` will show misleading percentages when yfinance is active. The plan should either use yfinance's actual `open` price or explicitly document this as a known inaccuracy.

---

## 3. Consistency Issues

### Section 3 diagram vs. Section 4 directory structure
Section 3 diagram shows `Background task: market data sim / yfinance`. Section 4 shows `backend/db/` in the original CLAUDE.md but `backend/schema/` in PLAN.md. The CLAUDE.md system context (which overrides PLAN.md from an agent perspective) says `backend/db/`. Agents will implement one or the other inconsistently. PLAN.md must be authoritative and match CLAUDE.md. **This is a concrete conflict: `backend/db/` vs `backend/schema/`.**

### `docker-compose.yml` existence
Section 4 and the note below the directory tree say "docker-compose.yml is not part of the core build — omit it." The CLAUDE.md system context (checked into the codebase) includes `docker-compose.yml` in the directory structure listing in its embedded PLAN.md excerpt. If the CLAUDE.md embedded copy differs from the actual PLAN.md, agents reading CLAUDE.md will create a `docker-compose.yml` anyway.

### Fractional shares: Section 7 vs. Section 13
Section 7 (positions schema) says `quantity REAL (whole shares; fractional shares not supported for KRX)` and states the row is deleted when quantity reaches 0. Section 13 (Q2) asks whether fractional shares should be supported as a "demo flexibility." This contradicts Section 7's clear statement. The schema decision should be settled before implementation — if the schema says `REAL` but the validation layer enforces integers, the type mismatch is confusing.

### SSE event shape vs. `GET /api/watchlist` response shape
Section 6 SSE payload includes `session_open`. Section 8 `GET /api/watchlist` response does not include `session_open`. Agents may or may not add `session_open` to the watchlist response. If the frontend needs it to compute the display-level change percentage from a REST call (e.g., on initial page load before SSE connects), it will be absent. The two shapes should be aligned or the discrepancy documented.

### `POST /api/watchlist` request body
Section 6 says the backend resolves names via yfinance/OpenDART. Section 8 specifies the request body as `{ticker, name}`, implying `name` is a required client-supplied field. These two positions conflict. See also Gap section above.

---

## 4. Schema and Data Model

### Missing indexes
No indexes are defined anywhere in the plan. At minimum these are needed for correctness and future-proofing:
- `trades(ticker)` — trade history queries by ticker
- `trades(executed_at)` — time-ordered history queries
- `portfolio_snapshots(recorded_at)` — chart query is always time-ordered
- `chat_messages(created_at)` — history loaded as "last 20 by time"

SQLite will do full table scans without these. For a demo with bounded data this is acceptable, but the `chat_messages` load ("last 20 messages") requires `ORDER BY created_at DESC LIMIT 20` which without an index on `created_at` is a full scan. Worth noting for agents writing the query.

### `portfolio_state` table design
Section 7 defines `portfolio_state` as a single-row table with only `cash_balance REAL`. There is no primary key, no `updated_at`, no `id`. SQLite requires at least an implicit rowid, but agents writing the schema SQL may omit a PK and get a warning. Recommend: `id TEXT PRIMARY KEY DEFAULT 'default'` to be explicit and consistent.

### Row-deletion at zero quantity
Section 7 says the positions row is deleted when `quantity` reaches 0. This creates a gap: after selling all shares, the trade history still references that ticker, but `GET /api/portfolio` will not show it. The plan does not specify whether the frontend should show closed positions anywhere (e.g., a "closed" section in the positions table). The P&L on a fully sold position is permanently unrepresentable from the positions table.

### `actions` JSON column in `chat_messages`
Section 7 defines `actions` as `TEXT (JSON — trades executed, watchlist changes made)`. The schema for this JSON blob is never defined. Agents will invent their own structure. A concrete schema should be provided — e.g., `{ "trades": [{...}], "watchlist_changes": [{...}] }` — to match the structured output schema from Section 9 exactly.

### No `UNIQUE` constraint on `watchlist.ticker`
Section 7 defines `ticker TEXT PRIMARY KEY` for the watchlist table, which implicitly creates a unique constraint. This is fine. But the seed data inserts 10 rows — if the backend runs seed logic on startup without checking for existing rows, re-running the container will fail with `UNIQUE constraint failed` on the second start. The plan should specify idempotent seeding (e.g., `INSERT OR IGNORE`).

---

## 5. API Contracts

### Error response shape is inconsistent
The only defined error format is `{ "success": false, "error": "Insufficient cash" }` for trade failures. All other endpoints have no defined error shape. FastAPI's default validation error format (`{ "detail": [...] }`) will be used for missing/invalid fields. The frontend needs to handle both. This should be standardized.

### `POST /api/watchlist` — duplicate ticker behavior
If the user adds a ticker already in the watchlist, the `PRIMARY KEY` constraint will cause a SQLite error. The plan does not specify whether this should return 409 Conflict, 200 OK (idempotent), or silently ignore. Agents will make different choices.

### `DELETE /api/watchlist/{ticker}` — ticker not found
No error shape defined for attempting to delete a ticker not in the watchlist. Should be 404. Not specified.

### `POST /api/portfolio/trade` — quantity validation
The plan specifies "insufficient cash" and "insufficient shares" as validation cases. Missing:
- `quantity <= 0` (zero or negative quantity)
- `quantity` is non-integer (if integer enforcement is decided per Q2)
- Ticker not in price cache (no current price available to fill against)
- Ticker string is malformed (not a 6-digit code)

### `GET /api/portfolio` — when price cache is empty
If the price cache has not been populated yet (container just started, yfinance first poll pending), `current_price` for positions is undefined. The plan does not specify what to return — 0, null, or the `avg_cost` as a fallback. Frontend code that computes `unrealized_pnl = (current_price - avg_cost) * quantity` will produce NaN or 0 silently.

### `/api/chat` — no request/response schema defined
Section 9 defines the LLM structured output schema but does not define the HTTP request body for `POST /api/chat`. Presumably `{ "message": "user text" }` but this is never stated. The response schema is also not defined — presumably the structured output JSON is returned directly, or wrapped. Agents will invent their own wrapping.

### No rate limiting or input length limits
`POST /api/chat` accepts arbitrary-length messages. A user (or test) sending a 100KB message will be forwarded to the LLM, consuming tokens and potentially hitting model input limits. Not a production concern for a demo, but agents should at least truncate or validate `message` length.

---

## 6. Market Data — yfinance Limitations and Edge Cases

### yfinance is unofficial and unstable
Yahoo Finance has broken yfinance multiple times by changing their API surface without notice. The plan describes yfinance as a stable `pip install` dependency, but in production use it fails 1–5% of requests with `JSONDecodeError` or `KeyError` on schema changes. The yfinance poller must catch all exceptions per ticker, log them, and continue. The plan mentions "skipped if not found" but not general exception handling.

### KRX trading hours: prices freeze for 17+ hours per day
KRX trades 09:00–15:30 KST (UTC+9). Outside those hours yfinance returns the last closing price indefinitely. `direction` will always be `"flat"`, sparklines will be flat, and the UI will appear broken. The plan does not address this. Options include:
- Show a "market closed" banner based on KST time
- Fall back to simulator outside market hours automatically
- Document this as expected behavior

The plan is silent on this, and it is a significant UX issue for a demo that may be run outside Korean trading hours (which is very likely for a global course audience).

### `.KS` / `.KQ` suffix guessing adds latency
Section 13 Q1 recommends trying `.KS` first, then falling back to `.KQ`. This means adding a ticker triggers two sequential yfinance requests in the worst case (KOSDAQ ticker). yfinance calls can take 1–3 seconds each. The user adding a KOSDAQ ticker could wait 3–6 seconds for confirmation. This should be called out as a UX latency issue.

### yfinance `shortName` for Korean tickers
yfinance's `shortName` for Korean tickers is often in Korean characters (e.g., "삼성전자") or in an abbreviated romanized form that differs from common English names. The plan says to use `shortName` as the company name fallback, but does not address the Korean character encoding issue. Frontend must handle UTF-8 Korean names correctly, and the positions table display assumes English names.

### Rate limiting from Docker
Yahoo Finance may rate-limit requests from cloud/container IP ranges. This is a known issue with yfinance in CI environments. The plan makes no mention of retry logic or exponential backoff for the poller. With 10+ tickers polled every 15 seconds, hitting a rate limit will silence the entire price feed without any user-visible indication.

### Seed prices may be stale
Section 7 seeds Samsung Electronics at ₩75,000. If the actual price at demo time is ₩85,000, switching from simulator (starting at ₩75,000) to yfinance (showing ₩85,000) mid-session will cause a visible price jump and incorrect `session_change_pct`. Not a correctness bug, but worth noting.

---

## 7. LLM Integration

### Structured output reliability with Cerebras / `gpt-oss-120b` via OpenRouter
The plan specifies `openrouter/openai/gpt-oss-120b` with Cerebras as inference provider (Section 9, Section 3). OpenRouter's structured output support (JSON schema enforcement) varies by model and routing. If the Cerebras-routed `gpt-oss-120b` does not natively support OpenAI-style `response_format: { type: "json_schema" }`, LiteLLM will fall back to prompt-only JSON enforcement. This can produce malformed JSON (missing fields, wrong types) under adversarial inputs or long conversation histories. The backend must validate the parsed response against the schema and have a fallback (return a plain-text error message) rather than crashing.

### `watchlist_changes.name` required on `add` but LLM may omit it
Section 9 specifies that `action: "add"` requires `name`. The LLM may not always provide `name` — especially if it only knows the ticker code. The backend must handle a missing `name` gracefully (fall back to yfinance lookup or ticker code), not raise a validation error.

### Prompt injection via chat messages
The user's chat message is included verbatim in the LLM prompt. A user (or test) could send a message that instructs the LLM to ignore the structured output format and return plain text, or to execute a large number of trades. The plan makes no mention of input sanitization or guardrails. For a demo/course project this is acceptable, but agents should be aware.

### OpenDART integration with LLM: no tool-call design
Section 9 step 3 says the backend "optionally fetches relevant OpenDART data to include in context" based on whether "the user's question appears to concern company fundamentals." The mechanism for this determination is not specified. Options:
- Keyword matching ("revenue", "profit", "earnings") — brittle
- A second LLM call to classify the query — expensive
- Always fetch OpenDART context if key is present — simple but noisy

This is completely unspecified. The agent implementing chat will have to invent this logic.

### The single mock fixture is too simple for E2E test coverage
Section 9 defines one mock response with empty `trades` and `watchlist_changes`. The E2E test scenario "AI chat (mocked): send a message, receive the fixture response, no trades executed" does not test the agentic path at all — it never exercises the trade auto-execution code path. A second mock fixture that includes a trade and a watchlist change would allow testing the full execution pipeline. Consider supporting a `LLM_MOCK_SCENARIO` environment variable to select between fixtures.

### Conversation history truncation
"Last 20 messages" (Sections 7 and 9) is a hard cap. With verbose exchanges this is fine, but the plan does not specify whether the user message being submitted counts toward the 20 or is appended after the cap. Agents will interpret this differently, leading to off-by-one behavior in context window management.

---

## 8. Testing Strategy

### No test for SSE streaming behavior
Section 12 lists E2E scenarios but "SSE resilience: disconnect and verify reconnection" is the only SSE test. There is no test for:
- Initial price population after SSE connect (sparklines start empty then fill)
- Price flash animation triggering on price change
- `session_change_pct` correct value in SSE payload
- SSE event arriving while a trade is in flight (race condition)

### E2E test coverage of LLM auto-execution is absent
As noted above, the single mock fixture returns empty `trades`. The trade auto-execution path (LLM specifies trades → backend executes → chat response shows confirmation) is not covered by E2E tests at all.

### No test for yfinance mode
All tests run with `USE_YFINANCE=false` (simulator). The yfinance poller logic — suffix mapping, error handling, session_open calculation — has no test coverage defined. The backend unit tests in Section 12 mention testing "yfinance poller correctly maps `005930` → `005930.KS`" but no test infrastructure for yfinance is described (mocking the network, etc.).

### No test for concurrent trade execution
Two simultaneous `POST /api/portfolio/trade` requests could both read the same `cash_balance` before either writes the deduction, resulting in a negative balance. SQLite serializes writes, but the read-compute-write logic in the backend must be wrapped in a transaction. No test covers this race condition.

### Playwright container version not specified
Section 12 references a Playwright container in `docker-compose.test.yml` but specifies no version tag. `mcr.microsoft.com/playwright:latest` changes frequently and can break tests. A specific version tag should be pinned.

### No backend integration tests
Section 12 lists backend unit tests (pure logic) and E2E tests (full stack). There are no integration tests that run the FastAPI app against a real SQLite instance without Docker. This gap means schema errors (wrong column name, missing table) will only surface in E2E, which is slower to debug.

---

## 9. Simplification Opportunities

### Remove OpenDART entirely for v1
OpenDART adds three ambiguities (Q3, name resolution, LLM context injection logic) and one optional environment variable for a feature that may never be tested. The LLM can provide useful portfolio analysis without fundamentals. Recommend deferring OpenDART to a "stretch goal" section and removing it from the core build scope. This eliminates Section 13 Q3 entirely and simplifies the `POST /api/watchlist` name resolution logic.

### Simplify `portfolio_snapshots`
The current scheme (snapshot on trade + snapshot on `GET /api/portfolio/history` call) is fragile. A simple 60-second background timer writing a snapshot is more predictable and easier to test. The GET side-effect should be removed (see Section 5 above).

### Remove `session_open` from the SSE event and watchlist response
`session_open` is computed at server startup. It resets on restart. It means different things in simulator vs. yfinance mode. For a demo, showing only `direction: up/down/flat` and a raw price is sufficient. If session change % is desired in the UI, it can be derived from the first price in the sparkline buffer. Removing `session_open` from the SSE event simplifies the backend and the frontend.

### Drop the `name` column from `watchlist` and resolve at query time
If OpenDART is deferred, the only source of company names is yfinance. Rather than storing names in the watchlist table (requiring resolution at insert time), resolve names lazily via yfinance at `GET /api/watchlist` time and cache them in memory. This eliminates the name-on-insert ambiguity entirely.

---

## 10. Open Questions from Section 13 — Downstream Implications

### Q1 — KOSPI vs. KOSDAQ suffix detection
**Recommended resolution:** Implement `.KS`-first fallback as described. Document it. The latency impact is acceptable (< 5 seconds for KOSDAQ tickers). **However**, if OpenDART is kept in scope, use the OpenDART corp search as the primary resolution path when the key is present — it returns the exchange field directly and avoids the two-request fallback entirely.

**Downstream impact if unresolved:** The yfinance poller will be implemented with either a hardcoded `.KS` suffix (breaking KOSDAQ tickers silently) or no suffix (breaking all Korean tickers). This is a critical correctness issue for `USE_YFINANCE=true`.

### Q2 — Fractional shares
**Recommended resolution:** Enforce integer quantity at the API validation layer (`quantity: int`, minimum 1). Keep `REAL` in the SQLite schema for forward compatibility, but document that the validation layer rejects non-integers. This resolves the contradiction between Section 7 and Section 13.

**Downstream impact if unresolved:** The backend agent will use `REAL` and allow fractional quantities, the frontend will display `10.5 shares`, and unit tests will mix integer and float test cases. KRX realism is undermined.

### Q3 — OpenDART usage scope
**Recommended resolution:** If not deferring OpenDART (see Section 9 above), specify "company profile only" (name, sector, listing date). Financial statements and filings require significantly more OpenDART API surface area and add prompt context that may confuse the LLM's structured output with numbers. Keep scope minimal.

**Downstream impact if unresolved:** The OpenDART client will be built to an arbitrary scope by whichever agent implements it first, potentially making expensive multi-request API calls per chat message, or not fetching anything useful. The LLM context injection logic cannot be designed without knowing what data is available.

---

## Summary of Highest-Priority Issues

The following issues are most likely to cause implementation failures or agent-to-agent inconsistencies and should be resolved before implementation begins:

1. **`backend/db/` vs. `backend/schema/`** — CLAUDE.md and PLAN.md are in conflict. Pick one and update both files.
2. **`POST /api/watchlist` `name` field** — required or optional? Resolve the backend-resolves-name vs. client-supplies-name contradiction.
3. **`GET /api/portfolio/history` write side-effect** — remove it. Use a background timer instead.
4. **SQLite WAL mode** — explicitly specify `PRAGMA journal_mode=WAL` in the database initialization code.
5. **`session_open` semantics in yfinance mode** — use yfinance `open` price or document the limitation.
6. **KRX market hours** — specify UI behavior when market is closed (flat prices are not a bug).
7. **Q2 fractional shares** — resolve before schema is written.
8. **Single LLM mock fixture** — add a second fixture with a trade to enable E2E coverage of auto-execution.
9. **`/api/chat` request/response schema** — define it explicitly in Section 8.
10. **uvicorn worker count** — explicitly state `--workers 1` in the Dockerfile CMD.

---

## Resolution (2026-11-17)

Every finding above is now either **implemented in code** (market data, `backend/app/market/`) or **decided in `PLAN.md`** for the agents who build the remaining platform.

### Implemented in the market data backend

| Finding | Resolution |
|---|---|
| SSE pushes stale prices 30× between yfinance polls | Sources write to the cache only when the price changes. SSE sends only changed tickers (per-ticker events, `id` = cache version). A `: keepalive` comment goes out after 15 s idle. |
| Empty cache on first SSE connect / first yfinance poll fails silently | `start()` and `add_ticker()` write a first price before returning. SSE sends a full snapshot on connect. A failed first poll is retried with back-off. |
| Health check doesn't reflect yfinance state | `GET /api/health` returns `market_data` (`ok` / `degraded` / `stopped`), `source` and `market_session`. `degraded` is set after 3 consecutive poll failures. |
| yfinance unstable / rate-limited, no back-off | One batched download per cycle, run in a worker thread. Every exception is caught. Exponential back-off runs from 15 s to 5 min. NaN or missing symbols keep their last price. |
| `.KS`/`.KQ` suffix guessing & latency (Q1) | The bundled `backend/schema/krx_listing.csv` resolves the suffix without network calls. Only unlisted tickers are probed (`.KS`, then `.KQ`). Successful resolutions are memoized. |
| `shortName` is Korean or terse | Names come from the listing first, then OpenDART, then `shortName`, then the ticker code, via `NameRegistry`. The SSE payload is UTF-8 (`ensure_ascii=False`). |
| Position name missing after its watchlist row is removed | `NameRegistry` is independent of the watchlist table. `TickerTracker` keeps held tickers priced (tracked = watchlist ∪ positions). |
| `session_open` semantics in yfinance mode | The first price seen after server start, the same as in the simulator. Documented in PLAN §6. |
| KRX market hours: frozen prices look broken | `market_session()` (KST) is exposed in health. PLAN tells the frontend to show a "Market closed" badge in yfinance mode. The simulator runs 24/7 by design. |
| Ticker validation unspecified | `normalize_ticker()`: `^[0-9A-Z]{6}$`; strips `.KS`/`.KQ`; string-only. |
| Trades when the cache has no price | Sources never write 0 or non-int prices (the cache rejects them). PLAN requires a "No price available" rejection. |
| Missing SSE tests, thread-safety test, full-universe test | `test_stream.py` covers the generator and a raw ASGI endpoint with disconnect. There is an 8-thread cache test. A conformance suite runs both sources on all 10 default tickers. |
| uvicorn `--workers N` would split the cache | `app/main.py`, PLAN §3 and §11, and the backend docs all require `--workers 1`. |
| Seed prices are stale | Documented in PLAN §7, with live yfinance figures from 2026-11-17. The seeds only drive the simulator. |

**Still open for the backend agent:** OpenDART name lookup; reading watchlist ∪ positions from the DB in the lifespan (it currently starts with `DEFAULT_TICKERS`).

### Decided in PLAN.md (for the remaining agents)

| # | Finding | Decision (PLAN section) |
|---|---|---|
| 1 | `backend/db` vs `backend/schema` | `backend/schema/` everywhere (§4). The folder now holds `krx_listing.csv`. |
| 2 | `POST /api/watchlist` `name` | Optional; the backend resolves it. Status codes 201, 409 (duplicate), 404 (unknown ticker) and 422 (§8). |
| 3 | `GET /api/portfolio/history` write side-effect | GET is read-only. Snapshots are taken after each trade plus every 60 s in the background (§7). |
| 4 | SQLite WAL | `journal_mode=WAL` and `busy_timeout=5000`. Each trade runs in one `BEGIN IMMEDIATE` transaction (§7). |
| 5 | `session_open` in yfinance mode | First price seen; documented (§6). |
| 6 | KRX market hours | `market_session` in health; "Market closed" badge (§6, §8). |
| 7 | Q2 fractional shares | Whole shares only; validated as a positive int (§13). |
| 8 | Single LLM mock fixture | A second "buy" fixture with a trade and a watchlist add, plus an E2E scenario (§9, §12). |
| 9 | `/api/chat` schema | Request and response defined; `actions` JSON shape defined (§7, §8). |
| 10 | uvicorn worker count | `--workers 1` (§3, §11). |
| — | Indexes, `portfolio_state` PK, idempotent seeding | Added (§7). |
| — | Error shape, duplicate/404 behaviour, trade validation, empty-cache fallback | "Validation & Error Conventions" (§8). |
| — | Malformed LLM output, `name` omitted on add, history off-by-one, message length | §9 and §8. |
| — | OpenDART scope (Q3) and trigger | Profile and key financials, keyword heuristic, 24 h cache (§9, §13). |
| — | Playwright version, Compose only in `test/` | Pinned image; no top-level compose (§4, §12). |

**Not adopted:**
- *Remove OpenDART for v1*: kept, but optional and narrowly scoped (Q3).
- *Drop `session_open` / the `name` column*: kept. PLAN's payload already depends on them, and they are now well-defined.
