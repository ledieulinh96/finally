import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { api } from "@/lib/api";
import { Watchlist } from "@/components/Watchlist";
import type { WatchlistItem } from "@/lib/types";

const row = (ticker: string, name: string, price: number | null): WatchlistItem => ({
  ticker,
  name,
  price,
  prev_price: price,
  session_open: price,
  session_change_pct: price === null ? null : 0,
  direction: "flat",
});

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Minimal harness wiring Watchlist to the real api client over a mocked fetch. */
function Harness({ initial }: { initial: WatchlistItem[] }) {
  const [items, setItems] = useState(initial);
  const reload = async () => setItems(await api.watchlist());
  return (
    <Watchlist
      items={items}
      prices={{}}
      history={{}}
      selected={null}
      onSelect={() => {}}
      onAdd={async (t) => {
        try {
          await api.addWatchlist(t);
          await reload();
          return null;
        } catch (e) {
          return (e as Error).message;
        }
      }}
      onRemove={async (t) => {
        try {
          await api.removeWatchlist(t);
          await reload();
          return null;
        } catch (e) {
          return (e as Error).message;
        }
      }}
    />
  );
}

describe("watchlist CRUD", () => {
  let server: WatchlistItem[];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === "/api/watchlist" && method === "GET") return jsonResponse(200, server);
    if (url === "/api/watchlist" && method === "POST") {
      const { ticker } = JSON.parse(String(init!.body));
      if (server.some((s) => s.ticker === ticker)) return jsonResponse(409, { detail: "Ticker already in watchlist" });
      if (ticker === "999999") return jsonResponse(404, { detail: "Unknown ticker" });
      server = [...server, row(ticker, "EcoPro BM", 86200)];
      return jsonResponse(201, { ticker, name: "EcoPro BM", price: 86200 });
    }
    const m = url.match(/^\/api\/watchlist\/(\w+)$/);
    if (m && method === "DELETE") {
      if (!server.some((s) => s.ticker === m[1])) return jsonResponse(404, { detail: "Not in watchlist" });
      server = server.filter((s) => s.ticker !== m[1]);
      return new Response(null, { status: 204 });
    }
    return jsonResponse(500, { detail: "unexpected" });
  });

  beforeEach(() => {
    server = [row("005930", "Samsung Electronics", 75000), row("000660", "SK Hynix", 180000)];
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("renders rows with KRW prices and a dash for unpriced tickers", () => {
    render(<Harness initial={[...server, row("247540", "에코프로비엠", null)]} />);
    expect(screen.getByTestId("watchlist-price-005930")).toHaveTextContent("₩75,000");
    expect(screen.getByTestId("watchlist-price-247540")).toHaveTextContent("—");
    expect(screen.getByText("에코프로비엠")).toBeInTheDocument();
  });

  it("adds a ticker (normalising input) and shows it", async () => {
    const user = userEvent.setup();
    render(<Harness initial={server} />);
    await user.type(screen.getByTestId("watchlist-add-input"), " 247540.kq ");
    await user.click(screen.getByTestId("watchlist-add-button"));
    await waitFor(() => expect(screen.getByTestId("watchlist-row-247540")).toBeInTheDocument());
    const post = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ ticker: "247540" });
    expect(screen.getByTestId("watchlist-add-input")).toHaveValue("");
  });

  it("shows the backend error for unknown tickers", async () => {
    const user = userEvent.setup();
    render(<Harness initial={server} />);
    await user.type(screen.getByTestId("watchlist-add-input"), "999999");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByTestId("watchlist-error")).toHaveTextContent("Unknown ticker");
  });

  it("rejects malformed and duplicate tickers without calling the API", async () => {
    const user = userEvent.setup();
    render(<Harness initial={server} />);
    await user.type(screen.getByTestId("watchlist-add-input"), "AAPL");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(screen.getByTestId("watchlist-error")).toHaveTextContent(/6-character/);
    await user.clear(screen.getByTestId("watchlist-add-input"));
    await user.type(screen.getByTestId("watchlist-add-input"), "005930");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(screen.getByTestId("watchlist-error")).toHaveTextContent(/already/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("removes a ticker", async () => {
    const user = userEvent.setup();
    render(<Harness initial={server} />);
    await user.click(screen.getByTestId("watchlist-remove-000660"));
    await waitFor(() => expect(screen.queryByTestId("watchlist-row-000660")).not.toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/watchlist/000660", expect.objectContaining({ method: "DELETE" }));
    expect(screen.getByTestId("watchlist-row-005930")).toBeInTheDocument();
  });
});
