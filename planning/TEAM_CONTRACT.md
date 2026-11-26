# Agent Team Contract

Shared rules for the FinAlly build team. PLAN.md is the spec; this file fixes **ownership** and the **seams** between agents. If you need to change a seam, update this file and message the affected teammates.

## Team & file ownership

| Agent (name) | Owns (only this agent edits) |
|---|---|
| `frontend` — Frontend Engineer | `frontend/**` |
| `backend` — Backend API Engineer | `backend/app/main.py`, `backend/app/api/**`, `backend/app/services/**`, `backend/app/config.py`, `backend/pyproject.toml`, `backend/uv.lock`, `backend/tests/api/**`, `backend/tests/services/**`, `backend/CLAUDE.md` |
| `database` — Database Engineer | `backend/app/db/**`, `backend/schema/*.sql`, `backend/tests/db/**` |
| `llm` — LLM Engineer | `backend/app/llm/**`, `backend/tests/llm/**` |
| `devops` — DevOps Engineer | `Dockerfile`, `.dockerignore`, `scripts/**`, `.env.example`, `.gitignore`, `README.md` (run instructions) |
| `tester` — Integration Tester | `test/**` (Playwright + `test/docker-compose.test.yml`) |

`backend/app/market/**` is finished — do not modify it; read `planning/MARKET_DATA_SUMMARY.md` / `backend/CLAUDE.md`.
Need a dependency added? Ask `backend` (sole owner of `pyproject.toml`/`uv.lock`). Need a change in someone else's files? Message them; don't edit.

## Git
Everyone works in the same tree on branch `agent-team`. **Do not commit, push, stash, reset or checkout** — the team lead commits. Never touch `.env` contents beyond reading.

## Paths & runtime conventions
- Backend runs from `backend/`: `uv run uvicorn app.main:app --port 8000 --workers 1`.
- DB path: env `DB_PATH`, default `<repo>/db/finally.db` (the repo-root `db/` dir, i.e. `parents[3]` from `backend/app/db/<module>.py`). Docker sets `DB_PATH=/app/db/finally.db`.
- Static frontend: env `STATIC_DIR`, default `backend/static`. Frontend `npm run build` emits a static export in `frontend/out/`; Docker copies it to `/app/static`. Backend mounts it at `/` **after** all `/api` routes (SPA fallback to `index.html`).
- `.env` is read from the repo root (`python-dotenv`, `override=False` so docker `--env-file` wins).
- In Docker: `WORKDIR /app` contains the backend project (`app/`, `schema/`, `pyproject.toml`), `/app/static`, `/app/db` (volume).

## Seam 1 — `app/db` (database → backend, llm)
`database` publishes the final signatures in `planning/DB_INTERFACE.md` as soon as possible (stub first, then fill). Expected shape (sync `sqlite3`, called via `asyncio.to_thread` or directly — fast enough):
- `init_db(path=None)` — create schema (`CREATE TABLE IF NOT EXISTS`) + seed (`INSERT OR IGNORE`); idempotent. `connect(path=None)` sets WAL + `busy_timeout=5000`, `row_factory=sqlite3.Row`.
- Watchlist: `list_watchlist()`, `add_watchlist(ticker, name) -> bool` (False if already present), `remove_watchlist(ticker) -> bool`.
- Portfolio: `get_cash()`, `list_positions()`, `list_trades(limit)`.
- `execute_trade(ticker, side, quantity:int, price:int, price_lookup: Callable[[str], int|None]) -> TradeResult` — one `BEGIN IMMEDIATE` transaction: read cash/position → validate (`Insufficient cash` / `Insufficient shares`) → write cash, position (weighted avg cost; delete row at 0), trade row, portfolio snapshot (total = cash + Σ qty × (price_lookup(t) or avg_cost)). Returns success/error, new cash, and whether a position was opened/closed.
- Snapshots: `record_snapshot(total_value)`, `last_snapshot_time()`, `list_snapshots()`.
- Chat: `add_chat_message(role, content, actions: dict|None)`, `recent_chat_messages(limit=20)` (oldest→newest).

## Seam 2 — `app/services` (backend → llm)
`backend` publishes `planning/SERVICES_INTERFACE.md`. A `PortfolioService` (on `app.state.services`) that both REST routes and the chat flow use, so validation is identical:
- `async trade(ticker, side, quantity) -> dict` (PLAN §8 trade response shape, success or `{"success": False, "error": ...}`; handles `normalize_ticker`, `tracker.ensure`, "No price available", tracker re-sync).
- `async add_watchlist(ticker, name=None) -> dict` / `async remove_watchlist(ticker) -> dict` (raise typed errors the route maps to 404/409/422; chat maps them to `success: False, error`).
- `portfolio()` (PLAN §8 `GET /api/portfolio` shape), `watchlist()` (PLAN §8 shape).

## Seam 3 — `app/llm` (llm → backend)
`llm` publishes `planning/LLM_INTERFACE.md`. Entry point: `async handle_chat(message: str, services: PortfolioService) -> dict` returning the PLAN §8 `POST /api/chat` shape, persisting both messages. `backend` mounts `POST /api/chat` and calls it. Honors `LLM_MOCK=true` fixtures exactly as PLAN §9. Model: `openrouter/openai/gpt-oss-120b` via LiteLLM, Cerebras provider (use the `cerebras` skill).

## Seam 4 — frontend ↔ backend ↔ tester
- REST/SSE shapes are exactly PLAN §6 and §8. Discrepancies are bugs — report to the owner.
- `frontend` publishes `planning/FRONTEND_TESTIDS.md`: the `data-testid` attributes the E2E suite can rely on (header total/cash/connection dot, watchlist rows `watchlist-row-<ticker>` with price cell, add/remove controls, trade bar inputs/buttons, positions rows `position-row-<ticker>`, heatmap, P&L chart, chat input/send/messages/loading).
- E2E env: `LLM_MOCK=true`, `SIM_SEED=42`, Playwright image pinned `mcr.microsoft.com/playwright:v1.56.0-noble`.

## Status board
Each agent appends a dated line to `planning/TEAM_STATUS.md` when it publishes an interface, finishes a milestone, or is blocked (`[agent] YYYY-MM-DD HH:MM — message`).
