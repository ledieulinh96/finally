import { test, expect, Page } from "@playwright/test";
import { T, expectConnected, expectSomePriceChanges, openApp, watchlistPrices } from "./helpers";

const STREAM = "**/api/stream/prices**";

/**
 * Chromium's offline emulation does not cut an already-open EventSource, so the live connection
 * is made finite instead: the first stream request is answered with a real-shaped snapshot that
 * then ends (server drop). Subsequent attempts are refused while "down", then let through.
 */
async function snapshotBody(page: Page): Promise<string> {
  const res = await page.request.get("/api/watchlist");
  const list: Array<Record<string, unknown>> = await res.json();
  return (
    "retry: 500\n\n" +
    list
      .filter((w) => w.price !== null)
      .map((w, i) => `id: ${i + 1}\ndata: ${JSON.stringify({ ...w, timestamp: new Date().toISOString() })}\n\n`)
      .join("")
  );
}

test.describe("SSE resilience", () => {
  test("stream drops, indicator leaves 'connected', then recovers and prices resume", async ({ page }) => {
    const body = await snapshotBody(page);
    let down = true;
    let attempts = 0;
    await page.route(STREAM, async (route) => {
      attempts += 1;
      if (attempts === 1) return route.fulfill({ status: 200, contentType: "text/event-stream", body });
      if (down) return route.abort("connectionrefused");
      return route.continue();
    });

    await openApp(page);
    const dot = page.getByTestId(T.connection);
    // The finite stream ends → browser reconnect attempts are refused → not connected.
    await expect(dot).toHaveAttribute("data-status", /^(reconnecting|disconnected)$/, { timeout: 15_000 });
    await expect.poll(() => attempts, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
    // Stays down while the server is unreachable.
    await page.waitForTimeout(2_000);
    await expect(dot).not.toHaveAttribute("data-status", "connected");

    // Server comes back.
    down = false;
    await expectConnected(page, 30_000);
    const before = await watchlistPrices(page);
    await expectSomePriceChanges(page, before);
  });

  test("server-side stream end triggers reconnect", async ({ page }) => {
    let hits = 0;
    await page.route(STREAM, async (route) => {
      hits += 1;
      if (hits === 1) return route.fulfill({ status: 200, contentType: "text/event-stream", body: "retry: 500\n\n" });
      return route.continue();
    });
    await openApp(page);
    await expectConnected(page, 30_000);
    expect(hits).toBeGreaterThanOrEqual(2);
    const before = await watchlistPrices(page);
    await expectSomePriceChanges(page, before);
  });

  test("HTTP error from the stream (e.g. 503 during restart) is recovered from", async ({ page }) => {
    // A non-200 response puts EventSource into CLOSED (no native retry); the app must reconnect itself.
    let hits = 0;
    await page.route(STREAM, async (route) => {
      hits += 1;
      if (hits === 1) return route.fulfill({ status: 503, body: "Service Unavailable" });
      return route.continue();
    });
    await page.goto("/");
    await expect(page.getByTestId(T.connection)).toHaveAttribute("data-status", "disconnected", { timeout: 15_000 });
    await expectConnected(page, 30_000);
    const before = await watchlistPrices(page);
    await expectSomePriceChanges(page, before);
  });
});
