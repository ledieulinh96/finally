# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live Korean stock market data (KOSPI/KOSDAQ), simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course. The full specification lives in [`planning/PLAN.md`](planning/PLAN.md).

## Features

- **Live price streaming** via SSE with green/red flash animations and sparklines
- **Simulated portfolio** — ₩10,000,000 virtual cash, market orders, instant fills, whole shares
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades, manages the watchlist
- **Watchlist management** — 10 KOSPI blue chips by default; add/remove manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite (`db/finally.db`) with lazy initialization
- **AI**: LiteLLM → OpenRouter (`openai/gpt-oss-120b` on Cerebras) with structured outputs
- **Market data**: Built-in KRX simulator (default: correlated GBM, real tick sizes, ±30% limit) or ~20-min delayed KRX prices via `yfinance` (optional)
- **Fundamentals**: OpenDART corporate disclosures (optional) to enrich AI answers

## Quick Start

```bash
# Configure
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env

# Run (macOS/Linux)
./scripts/start_mac.sh          # add --build to force a rebuild
./scripts/stop_mac.sh           # data persists in the finally-data volume

# Run (Windows PowerShell)
./scripts/start_windows.ps1
./scripts/stop_windows.ps1

# Or with plain Docker
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally

# Open http://localhost:8000
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `USE_YFINANCE` | No | `true` to poll real (~20-min delayed) KOSPI/KOSDAQ prices via yfinance; default uses the simulator |
| `SIM_SEED`, `SIM_TIME_SCALE`, `SIM_EVENT_RATE`, `SIM_UPDATE_INTERVAL` | No | Simulator tuning (see `planning/MARKET_DATA_SUMMARY.md`) |
| `OPENDART_API_KEY` | No | OpenDART key for company fundamentals and name lookup |
| `LLM_MOCK` | No | `true` for deterministic mock LLM responses (testing) |
| `GEMINI_API_KEY` | No | Dev tooling only — used by the Gemini review hook (see below) |

## Backend development

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --port 8000 --workers 1   # /api/health, /api/stream/prices
uv run --extra dev pytest                              # market data test suite
uv run market_data_demo.py                             # terminal price dashboard
```

## Project Structure

```
finally/
├── frontend/          # Next.js static export
├── backend/           # FastAPI uv project
│   ├── app/market/    # Market data: simulator, yfinance poller, price cache, SSE
│   └── schema/        # SQL schema, seed data, krx_listing.csv
├── planning/          # Project documentation and agent contracts (PLAN.md)
├── test/              # Playwright E2E tests + docker-compose.test.yml
├── db/                # SQLite volume mount (finally.db is gitignored)
├── scripts/           # Start/stop helpers
└── .claude/           # Claude Code agents, commands, hooks and scripts
```

## Development: AI Review Tooling

This repo ships Claude Code configuration for automated reviews by Gemini.

**Setup**

```bash
npm install -g @google/gemini-cli
# put GEMINI_API_KEY=... in .env (the CLI loads it from the project root)
```

**Automatic change review (Stop hook)** — configured in `.claude/settings.json`. Every time Claude Code finishes a turn, `.claude/scripts/gemini_change_review.sh` runs in the background and asks Gemini to review all changes since the last commit (tracked diff vs `HEAD` plus untracked files).

- Output: `.claude/reviews/gemini-latest.md` (gitignored); failures go to `.claude/reviews/gemini-last-error.log`
- Model fallback: `gemini-3.8-flash` → `gemini-3.7-flash` → `gemini-3.1-pro-preview` → `gemini-pro-latest`. Override with `GEMINI_REVIEW_MODELS="model-a model-b"`
- Skips when there are no changes, when the diff is unchanged since the last review, or when a review is already running
- Never sends `.env*`, `*.pem`/`*.key`/`*.p12`, SQLite files or `db/` contents, at any depth
- Disable or edit via `/hooks` in Claude Code

**Plan review** — ask Claude Code to "use gemini-reviewer to review PLAN.md"; the agent writes `planning/REVIEW_GEMINI.md`.

## License

See [LICENSE](LICENSE).
