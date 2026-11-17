# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live Korean stock market data (KOSPI/KOSDAQ), lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

---

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default KOSPI tickers with live-updating prices in a grid
- ₩10,000,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, company name, quantity, average cost, current price, unrealized P&L, % change
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

---

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background task: market data sim / yfinance     │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real (~20-min delayed) KOSPI/KOSDAQ prices via `yfinance` if `USE_YFINANCE=true`. OpenDART API (optional, separate) used to enrich the AI assistant with company fundamentals.

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |
| yfinance for real prices | No API key, no account needed; `pip install yfinance`; covers all KRX tickers; ~20-min delay (Yahoo's figure for Korea) is acceptable for a sim portfolio |
| Simulator as default | Works offline, deterministic for tests (`SIM_SEED`), no rate limits — yfinance is opt-in via env var |
| Single uvicorn worker | The price cache and simulator are in-process state; `--workers N` would give each worker diverging prices. Always run `--workers 1`. |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── schema/               # SQL schema, seed data, krx_listing.csv (ticker → English name, KOSPI/KOSDAQ)
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Volume mount target (SQLite file lives here at runtime)
│   └── .gitkeep              # Directory exists in repo; finally.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

> `docker-compose.yml` is **not** part of the core build — omit it. The start scripts wrap `docker run` directly.

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/schema/`** contains SQL schema definitions, seed logic and `krx_listing.csv` (bundled listing snapshot used for names and the yfinance suffix). The backend lazily initializes the database on first request — creating tables and seeding default data if the SQLite file doesn't exist or is empty.
- **`db/`** at the top level is the runtime volume mount point. The SQLite file (`db/finally.db`) is created here by the backend and persists across container restarts via Docker volume.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Compose is used **only** here — never add a top-level `docker-compose.yml`. Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Set to "true" to fetch real (~20-min delayed) KOSPI/KOSDAQ prices via yfinance.
# No API key needed — yfinance is a free library. When false, the built-in simulator is used.
USE_YFINANCE=false

# Optional: OpenDART API key for company fundamental data
# Used by the AI assistant to enrich responses with financial disclosures.
# OpenDART is a corporate disclosure API (like SEC EDGAR) — it does NOT provide prices.
# Register at: https://opendart.fss.or.kr
OPENDART_API_KEY=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false

# Optional simulator tuning (defaults shown)
# SIM_SEED=            # integer → reproducible prices (E2E tests set this)
# SIM_TIME_SCALE=200   # market-time speed-up so prices move ~1 tick per step
# SIM_EVENT_RATE=0.1   # 2–5% jump events per ticker per minute; 0 disables
# SIM_UPDATE_INTERVAL=0.5
# YFINANCE_POLL_INTERVAL=15
```

### Behavior

- If `USE_YFINANCE=true` → backend polls yfinance for real KOSPI/KOSDAQ prices (~20-min delayed, every 15 seconds)
- If `USE_YFINANCE=false` (default) → built-in simulator generates prices
- If `OPENDART_API_KEY` is set and non-empty → AI assistant can query OpenDART for company financial data to enrich chat responses
- If `OPENDART_API_KEY` is absent → AI assistant works without company fundamental data
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- The backend reads `.env` from the project root (mounted into the container or read via docker `--env-file`)

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the yfinance poller implement the same abstract interface. The backend selects which to use based on `USE_YFINANCE`. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

Runs as an in-process background task with no external dependencies.

- Generates prices in KRW as whole integers, snapped to the real KRX tick table (e.g. ₩100 steps for ₩50,000–₩200,000) and clamped to the ±30% daily limit around `session_open`
- Uses geometric Brownian motion (GBM) with per-ticker volatility, sped up by `SIM_TIME_SCALE` (default 200) so prices visibly move ~1 tick per step
- Updates at ~500ms intervals; only tickers whose price changed are written to the cache
- Correlated moves via a market factor + sector factor model (e.g., Samsung Electronics and SK Hynix correlate ≈0.73)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama (≈1 per ticker per 10 min), sometimes spilling over to sector peers
- A weak mean-reversion pull toward the seed price keeps hours-long demos within a believable range
- Starts from the KOSPI seed prices in Section 7; tickers added at runtime get a deterministic pseudo-price derived from the code
- Runs 24/7 — it deliberately ignores KRX market hours
- Tracks `session_open` price (price at server startup) for session change % calculation
- Full design: `planning/MARKET_SIMULATOR.md`

### yfinance Poller (Optional, `USE_YFINANCE=true`)

Uses the `yfinance` Python library (`pip install yfinance`) — no API key or account required.

- Polls all tracked tickers every **15 seconds** in **one batched** `yf.download` call, run in a worker thread
- Suffix resolution (Q1, resolved): look the ticker up in `backend/schema/krx_listing.csv` (`KOSPI` → `.KS`, `KOSDAQ` → `.KQ`); if absent, probe `.KS` then `.KQ`; if neither has data the ticker is rejected as unknown
- Prices returned by yfinance are already in KRW — rounded and snapped to the tick table
- Data is ~20 minutes delayed (Yahoo's stated delay for Korea)
- `session_open` is the **first price received after server start**, not Yahoo's official day open. Restarting the server resets it.
- Only changed prices are written to the cache (no repeated "flat" events between polls)
- If a ticker is missing or returns NaN (bad code, delisted), it is skipped and the cache retains the last known price
- Any poll error is caught; the poller backs off exponentially (15 s → 5 min) and `GET /api/health` reports `market_data: "degraded"` after 3 consecutive failures
- **Market hours:** outside the KRX session (09:00–15:30 KST, weekdays) prices stay frozen at the last close. This is expected, not a bug. `GET /api/health` returns `market_session` (`pre_open` | `regular` | `closing_auction` | `after_hours` | `closed`); in yfinance mode the frontend shows a "Market closed" badge when it is not `regular`/`closing_auction`. Exchange holidays are not modelled.
- The container needs outbound HTTPS to Yahoo; do not run it with `--network none` in yfinance mode

### OpenDART Integration (Optional AI Enrichment)

OpenDART (`opendart.fss.or.kr`) is Korea's official corporate disclosure system (FSS). It is **not** a price feed — it provides financial statements, quarterly/annual reports, and corporate disclosures.

When `OPENDART_API_KEY` is set, the AI assistant may query OpenDART to enrich chat responses with fundamental context. It is not queried on every message — only when the LLM determines fundamentals are relevant.

**Company names** are resolved by the backend, never required from the client, in this order: bundled `krx_listing.csv` → OpenDART `corp_name_eng` (if `OPENDART_API_KEY` is set) → yfinance `shortName` (terse, sometimes Korean — UI must render UTF-8) → the ticker code itself. Names live in an in-memory name registry (seeded from the listing and the `watchlist` table) so positions keep their name even after their watchlist row is removed.

### Shared Price Cache

- One background task (simulator or yfinance poller) writes to an in-memory price cache
- Cache holds per ticker: latest price, previous price, session open price (all `int` KRW), timestamp, and the cache version at which it was written
- SSE streams, REST endpoints and trade execution read from this cache
- **Tracked tickers = watchlist ∪ open positions.** A held stock keeps a live price after it is removed from the watchlist; it is untracked only when it is neither watched nor held. The backend re-syncs the tracked set after every watchlist change and every trade that opens or closes a position.
- Interface design: `planning/MARKET_DATA_INTERFACE.md`; implementation summary: `planning/MARKET_DATA_SUMMARY.md`

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API (`onmessage`; events are unnamed)
- On connect the server sends one event per tracked ticker (initial snapshot); afterwards, every ~500ms, it sends only tickers whose price changed
- Each event carries `id: <cache version>`. On reconnect the browser sends `Last-Event-ID` and the server resumes from there (an unknown/future id gets a full snapshot)
- `retry: 2000` tells the browser to reconnect after 2 s; a `: keepalive` comment is sent after 15 s without data (yfinance mode can be quiet for minutes)
- SSE never announces removals — the frontend drops rows based on the watchlist/chat responses and ignores events for tickers it no longer shows

**SSE event JSON shape** (each `data:` payload, one ticker per event):
```json
{
  "ticker": "005930",
  "name": "Samsung Electronics",
  "price": 75400,
  "prev_price": 75200,
  "session_open": 74800,
  "session_change_pct": 0.80,
  "direction": "up",
  "timestamp": "2026-11-13T09:30:01.234Z"
}
```

Field definitions:
- `price` / `prev_price`: KRW integers
- `session_open`: price at server startup (basis for `session_change_pct`)
- `session_change_pct`: `((price - session_open) / session_open) * 100`, rounded to 2dp
- `direction`: `"up"` | `"down"` | `"flat"`

---

## 7. Database

### SQLite with Lazy Initialization

The backend checks for the SQLite database on startup (or first request). If the file doesn't exist or tables are missing, it creates the schema and seeds default data. No separate migration step, no manual setup.

- Every connection sets `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` so SSE-heavy multi-tab demos don't hit "database is locked"
- Schema uses `CREATE TABLE IF NOT EXISTS`; seeding uses `INSERT OR IGNORE`, so restarts are idempotent
- Trade execution (read cash/position → validate → write cash, position, trade, snapshot) runs in **one transaction** (`BEGIN IMMEDIATE`) so concurrent trades cannot overdraw cash

### Schema

No `user_id` columns — this is a single-user application. Natural keys are used where appropriate.

**portfolio_state** — Cash balance (single row, always exists after seed)
- `id` TEXT PRIMARY KEY (always `'default'`)
- `cash_balance` REAL (default: `10000000.0` KRW)
- `updated_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `ticker` TEXT PRIMARY KEY (6-digit KRX code, e.g., `"005930"`)
- `name` TEXT (English company name, e.g., `"Samsung Electronics"`)
- `added_at` TEXT (ISO timestamp)

**positions** — Current holdings (one row per ticker; row deleted when quantity reaches 0)
- `ticker` TEXT PRIMARY KEY
- `quantity` REAL (always a whole number — the API rejects non-integer quantities, see Q2)
- `avg_cost` REAL (KRW; updated as weighted average on each buy: `(old_qty * old_avg_cost + new_qty * new_price) / (old_qty + new_qty)`)
- `updated_at` TEXT (ISO timestamp)

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL
- `price` REAL (KRW)
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart)
- `id` TEXT PRIMARY KEY (UUID)
- `total_value` REAL (KRW)
- `recorded_at` TEXT (ISO timestamp)

Snapshots are recorded immediately after each trade execution **and** by a background task every 60 seconds (skipped if the previous snapshot is less than 60 s old). `GET /api/portfolio/history` is read-only — it never writes. The frontend may append the live header total as the last chart point.

**chat_messages** — Conversation history with LLM (capped at last 20 messages loaded per request)
- `id` TEXT PRIMARY KEY (UUID)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON, null for user messages). Shape: `{"trades": [{"ticker", "side", "quantity", "price", "success", "error"?}], "watchlist_changes": [{"ticker", "action", "name"?, "success", "error"?}]}` — the requested actions annotated with their execution results
- `created_at` TEXT (ISO timestamp)

**Indexes:** `trades(executed_at)`, `trades(ticker)`, `portfolio_snapshots(recorded_at)`, `chat_messages(created_at)`.

### Default Seed Data

- `portfolio_state`: `cash_balance = 10000000.0`
- Ten watchlist entries (KOSPI blue chips):

| ticker | name | seed price (KRW) |
|--------|------|-----------------|
| 005930 | Samsung Electronics | 75,000 |
| 000660 | SK Hynix | 180,000 |
| 035420 | NAVER | 200,000 |
| 035720 | Kakao | 40,000 |
| 005380 | Hyundai Motor | 230,000 |
| 373220 | LG Energy Solution | 350,000 |
| 207940 | Samsung Biologics | 800,000 |
| 068270 | Celltrion | 200,000 |
| 000270 | Kia | 100,000 |
| 005490 | POSCO Holdings | 300,000 |

Seed prices are illustrative and drift from reality (a live yfinance check on 2026-11-17 showed Samsung Electronics ≈ ₩191,800 and SK Hynix ≈ ₩1,124,000). They only seed the simulator; yfinance mode always uses real prices. Switching modes mid-session therefore produces a price jump — expected.

---

## 8. API Endpoints

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker, name?}` — `name` optional, backend resolves it |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

### Validation & Error Conventions

- Tickers must match `^[0-9A-Z]{6}$` after trimming/upper-casing (a `.KS`/`.KQ` suffix is stripped). Always strings — leading zeros matter.
- Trade `quantity` must be a positive **integer** (KRX has no fractional shares). `side` is `"buy"` or `"sell"`.
- Trades fill at the cached price; if the ticker has no price yet the backend first starts tracking it, and rejects with `"No price available"` if it still has none. It never fills at 0.
- `POST /api/portfolio/trade` business-rule failures return **400** with `{"success": false, "error": "..."}` (`Insufficient cash`, `Insufficient shares`, `No price available`, `Invalid ticker`).
- All other endpoints use FastAPI's `{"detail": "..."}` with: **422** malformed body/ticker, **404** unknown ticker (source can't price it) or `DELETE` of a ticker not in the watchlist, **409** adding a ticker already in the watchlist.
- `POST /api/chat` `message` is limited to 2,000 characters (422 if longer).

### Response Schemas

**`GET /api/portfolio`**
```json
{
  "cash_balance": 8500000,
  "total_value": 10200000,
  "positions": [
    {
      "ticker": "005930",
      "name": "Samsung Electronics",
      "quantity": 10,
      "avg_cost": 74000,
      "current_price": 75400,
      "market_value": 754000,
      "unrealized_pnl": 14000,
      "pnl_pct": 1.89
    }
  ]
}
```

**`POST /api/portfolio/trade`** — request `{ticker, quantity, side}`
```json
{ "success": true, "ticker": "005930", "side": "buy", "quantity": 5, "price": 75400, "cash_balance": 8123000 }
```
```json
{ "success": false, "error": "Insufficient cash" }
```

**`GET /api/watchlist`**
```json
[
  {
    "ticker": "005930",
    "name": "Samsung Electronics",
    "price": 75400,
    "prev_price": 75200,
    "session_open": 74800,
    "session_change_pct": 0.80,
    "direction": "up"
  }
]
```
`price`/`prev_price`/`session_open` are `null` (and `direction` `"flat"`) for a ticker that has not been priced yet.

`GET /api/portfolio`: if a position's ticker has no cached price yet, `current_price` falls back to `avg_cost` (P&L 0) rather than erroring. `name` comes from the name registry, so it is present even for positions no longer on the watchlist.

**`POST /api/watchlist`** — request `{"ticker": "247540"}` → **201**
```json
{ "ticker": "247540", "name": "EcoPro BM", "price": 86200 }
```

**`POST /api/chat`** — request `{"message": "Buy 10 Samsung"}` → **200**
```json
{
  "message": "Bought 10 shares of 005930 Samsung Electronics at ₩75,400.",
  "trades": [{"ticker": "005930", "side": "buy", "quantity": 10, "price": 75400, "success": true}],
  "watchlist_changes": []
}
```
`trades` / `watchlist_changes` are the executed results (same shape as `chat_messages.actions`); failed items carry `"success": false, "error": "..."`.

**`GET /api/health`**
```json
{ "status": "ok", "market_data": "ok", "source": "simulator", "tickers": 10, "market_session": "regular" }
```
`market_data` is `ok` | `degraded` | `stopped`; `source` is `simulator` | `yfinance`.

**`GET /api/portfolio/history`**
```json
[
  { "total_value": 10000000, "recorded_at": "2026-11-13T09:00:00Z" },
  { "total_value": 10200000, "recorded_at": "2026-11-13T09:30:00Z" }
]
```

---

## 9. LLM Integration

When writing code to make calls to LLMs, use the cerebras-inference skill to call LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads the **last 20 stored messages** from `chat_messages` as conversation history (the new user message is appended after them, so the prompt holds up to 21)
3. If `OPENDART_API_KEY` is set and the message mentions fundamentals (keyword heuristic: revenue, profit, earnings, EPS, valuation, fundamentals, 매출, 실적, …), fetches the company profile and latest key financials (Q3) for tickers mentioned in the message or held, cached in memory for 24 h
4. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
5. Calls the LLM via LiteLLM → OpenRouter, requesting structured output
6. Parses and validates the structured JSON response against the schema; if parsing fails the backend returns a friendly error message with no actions instead of a 500
7. Auto-executes any trades or watchlist changes specified in the response
8. Stores the message and executed actions in `chat_messages`
9. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "005930", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "035420", "action": "add", "name": "NAVER"},
    {"ticker": "000270", "action": "remove"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells)
- `watchlist_changes` (optional): `action` is either `"add"` or `"remove"`. `name` is optional — if the LLM omits it, the backend resolves it like `POST /api/watchlist`

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade fails validation (e.g., insufficient cash), the error is included in the chat response so the LLM can inform the user.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant for Korean equities" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning grounded in Korean market context
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Reference Korean ticker codes and company names (e.g., "005930 Samsung Electronics")
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns this deterministic fixture instead of calling OpenRouter:

```json
{
  "message": "Your portfolio looks well-diversified across Korean tech and industrial sectors. Samsung Electronics (005930) is your largest position. Consider adding exposure to financials for balance.",
  "trades": [],
  "watchlist_changes": []
}
```

If the user message contains the word "buy" (case-insensitive), mock mode instead returns a second fixture that exercises auto-execution:

```json
{
  "message": "Buying 1 share of 005930 Samsung Electronics and adding 035420 NAVER to your watchlist.",
  "trades": [{"ticker": "005930", "side": "buy", "quantity": 1}],
  "watchlist_changes": [{"ticker": "035420", "action": "add"}]
}
```

This enables fast, free, reproducible E2E tests of both the plain and the agentic path without an API key.

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture is up to the Frontend Engineer, but the UI must include:

- **Watchlist panel** — grid/table of watched tickers with: ticker code, company name, current price in KRW, session change %, and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, price over time. Clicking a ticker in the watchlist selects it.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — ticker, company name, quantity, avg cost (KRW), current price (KRW), unrealized P&L (KRW), % change
- **Trade bar** — ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value in KRW (updating live), connection status indicator, cash balance in KRW

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Canvas-based charting library preferred (Lightweight Charts or Recharts) for performance
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme
- Format all KRW prices with `₩` prefix and thousands separators (e.g., `₩75,400`)
- Prices are integers — no decimal display needed

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1` (exactly one worker — see Section 3)
```

FastAPI serves the static frontend files and all API routes on port 8000.

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The `db/` directory in the project root maps to `/app/db` in the container. The backend writes `finally.db` to this path.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data (implemented — `backend/tests/market/`): simulator prices are int, tick-aligned and inside the ±30% band; GBM moments, factor correlations, mean reversion and seeding are correct; yfinance poller maps `005930` → `005930.KS` and KOSDAQ → `.KQ`, handles missing/NaN tickers, backs off; both implementations pass one shared conformance suite; SSE snapshot/delta/resume/keepalive
- Portfolio: trade execution logic, P&L calculations, avg_cost weighted average, edge cases (selling more than owned, buying with insufficient cash, quantity-zero row deletion)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow, mock mode returns fixture
- API routes: correct status codes, response shapes match Section 8 schemas, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- KRW formatting renders correctly
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: Tests run with `LLM_MOCK=true` and `SIM_SEED=42` by default for speed and determinism. Pin the Playwright image to an exact version (e.g. `mcr.microsoft.com/playwright:v1.56.0-noble`), never `latest`.

**Key Scenarios**:
- Fresh start: default watchlist (10 KOSPI tickers) appears, ₩10,000,000 balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears (row deleted at zero quantity)
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive the fixture response, no trades executed
- AI chat (mocked, "buy"): the trade fixture executes — cash decreases, a 005930 position appears, NAVER is on the watchlist
- SSE resilience: disconnect and verify reconnection

---

## 13. Resolved Questions

**Q1 — KOSPI vs KOSDAQ suffix detection → resolved.** Use the bundled `backend/schema/krx_listing.csv` (market column) first; otherwise probe `.KS`, then `.KQ`; reject as unknown if neither has data. Successful resolutions are cached per ticker. Implemented in `backend/app/market/yfinance_source.py`.

**Q2 — Fractional shares → resolved: whole shares only.** The API validates `quantity` as a positive integer (Pydantic `conint(gt=0)`), matching KRX rules. The `REAL` column type stays for simplicity.

**Q3 — OpenDART usage scope → resolved.** v1 uses the company profile (`company.json`: `corp_name_eng`, industry, listing date) and the latest key financials (`fnlttSinglAcnt.json`: revenue, operating profit, net income). Disclosure lists are out of scope for v1. See `planning/MARKET_DATA_SOURCES.md` §4.4.
