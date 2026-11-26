import { APIRequestContext, Locator, Page, expect } from "@playwright/test";

/**
 * Single place for every data-testid the suite relies on.
 * Keep in sync with planning/FRONTEND_TESTIDS.md.
 */
export const T = {
  headerTotal: "header-total-value",
  headerCash: "header-cash",
  connection: "connection-status",
  watchlistRow: (t: string) => `watchlist-row-${t}`,
  watchlistPrice: (t: string) => `watchlist-price-${t}`,
  watchlistChange: (t: string) => `watchlist-change-${t}`,
  watchlistError: "watchlist-error",
  watchlistRemove: (t: string) => `watchlist-remove-${t}`,
  watchlistAddInput: "watchlist-add-input",
  watchlistAddButton: "watchlist-add-button",
  tradeTicker: "trade-ticker-input",
  tradeQuantity: "trade-quantity-input",
  tradeBuy: "trade-buy-button",
  tradeSell: "trade-sell-button",
  tradeMessage: "trade-message",
  positionRow: (t: string) => `position-row-${t}`,
  positionQty: (t: string) => `position-qty-${t}`,
  positionsEmpty: "positions-empty",
  heatmap: "heatmap",
  heatmapTile: (t: string) => `heatmap-cell-${t}`,
  pnlChart: "pnl-chart",
  mainChart: "main-chart",
  chatInput: "chat-input",
  chatSend: "chat-send",
  chatLoading: "chat-loading",
  chatMessage: "chat-message",
  chatAction: "chat-action",
};

export const DEFAULT_TICKERS = [
  "005930", "000660", "035420", "035720", "005380",
  "373220", "207940", "068270", "000270", "005490",
];

/** "₩10,000,000" / "-₩1,234" / "₩ 75,400" → number. */
export function parseKRW(text: string | null | undefined): number {
  if (!text) return NaN;
  const neg = /^\s*[-−]/.test(text) || /\(\s*₩/.test(text);
  const digits = text.replace(/[^0-9.]/g, "");
  if (!digits) return NaN;
  const n = Number(digits);
  return neg ? -n : n;
}

export async function krwOf(locator: Locator): Promise<number> {
  return parseKRW(await locator.innerText());
}

export function formatKRW(n: number): string {
  return "₩" + Math.round(n).toLocaleString("en-US");
}

export type Position = {
  ticker: string; name: string; quantity: number; avg_cost: number;
  current_price: number; market_value: number; unrealized_pnl: number; pnl_pct: number;
};
export type Portfolio = { cash_balance: number; total_value: number; positions: Position[] };

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function apiTrade(request: APIRequestContext, ticker: string, side: "buy" | "sell", quantity: number) {
  const res = await request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
  const body = await res.json();
  expect(res.status(), JSON.stringify(body)).toBe(200);
  expect(body.success).toBe(true);
  return body;
}

/** Sell any holding of `ticker` so a test starts flat in it. */
export async function flatten(request: APIRequestContext, ticker: string) {
  const p = await getPortfolio(request);
  const pos = p.positions.find((x) => x.ticker === ticker);
  if (pos && pos.quantity > 0) await apiTrade(request, ticker, "sell", pos.quantity);
}

export async function ensureNotWatched(request: APIRequestContext, ticker: string) {
  const res = await request.delete(`/api/watchlist/${ticker}`);
  expect([200, 204, 404]).toContain(res.status());
}

export async function openApp(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId(T.watchlistRow("005930"))).toBeVisible({ timeout: 20_000 });
}

export async function expectConnected(page: Page, timeout = 15_000) {
  await expect(page.getByTestId(T.connection)).toHaveAttribute("data-status", "connected", { timeout });
}

/** Snapshot of every watchlist price cell currently shown. */
export async function watchlistPrices(page: Page): Promise<Record<string, string>> {
  return page.evaluate(() => {
    const out: Record<string, string> = {};
    document.querySelectorAll<HTMLElement>('[data-testid^="watchlist-price-"]').forEach((cell) => {
      out[cell.dataset.testid!.replace("watchlist-price-", "")] = cell.innerText.trim();
    });
    return out;
  });
}

/** Wait until at least one watchlist price differs from `before`. */
export async function expectSomePriceChanges(page: Page, before: Record<string, string>, timeout = 20_000) {
  await expect
    .poll(async () => {
      const now = await watchlistPrices(page);
      return Object.keys(now).some((k) => before[k] !== undefined && now[k] !== "" && now[k] !== before[k]);
    }, { timeout, message: "expected at least one watchlist price to change" })
    .toBe(true);
}
