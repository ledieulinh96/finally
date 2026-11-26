import { test, expect } from "@playwright/test";
import { DEFAULT_TICKERS, ensureNotWatched, flatten, getPortfolio } from "./helpers";

// PLAN §8 response shapes and error conventions.
test.describe("REST API contract", () => {
  test("GET /api/health", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.status()).toBe(200);
    const b = await res.json();
    expect(b).toMatchObject({ status: "ok", source: "simulator" });
    expect(["ok", "degraded", "stopped"]).toContain(b.market_data);
    expect(typeof b.tickers).toBe("number");
    expect(b.tickers).toBeGreaterThanOrEqual(10);
    expect(["pre_open", "regular", "closing_auction", "after_hours", "closed"]).toContain(b.market_session);
  });

  test("GET /api/watchlist shape", async ({ request }) => {
    const res = await request.get("/api/watchlist");
    expect(res.status()).toBe(200);
    const list = await res.json();
    expect(Array.isArray(list)).toBe(true);
    const tickers = list.map((x: any) => x.ticker);
    for (const t of DEFAULT_TICKERS) expect(tickers).toContain(t);
    const s = list.find((x: any) => x.ticker === "005930");
    expect(s.name).toBe("Samsung Electronics");
    for (const k of ["price", "prev_price", "session_open"]) {
      expect(Number.isInteger(s[k]), `${k}=${s[k]}`).toBe(true);
    }
    expect(typeof s.session_change_pct).toBe("number");
    expect(["up", "down", "flat"]).toContain(s.direction);
  });

  test("watchlist add / duplicate / remove / errors", async ({ request }) => {
    const T = "247540";
    await ensureNotWatched(request, T);

    const add = await request.post("/api/watchlist", { data: { ticker: T } });
    expect(add.status()).toBe(201);
    const a = await add.json();
    expect(a.ticker).toBe(T);
    expect(a.name).toMatch(/EcoPro/i);
    expect(a.price === null || Number.isInteger(a.price)).toBe(true);

    // Duplicate → 409; suffix/whitespace normalisation applies before the check.
    expect((await request.post("/api/watchlist", { data: { ticker: T } })).status()).toBe(409);
    expect((await request.post("/api/watchlist", { data: { ticker: ` ${T}.KQ ` } })).status()).toBe(409);

    const del = await request.delete(`/api/watchlist/${T}`);
    expect(del.status()).toBe(200);
    expect(await del.json()).toMatchObject({ ticker: T, removed: true });
    // Delete of a ticker not on the watchlist → 404.
    const gone = await request.delete(`/api/watchlist/${T}`);
    expect(gone.status()).toBe(404);
    expect(await gone.json()).toHaveProperty("detail");

    // Malformed ticker → 422.
    const bad = await request.post("/api/watchlist", { data: { ticker: "SAMSUNG!" } });
    expect(bad.status()).toBe(422);
    expect(await bad.json()).toHaveProperty("detail");
    expect((await request.post("/api/watchlist", { data: {} })).status()).toBe(422);
    expect((await request.delete("/api/watchlist/BAD!!")).status()).toBe(422);
  });

  test("GET /api/portfolio shape", async ({ request }) => {
    const p = await getPortfolio(request);
    expect(typeof p.cash_balance).toBe("number");
    expect(typeof p.total_value).toBe("number");
    expect(Array.isArray(p.positions)).toBe(true);
  });

  test("trade buy/sell happy path and response shape", async ({ request }) => {
    const T = "000660";
    await flatten(request, T);
    const before = await getPortfolio(request);

    const buy = await request.post("/api/portfolio/trade", { data: { ticker: T, side: "buy", quantity: 2 } });
    expect(buy.status()).toBe(200);
    const b = await buy.json();
    expect(b).toMatchObject({ success: true, ticker: T, side: "buy", quantity: 2 });
    expect(Number.isInteger(b.price)).toBe(true);
    expect(b.price).toBeGreaterThan(0);
    expect(b.cash_balance).toBeCloseTo(before.cash_balance - 2 * b.price, 0);

    const p = await getPortfolio(request);
    const pos = p.positions.find((x) => x.ticker === T)!;
    expect(pos).toMatchObject({ ticker: T, name: "SK Hynix", quantity: 2, avg_cost: b.price });
    for (const k of ["current_price", "market_value", "unrealized_pnl", "pnl_pct"] as const) {
      expect(typeof pos[k]).toBe("number");
    }
    expect(pos.market_value).toBeCloseTo(pos.quantity * pos.current_price, 0);
    expect(pos.unrealized_pnl).toBeCloseTo((pos.current_price - pos.avg_cost) * pos.quantity, 0);
    const mv = p.positions.reduce((s, x) => s + x.market_value, 0);
    expect(p.total_value).toBeCloseTo(p.cash_balance + mv, -1);

    // Weighted average cost on a second buy.
    const buy2 = await (await request.post("/api/portfolio/trade", { data: { ticker: T, side: "buy", quantity: 1 } })).json();
    const p2 = await getPortfolio(request);
    const pos2 = p2.positions.find((x) => x.ticker === T)!;
    expect(pos2.quantity).toBe(3);
    expect(pos2.avg_cost).toBeCloseTo((2 * b.price + buy2.price) / 3, 2);

    const sell = await request.post("/api/portfolio/trade", { data: { ticker: T, side: "sell", quantity: 3 } });
    expect(sell.status()).toBe(200);
    expect(await sell.json()).toMatchObject({ success: true, side: "sell", quantity: 3 });
    expect((await getPortfolio(request)).positions.find((x) => x.ticker === T)).toBeUndefined();

    // History has snapshots, read-only and well-formed.
    const hist = await (await request.get("/api/portfolio/history")).json();
    expect(hist.length).toBeGreaterThanOrEqual(1);
    expect(typeof hist[0].total_value).toBe("number");
    expect(typeof hist[0].recorded_at).toBe("string");
  });

  test("trade business-rule failures → 400 {success:false,error}", async ({ request }) => {
    await flatten(request, "005490");
    const cases: [object, RegExp][] = [
      [{ ticker: "005490", side: "sell", quantity: 1 }, /Insufficient shares/],
      [{ ticker: "207940", side: "buy", quantity: 1_000_000 }, /Insufficient cash/],
    ];
    for (const [data, err] of cases) {
      const res = await request.post("/api/portfolio/trade", { data });
      expect(res.status(), JSON.stringify(data)).toBe(400);
      const b = await res.json();
      expect(b.success).toBe(false);
      expect(b.error).toMatch(err);
    }
  });

  test("trade malformed bodies → 422 (or 400 Invalid ticker)", async ({ request }) => {
    for (const data of [
      { ticker: "005930", side: "buy", quantity: 1.5 },
      { ticker: "005930", side: "buy", quantity: 0 },
      { ticker: "005930", side: "buy", quantity: -1 },
      { ticker: "005930", side: "hold", quantity: 1 },
      { ticker: "005930", side: "buy" },
    ]) {
      const res = await request.post("/api/portfolio/trade", { data });
      expect(res.status(), JSON.stringify(data)).toBe(422);
    }
    const res = await request.post("/api/portfolio/trade", { data: { ticker: "NOT-A-TICKER", side: "buy", quantity: 1 } });
    expect([400, 422]).toContain(res.status());
    if (res.status() === 400) expect((await res.json()).error).toMatch(/Invalid ticker/);
  });

  test("chat validation and mock response shape", async ({ request }) => {
    const long = await request.post("/api/chat", { data: { message: "x".repeat(2001) } });
    expect(long.status()).toBe(422);

    const res = await request.post("/api/chat", { data: { message: "hello" } });
    expect(res.status()).toBe(200);
    const b = await res.json();
    expect(b.message).toContain("well-diversified");
    expect(b.trades).toEqual([]);
    expect(b.watchlist_changes).toEqual([]);
  });

  test("SSE stream sends snapshot events with PLAN §6 shape", async ({ request, baseURL }) => {
    // Read the first chunk of the stream with fetch + AbortController (request API would wait forever).
    const ctrl = new AbortController();
    const res = await fetch(`${baseURL}/api/stream/prices`, { signal: ctrl.signal });
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    const reader = res.body!.getReader();
    let text = "";
    const deadline = Date.now() + 10_000;
    while (Date.now() < deadline && (text.match(/^data:/gm)?.length ?? 0) < 10) {
      const { value, done } = await reader.read();
      if (done) break;
      text += new TextDecoder().decode(value);
    }
    ctrl.abort();
    expect(text).toMatch(/^id: ?\d+/m);
    const events = [...text.matchAll(/^data: ?(.*)$/gm)].map((m) => JSON.parse(m[1]));
    expect(events.length).toBeGreaterThanOrEqual(10);
    const e = events.find((x) => x.ticker === "005930");
    expect(e).toBeTruthy();
    expect(e).toMatchObject({ ticker: "005930", name: "Samsung Electronics" });
    for (const k of ["price", "prev_price", "session_open"]) expect(Number.isInteger(e[k])).toBe(true);
    expect(["up", "down", "flat"]).toContain(e.direction);
    expect(typeof e.session_change_pct).toBe("number");
    expect(typeof e.timestamp).toBe("string");
    void request;
  });
});
