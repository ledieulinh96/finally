import { test, expect } from "@playwright/test";
import { T, apiTrade, flatten, getPortfolio, krwOf, openApp } from "./helpers";

test.describe("trading", () => {
  test("buy shares: cash decreases and position appears", async ({ page, request }) => {
    const TICKER = "000270"; // Kia
    await flatten(request, TICKER);
    await openApp(page);
    await expect(page.getByTestId(T.positionRow(TICKER))).toHaveCount(0);

    const cash = page.getByTestId(T.headerCash);
    const cashBefore = (await getPortfolio(request)).cash_balance;
    await expect.poll(() => krwOf(cash)).toBe(Math.round(cashBefore));

    await page.getByTestId(T.tradeTicker).fill(TICKER);
    await page.getByTestId(T.tradeQuantity).fill("3");
    await page.getByTestId(T.tradeBuy).click();

    const row = page.getByTestId(T.positionRow(TICKER));
    await expect(row).toBeVisible();
    await expect(page.getByTestId(T.positionQty(TICKER))).toHaveText(/^\s*3\s*$/);

    const after = await getPortfolio(request);
    const pos = after.positions.find((p) => p.ticker === TICKER)!;
    expect(pos.quantity).toBe(3);
    expect(after.cash_balance).toBeCloseTo(cashBefore - 3 * pos.avg_cost, 0);
    await expect.poll(() => krwOf(cash)).toBe(Math.round(after.cash_balance));
    expect(after.cash_balance).toBeLessThan(cashBefore);

    await flatten(request, TICKER); // cleanup
  });

  test("sell shares: cash increases, partial sell updates row, full sell removes it", async ({ page, request }) => {
    const TICKER = "035720"; // Kakao
    await flatten(request, TICKER);
    await apiTrade(request, TICKER, "buy", 4);
    await openApp(page);

    const row = page.getByTestId(T.positionRow(TICKER));
    await expect(page.getByTestId(T.positionQty(TICKER))).toHaveText(/^\s*4\s*$/);

    const cash = page.getByTestId(T.headerCash);
    const c0 = (await getPortfolio(request)).cash_balance;
    await expect.poll(() => krwOf(cash)).toBe(Math.round(c0));

    // Partial sell.
    await page.getByTestId(T.tradeTicker).fill(TICKER);
    await page.getByTestId(T.tradeQuantity).fill("1");
    await page.getByTestId(T.tradeSell).click();
    await expect(page.getByTestId(T.positionQty(TICKER))).toHaveText(/^\s*3\s*$/);
    const c1 = (await getPortfolio(request)).cash_balance;
    expect(c1).toBeGreaterThan(c0);
    await expect.poll(() => krwOf(cash)).toBe(Math.round(c1));

    // Full sell → row disappears.
    await page.getByTestId(T.tradeQuantity).fill("3");
    await page.getByTestId(T.tradeSell).click();
    await expect(row).toHaveCount(0);
    const p2 = await getPortfolio(request);
    expect(p2.positions.find((p) => p.ticker === TICKER)).toBeUndefined();
    expect(p2.cash_balance).toBeGreaterThan(c1);
    await expect.poll(() => krwOf(cash)).toBe(Math.round(p2.cash_balance));
  });

  test("selling more than owned is rejected and changes nothing", async ({ page, request }) => {
    const TICKER = "005490"; // POSCO Holdings
    await flatten(request, TICKER);
    const before = await getPortfolio(request);
    await openApp(page);
    await page.getByTestId(T.tradeTicker).fill(TICKER);
    await page.getByTestId(T.tradeQuantity).fill("1");
    await page.getByTestId(T.tradeSell).click();
    const msg = page.getByTestId(T.tradeMessage);
    await expect(msg).toHaveAttribute("data-status", "error");
    await expect(msg).toContainText("Insufficient shares");
    const after = await getPortfolio(request);
    expect(after.cash_balance).toBe(before.cash_balance);
    await expect(page.getByTestId(T.positionRow(TICKER))).toHaveCount(0);
  });
});
