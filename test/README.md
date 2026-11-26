# FinAlly E2E tests (Playwright)

Playwright `@playwright/test` **1.56.0** (pinned; matches the `mcr.microsoft.com/playwright:v1.56.0-noble` image).
Specs live in `e2e/`; every `data-testid` used is centralised in `e2e/helpers.ts` (`T`) and mirrors
`planning/FRONTEND_TESTIDS.md`.

The app must run with `LLM_MOCK=true` (chat fixtures, PLAN §9) and the simulator (`USE_YFINANCE=false`);
`SIM_SEED=42` makes prices reproducible. Specs are written relative to observed state (they read
`/api/portfolio` before acting and clean up after), so they tolerate a non-empty DB — but the
"₩10,000,000" fresh-start assertion is only enforced on a fresh DB.

## Option A — full stack in Docker (CI-style)

From the repo root:

```bash
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
docker compose -f test/docker-compose.test.yml down -v
```

`app` is built from the root `Dockerfile` with a tmpfs DB (fresh every run); `playwright` waits for
`/api/health` to be healthy and runs against `BASE_URL=http://app:8000`. The HTML report is written to
`test/playwright-report/`.

## Option B — locally against a running backend (fastest loop)

```bash
# 1. build the frontend and hand it to the backend
cd frontend && npm install && npm run build && cd ..
rm -rf backend/static && cp -R frontend/out backend/static

# 2. start the backend with a throwaway DB
cd backend
LLM_MOCK=true SIM_SEED=42 DB_PATH="$TMPDIR/finally-e2e.db" \
  UV_CACHE_DIR="$TMPDIR/uv-cache" uv run uvicorn app.main:app --port 8000 --workers 1

# 3. in another shell
cd test && npm install && npx playwright install chromium
npx playwright test                 # all
npx playwright test e2e/03-trading  # one file
npx playwright show-report          # traces/screenshots of failures
```

Use `BASE_URL=http://host:port npx playwright test` to target another server.

## Scenarios

| File | Covers |
|---|---|
| `00-api.spec.ts` | PLAN §8 shapes + 400/404/409/422, SSE event shape |
| `01-fresh-start.spec.ts` | 10 default tickers, ₩10,000,000, prices streaming, ticker selection |
| `02-watchlist.spec.ts` | add + remove a ticker (247540 EcoPro BM) |
| `03-trading.spec.ts` | buy, partial/full sell (row removed at 0), insufficient shares |
| `04-portfolio-viz.spec.ts` | heatmap tiles (sized by weight, coloured by P&L), P&L chart |
| `05-chat.spec.ts` | mocked chat: plain fixture (no trades), "buy" fixture (005930 + NAVER) |
| `06-sse-resilience.spec.ts` | stream dropped/offline → indicator → recovery, prices resume |
