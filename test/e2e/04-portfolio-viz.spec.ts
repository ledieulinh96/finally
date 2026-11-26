import { test, expect } from "@playwright/test";
import { T, apiTrade, flatten, getPortfolio, openApp } from "./helpers";

test.describe("portfolio visualisation", () => {
  test("heatmap tiles and P&L chart render with data", async ({ page, request }) => {
    const A = "068270"; // Celltrion
    const B = "005380"; // Hyundai Motor
    await apiTrade(request, A, "buy", 2);
    await apiTrade(request, B, "buy", 1);

    // Trades record snapshots, so history must have data.
    const hist = await (await request.get("/api/portfolio/history")).json();
    expect(Array.isArray(hist)).toBe(true);
    expect(hist.length).toBeGreaterThanOrEqual(1);

    await openApp(page);

    const heatmap = page.getByTestId(T.heatmap);
    await expect(heatmap).toBeVisible();
    const portfolio = await getPortfolio(request);
    for (const pos of portfolio.positions) {
      const tile = page.getByTestId(T.heatmapTile(pos.ticker));
      await expect(tile).toBeVisible();
      // Colour class reflects P&L sign (re-read: prices move between calls).
      await expect(tile).toHaveAttribute("data-pnl", /^(profit|loss|flat)$/);
    }
    // Tiles are sized by weight: the bigger position has the bigger tile.
    const [big, small] = [...portfolio.positions].sort((x, y) => y.market_value - x.market_value);
    if (big && small && big.market_value > small.market_value * 1.5) {
      const bb = await page.getByTestId(T.heatmapTile(big.ticker)).boundingBox();
      const sb = await page.getByTestId(T.heatmapTile(small.ticker)).boundingBox();
      expect(bb!.width * bb!.height).toBeGreaterThan(sb!.width * sb!.height);
    }

    // Colour check: the data-pnl attribute must agree with the tile's computed colour hue.
    const colours = await page.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>('[data-testid^="heatmap-cell-"]')].map((el) => {
        // Colour may be a CSS background (div treemap) or an SVG fill (rect, or a rect child).
        const cs = getComputedStyle(el);
        const target = el.querySelector("rect") ?? el;
        const candidates = [cs.backgroundColor, cs.fill, getComputedStyle(target).fill, getComputedStyle(target).backgroundColor];
        const colour = candidates.find((c) => c && /rgb/.test(c) && !/rgba\(0, 0, 0, 0\)/.test(c)) ?? "rgb(0,0,0)";
        const m = colour.match(/\d+(\.\d+)?/g)!.map(Number);
        return { pnl: el.dataset.pnl, r: m[0], g: m[1] };
      }),
    );
    for (const c of colours) {
      if (c.pnl === "profit") expect(c.g, JSON.stringify(c)).toBeGreaterThan(c.r);
      if (c.pnl === "loss") expect(c.r, JSON.stringify(c)).toBeGreaterThan(c.g);
    }

    const chart = page.getByTestId(T.pnlChart);
    await expect(chart).toBeVisible();
    await expect(chart.locator("canvas, svg").first()).toBeVisible();
    await expect.poll(async () => Number(await chart.getAttribute("data-points"))).toBeGreaterThanOrEqual(1);
    const box = await chart.boundingBox();
    expect(box!.height).toBeGreaterThan(50);

    await flatten(request, A);
    await flatten(request, B);
  });
});
