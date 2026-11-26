import { livePortfolio, pnlColor, squarify } from "@/lib/portfolio";
import { buildPnlSeries } from "@/components/PnlChart";
import { appendPoint } from "@/hooks/usePriceStream";
import type { Portfolio } from "@/lib/types";

const portfolio: Portfolio = {
  cash_balance: 8_500_000,
  total_value: 10_200_000,
  positions: [
    { ticker: "005930", name: "Samsung Electronics", quantity: 10, avg_cost: 74000, current_price: 75400, market_value: 754000, unrealized_pnl: 14000, pnl_pct: 1.89 },
    { ticker: "000660", name: "SK Hynix", quantity: 2, avg_cost: 180000, current_price: 180000, market_value: 360000, unrealized_pnl: 0, pnl_pct: 0 },
  ],
};

describe("livePortfolio", () => {
  it("returns null without data", () => {
    expect(livePortfolio(null, {})).toBeNull();
  });

  it("uses REST prices when no live price is known", () => {
    const lp = livePortfolio(portfolio, {})!;
    expect(lp.totalValue).toBe(8_500_000 + 754_000 + 360_000);
    expect(lp.unrealizedPnl).toBe(14000);
    expect(lp.positions[0].pnl_pct).toBe(1.89);
  });

  it("re-prices positions from the stream", () => {
    const lp = livePortfolio(portfolio, {
      "000660": { price: 171000, prev_price: 180000, session_open: 180000, session_change_pct: -5, direction: "down", name: "SK Hynix" },
    })!;
    const hynix = lp.positions.find((p) => p.ticker === "000660")!;
    expect(hynix.current_price).toBe(171000);
    expect(hynix.market_value).toBe(342000);
    expect(hynix.unrealized_pnl).toBe(-18000);
    expect(hynix.pnl_pct).toBe(-5);
    expect(lp.totalValue).toBe(8_500_000 + 754_000 + 342_000);
    expect(lp.unrealizedPnl).toBe(14000 - 18000);
  });
});

describe("squarify", () => {
  it("tiles the bounds with areas proportional to value", () => {
    const cells = squarify(
      [
        { item: "a", value: 6 },
        { item: "b", value: 3 },
        { item: "c", value: 1 },
        { item: "zero", value: 0 },
      ],
      { x: 0, y: 0, w: 100, h: 50 },
    );
    expect(cells.map((c) => c.item)).toEqual(["a", "b", "c"]);
    const area = (i: number) => cells[i].rect.w * cells[i].rect.h;
    expect(area(0) + area(1) + area(2)).toBeCloseTo(5000);
    expect(area(0)).toBeCloseTo(3000);
    expect(area(2)).toBeCloseTo(500);
    for (const c of cells) {
      expect(c.rect.x).toBeGreaterThanOrEqual(-1e-9);
      expect(c.rect.x + c.rect.w).toBeLessThanOrEqual(100 + 1e-9);
      expect(c.rect.y + c.rect.h).toBeLessThanOrEqual(50 + 1e-9);
    }
  });

  it("returns nothing for empty input", () => {
    expect(squarify([], { x: 0, y: 0, w: 10, h: 10 })).toEqual([]);
  });
});

describe("pnlColor", () => {
  it("is green for profit, red for loss, neutral at zero", () => {
    const [r1, g1] = pnlColor(3).match(/\d+/g)!.map(Number);
    expect(g1).toBeGreaterThan(r1);
    const [r2, g2] = pnlColor(-3).match(/\d+/g)!.map(Number);
    expect(r2).toBeGreaterThan(g2);
    expect(pnlColor(0)).toBe("rgb(52, 60, 82)");
  });
});

describe("chart series helpers", () => {
  it("collapses same-second points and caps length", () => {
    let s = appendPoint([], { time: 1, value: 10 });
    s = appendPoint(s, { time: 1, value: 11 });
    s = appendPoint(s, { time: 2, value: 12 });
    expect(s).toEqual([
      { time: 1, value: 11 },
      { time: 2, value: 12 },
    ]);
    expect(appendPoint(s, { time: 3, value: 13 }, 2)).toEqual([
      { time: 2, value: 12 },
      { time: 3, value: 13 },
    ]);
  });

  it("sorts snapshots and appends the live total", () => {
    const pts = buildPnlSeries(
      [
        { total_value: 10_200_000, recorded_at: "2026-11-13T09:30:00Z" },
        { total_value: 10_000_000, recorded_at: "2026-11-13T09:00:00Z" },
      ],
      10_300_000,
      Date.parse("2026-11-13T10:00:00Z"),
    );
    expect(pts.map((p) => p.value)).toEqual([10_000_000, 10_200_000, 10_300_000]);
    expect(pts[2].time).toBe(Date.parse("2026-11-13T10:00:00Z") / 1000);
  });
});
