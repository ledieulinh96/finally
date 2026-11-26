import { test, expect } from "@playwright/test";
import { T, ensureNotWatched, openApp } from "./helpers";

// 247540 = EcoPro BM (KOSDAQ) — not in the default watchlist.
const TICKER = "247540";

test.describe("watchlist", () => {
  test("add and remove a ticker", async ({ page, request }) => {
    await ensureNotWatched(request, TICKER);
    await openApp(page);
    await expect(page.getByTestId(T.watchlistRow(TICKER))).toHaveCount(0);

    await page.getByTestId(T.watchlistAddInput).fill(TICKER);
    await page.getByTestId(T.watchlistAddButton).click();

    const row = page.getByTestId(T.watchlistRow(TICKER));
    await expect(row).toBeVisible();
    await expect(row).toContainText(/EcoPro/i);
    await expect(page.getByTestId(T.watchlistPrice(TICKER))).toHaveText(/^₩[\d,]+$/, { timeout: 15_000 });

    // Persisted on the backend.
    const list = await (await request.get("/api/watchlist")).json();
    expect(list.map((x: { ticker: string }) => x.ticker)).toContain(TICKER);

    // Survives a reload.
    await page.reload();
    await expect(page.getByTestId(T.watchlistRow(TICKER))).toBeVisible({ timeout: 20_000 });

    // Remove it.
    await page.getByTestId(T.watchlistRemove(TICKER)).click();
    await expect(page.getByTestId(T.watchlistRow(TICKER))).toHaveCount(0);
    const after = await (await request.get("/api/watchlist")).json();
    expect(after.map((x: { ticker: string }) => x.ticker)).not.toContain(TICKER);

    await page.reload();
    await expect(page.getByTestId(T.watchlistRow("005930"))).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId(T.watchlistRow(TICKER))).toHaveCount(0);
  });
});
