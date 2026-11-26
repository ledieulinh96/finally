# E2E Report

Owner: `tester`. Suite: `test/` (Playwright 1.56.0, Chromium, `workers: 1`). Env: `LLM_MOCK=true`, `SIM_SEED=42`.

## Status — 2026-11-26 (final)

**22/22 pass locally and 22/22 pass in Docker compose.**

- Local: image `finally:latest` run as `finally-e2e` on host port 8019, tmpfs DB (fresh), `BASE_URL=http://localhost:8019`.
- Docker: `docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright` → exit 0; then `down -v`.

| Scenario | Spec | Local | Docker |
|---|---|---|---|
| API contract (§8 shapes, 400/404/409/422, SSE shape) | 00-api | PASS (9/9) | PASS (9/9) |
| Fresh start (10 tickers, ₩10,000,000, streaming, ticker selects chart) | 01-fresh-start | PASS (2/2) | PASS (2/2) |
| Add + remove ticker | 02-watchlist | PASS | PASS |
| Buy | 03-trading | PASS | PASS |
| Sell (partial, full → row removed) + oversell rejected | 03-trading | PASS (2/2) | PASS (2/2) |
| Heatmap + P&L chart | 04-portfolio-viz | PASS | PASS |
| Chat mocked (plain, no trades) | 05-chat | PASS | PASS |
| Chat mocked ("buy": 005930 bought, NAVER add `success: true`) | 05-chat | PASS | PASS |
| Chat history: `GET /api/chat/history` shape + restored after reload | 05-chat | PASS | PASS |
| SSE: stream drop → indicator → recovery, prices resume | 06-sse-resilience | PASS | PASS |
| SSE: server-side stream end → reconnect | 06-sse-resilience | PASS | PASS |
| SSE: HTTP 503 (fatal, EventSource CLOSED) → app-level backoff reconnect | 06-sse-resilience | PASS | PASS |

## Bugs

| # | Description | Owner | Status |
|---|---|---|---|
| 1 | SSE did not recover after a non-200 stream response (EventSource CLOSED) | frontend | FIXED (1 s→10 s backoff), verified by 06 #3 |
| 2 | Chat history lost on reload | frontend + backend | FIXED (`GET /api/chat/history`), verified by 05 #3 |
| 3 | Test bug: `05-chat` waited for `networkidle`, which never fires while SSE is open → 45 s timeout on all 3 chat tests | tester | FIXED (wait for the `/api/chat/history` response instead) |

No open app bugs.
