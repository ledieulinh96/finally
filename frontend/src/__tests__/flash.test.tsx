import { act, render, screen } from "@testing-library/react";
import { WatchlistRow } from "@/components/Watchlist";
import type { WatchlistItem } from "@/lib/types";

const item: WatchlistItem = {
  ticker: "005930",
  name: "Samsung Electronics",
  price: 75000,
  prev_price: 75000,
  session_open: 75000,
  session_change_pct: 0,
  direction: "flat",
};

function renderRow(price: number) {
  return (
    <ul>
      <WatchlistRow
        item={item}
        live={{ price, prev_price: 75000, session_open: 75000, session_change_pct: ((price - 75000) / 75000) * 100, direction: "flat", name: item.name }}
        points={[]}
        selected={false}
        onSelect={() => {}}
        onRemove={() => {}}
      />
    </ul>
  );
}

describe("price flash", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not flash on first render", () => {
    render(renderRow(75000));
    const row = screen.getByTestId("watchlist-row-005930");
    expect(row.dataset.flash).toBe("");
    expect(row.className).not.toMatch(/flash-/);
  });

  it("flashes green on uptick, red on downtick, then clears after ~500ms", () => {
    const { rerender } = render(renderRow(75000));
    const row = () => screen.getByTestId("watchlist-row-005930");

    rerender(renderRow(75100));
    expect(row().dataset.flash).toBe("up");
    expect(row().className).toContain("flash-up");
    expect(screen.getByTestId("watchlist-price-005930")).toHaveTextContent("₩75,100");
    expect(screen.getByTestId("watchlist-change-005930")).toHaveTextContent("+0.13%");

    act(() => vi.advanceTimersByTime(500));
    expect(row().dataset.flash).toBe("");

    rerender(renderRow(74900));
    expect(row().dataset.flash).toBe("down");
    expect(row().className).toContain("flash-down");
    act(() => vi.advanceTimersByTime(500));
    expect(row().className).not.toMatch(/flash-/);
  });

  it("does not flash when the price is unchanged", () => {
    const { rerender } = render(renderRow(75000));
    rerender(renderRow(75000));
    expect(screen.getByTestId("watchlist-row-005930").dataset.flash).toBe("");
  });
});
