import { test, expect } from "@playwright/test";
import { DEFAULT_TICKERS, T, expectConnected, expectSomePriceChanges, getPortfolio, krwOf, openApp, parseKRW, watchlistPrices } from "./helpers";

test.describe("fresh start", () => {
  test("default watchlist, cash balance and streaming prices", async ({ page, request }) => {
    await openApp(page);

    // All 10 default KOSPI tickers are present.
    for (const t of DEFAULT_TICKERS) {
      await expect(page.getByTestId(T.watchlistRow(t))).toBeVisible();
    }

    // Header cash matches the backend; on a fresh DB it is exactly ₩10,000,000.
    const portfolio = await getPortfolio(request);
    const cash = page.getByTestId(T.headerCash);
    await expect(cash).toContainText("₩");
    await expect.poll(() => krwOf(cash)).toBe(Math.round(portfolio.cash_balance));
    if (portfolio.positions.length === 0 && portfolio.cash_balance === 10_000_000) {
      await expect(cash).toContainText("₩10,000,000");
      await expect.poll(async () => parseKRW(await page.getByTestId(T.headerTotal).innerText())).toBe(10_000_000);
    }

    // Prices formatted as ₩ integers, connection is live, and prices move.
    await expectConnected(page);
    await expect
      .poll(async () => Object.values(await watchlistPrices(page)).filter((v) => /^₩[\d,]+$/.test(v)).length, {
        message: "every default ticker should show a ₩ price",
      })
      .toBeGreaterThanOrEqual(10);
    const before = await watchlistPrices(page);
    await expectSomePriceChanges(page, before);
  });

  test("clicking a ticker selects it in the main chart", async ({ page }) => {
    await openApp(page);
    await page.getByTestId(T.watchlistRow("000660")).click();
    await expect(page.getByTestId(T.mainChart)).toHaveAttribute("data-ticker", "000660");
  });
});
