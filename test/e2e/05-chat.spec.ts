import { test, expect, Page } from "@playwright/test";
import { T, getPortfolio, krwOf, openApp } from "./helpers";

// Requires LLM_MOCK=true (PLAN §9 fixtures). Chat history persists (GET /api/chat/history), so
// assertions count messages relative to what is already on screen.
const PLAIN = "well-diversified";

const msgs = (page: Page, text: string | RegExp) => page.getByTestId(T.chatMessage).filter({ hasText: text });

async function openChat(page: Page) {
  // "networkidle" never fires while the SSE stream is open, so wait for the history fetch itself.
  const history = page
    .waitForResponse((r) => r.url().includes("/api/chat/history"), { timeout: 20_000 })
    .catch(() => null);
  await openApp(page);
  await expect(page.getByTestId(T.chatInput)).toBeVisible();
  await history;
  // Let persisted history render before counting.
  await page.waitForTimeout(300);
}

test.describe("AI chat (mocked)", () => {
  test("plain message returns the fixture and executes no trades", async ({ page, request }) => {
    const before = await getPortfolio(request);
    await openChat(page);
    const n0 = await msgs(page, PLAIN).count();

    await page.getByTestId(T.chatInput).fill("How does my portfolio look?");
    await page.getByTestId(T.chatSend).click();

    await expect(msgs(page, PLAIN)).toHaveCount(n0 + 1, { timeout: 20_000 });
    await expect(msgs(page, PLAIN).last()).toHaveAttribute("data-role", "assistant");
    await expect(page.getByTestId(T.chatLoading)).toHaveCount(0);

    const after = await getPortfolio(request);
    expect(after.cash_balance).toBe(before.cash_balance);
    expect(after.positions.map((p) => [p.ticker, p.quantity])).toEqual(before.positions.map((p) => [p.ticker, p.quantity]));
  });

  test("'buy' message auto-executes the trade fixture", async ({ page, request }) => {
    const before = await getPortfolio(request);
    const qtyBefore = before.positions.find((p) => p.ticker === "005930")?.quantity ?? 0;
    await openChat(page);
    const cash = page.getByTestId(T.headerCash);
    await expect.poll(() => krwOf(cash)).toBe(Math.round(before.cash_balance));
    const BUY = /Buying 1 share of 005930/;
    const n0 = await msgs(page, BUY).count();
    const okActions0 = await page.locator('[data-testid="chat-action"][data-success="true"]').count();
    const badActions0 = await page.locator('[data-testid="chat-action"][data-success="false"]').count();

    await page.getByTestId(T.chatInput).fill("Please buy some Samsung for me");
    const chatRes = page.waitForResponse((r) => r.url().endsWith("/api/chat") && r.request().method() === "POST");
    await page.getByTestId(T.chatSend).click();
    const body = await (await chatRes).json();
    expect(body.trades).toEqual([expect.objectContaining({ ticker: "005930", side: "buy", quantity: 1, success: true })]);
    expect(Number.isInteger(body.trades[0].price)).toBe(true);
    // NAVER is a seed ticker: chat treats the add as an idempotent success.
    expect(body.watchlist_changes).toEqual([expect.objectContaining({ ticker: "035420", action: "add", success: true })]);

    await expect(msgs(page, BUY)).toHaveCount(n0 + 1, { timeout: 20_000 });

    // Position for 005930 appears / grows by exactly 1, cash goes down.
    await expect(page.getByTestId(T.positionRow("005930"))).toBeVisible();
    await expect(page.getByTestId(T.positionQty("005930"))).toHaveText(new RegExp(`^\\s*${qtyBefore + 1}\\s*$`));
    const after = await getPortfolio(request);
    expect(after.positions.find((p) => p.ticker === "005930")?.quantity).toBe(qtyBefore + 1);
    expect(after.cash_balance).toBeLessThan(before.cash_balance);
    await expect.poll(() => krwOf(cash)).toBe(Math.round(after.cash_balance));

    // NAVER on the watchlist (UI + API).
    await expect(page.getByTestId(T.watchlistRow("035420"))).toBeVisible();
    const wl = await (await request.get("/api/watchlist")).json();
    expect(wl.map((x: { ticker: string }) => x.ticker)).toContain("035420");

    // Inline confirmations: two new successful actions (trade + watchlist), no new failures.
    await expect(page.locator('[data-testid="chat-action"][data-success="true"]')).toHaveCount(okActions0 + 2);
    await expect(page.locator('[data-testid="chat-action"][data-success="false"]')).toHaveCount(badActions0);
    const last = msgs(page, BUY).last();
    await expect(last.getByTestId(T.chatAction).filter({ hasText: "005930" })).toHaveAttribute("data-success", "true");
    await expect(last.getByTestId(T.chatAction).filter({ hasText: "035420" })).toHaveAttribute("data-success", "true");
  });

  test("user message is echoed, loading clears, and history survives reload", async ({ page, request }) => {
    const marker = `Summarise my risk ${Date.now()}`;
    await openChat(page);
    await page.getByTestId(T.chatInput).fill(marker);
    await page.getByTestId(T.chatSend).click();
    await expect(page.getByTestId(T.chatInput)).toHaveValue("");
    await expect(msgs(page, marker)).toHaveAttribute("data-role", "user");
    await expect(page.getByTestId(T.chatLoading)).toHaveCount(0, { timeout: 20_000 });

    const hist = await (await request.get("/api/chat/history")).json();
    expect(Array.isArray(hist)).toBe(true);
    const i = hist.findIndex((m: { content: string }) => m.content === marker);
    expect(i).toBeGreaterThanOrEqual(0);
    expect(hist[i]).toMatchObject({ role: "user" });
    expect(hist[i + 1]).toMatchObject({ role: "assistant" });
    expect(hist[i + 1].content).toContain(PLAIN);
    for (const k of ["id", "created_at"]) expect(typeof hist[i][k]).toBe("string");
    expect(Array.isArray(hist[i + 1].trades)).toBe(true);
    expect(Array.isArray(hist[i + 1].watchlist_changes)).toBe(true);

    await page.reload();
    await expect(msgs(page, marker)).toBeVisible({ timeout: 20_000 });
  });
});
