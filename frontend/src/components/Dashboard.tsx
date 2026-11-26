"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { livePortfolio } from "@/lib/portfolio";
import type { Health, Portfolio, Side, Snapshot, WatchlistItem } from "@/lib/types";
import { usePriceStream } from "@/hooks/usePriceStream";
import { Header } from "./Header";
import { Watchlist } from "./Watchlist";
import { MainChart } from "./MainChart";
import { TradeBar } from "./TradeBar";
import { Heatmap } from "./Heatmap";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { ChatPanel } from "./ChatPanel";

const OPEN_SESSIONS = new Set(["regular", "closing_auction"]);

export function Dashboard() {
  const stream = usePriceStream();
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshWatchlist = useCallback(async () => {
    setWatchlist(await api.watchlist());
  }, []);

  const refreshPortfolio = useCallback(async () => {
    const [p, h] = await Promise.all([api.portfolio(), api.history()]);
    setPortfolio(p);
    setSnapshots(h);
  }, []);

  const refreshAll = useCallback(async () => {
    try {
      await Promise.all([refreshWatchlist(), refreshPortfolio()]);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshWatchlist, refreshPortfolio]);

  useEffect(() => {
    refreshAll();
    const loadHealth = () => api.health().then(setHealth).catch(() => undefined);
    loadHealth();
    const h = window.setInterval(loadHealth, 30_000);
    // Background snapshots land every 60 s; pick them up for the P&L chart.
    const p = window.setInterval(() => refreshPortfolio().catch(() => undefined), 60_000);
    return () => {
      window.clearInterval(h);
      window.clearInterval(p);
    };
  }, [refreshAll, refreshPortfolio]);

  // After the stream recovers (e.g. server restart), re-sync REST state that may have moved on.
  const seenUp = useRef(false);
  const wasDown = useRef(false);
  useEffect(() => {
    if (stream.status !== "connected") wasDown.current = seenUp.current;
    else if (!seenUp.current) seenUp.current = true;
    else if (wasDown.current) {
      wasDown.current = false;
      refreshAll();
    }
  }, [stream.status, refreshAll]);

  // Keep a valid selection: default to the first watchlist ticker.
  useEffect(() => {
    const known =
      selected && (watchlist.some((w) => w.ticker === selected) || portfolio?.positions.some((p) => p.ticker === selected));
    if (!known) setSelected(watchlist[0]?.ticker ?? portfolio?.positions[0]?.ticker ?? null);
  }, [watchlist, portfolio, selected]);

  const live = useMemo(() => livePortfolio(portfolio, stream.prices), [portfolio, stream.prices]);

  const priceOf = useCallback(
    (t: string) =>
      stream.prices[t]?.price ??
      watchlist.find((w) => w.ticker === t)?.price ??
      portfolio?.positions.find((p) => p.ticker === t)?.current_price ??
      null,
    [stream.prices, watchlist, portfolio],
  );

  const onTrade = useCallback(
    async (ticker: string, quantity: number, side: Side) => {
      const r = await api.trade(ticker, quantity, side);
      if (r.success) await refreshAll();
      return r;
    },
    [refreshAll],
  );

  const onAdd = useCallback(
    async (ticker: string) => {
      try {
        await api.addWatchlist(ticker);
        await refreshWatchlist();
        setSelected(ticker);
        return null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return `${ticker} isn't a known KRX ticker`;
        return e instanceof Error ? e.message : String(e);
      }
    },
    [refreshWatchlist],
  );

  const onRemove = useCallback(
    async (ticker: string) => {
      setWatchlist((w) => w.filter((i) => i.ticker !== ticker));
      try {
        await api.removeWatchlist(ticker);
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      } finally {
        refreshWatchlist().catch(() => undefined);
      }
    },
    [refreshWatchlist],
  );

  const onChat = useCallback(
    async (message: string) => {
      const r = await api.chat(message);
      if ((r.trades?.length ?? 0) > 0 || (r.watchlist_changes?.length ?? 0) > 0) await refreshAll();
      return r;
    },
    [refreshAll],
  );

  const selectedName =
    (selected &&
      (watchlist.find((w) => w.ticker === selected)?.name ??
        portfolio?.positions.find((p) => p.ticker === selected)?.name ??
        stream.prices[selected]?.name)) ||
    "";

  const marketClosed = health?.source === "yfinance" && !OPEN_SESSIONS.has(health.market_session);

  return (
    <div className="flex min-h-screen flex-col bg-ink text-fg lg:h-screen lg:min-h-[640px] lg:overflow-hidden">
      <Header
        totalValue={live?.totalValue ?? null}
        cash={live?.cash ?? null}
        unrealizedPnl={live?.unrealizedPnl ?? null}
        status={stream.status}
        marketClosed={marketClosed}
        source={health?.source}
      />
      {loadError && (
        <div role="alert" className="border-b border-down/40 bg-down/10 px-4 py-1.5 text-xs text-down">
          Portfolio data didn&apos;t load: {loadError}{" "}
          <button type="button" onClick={refreshAll} className="underline underline-offset-2">
            Retry
          </button>
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <aside className="flex max-h-[40vh] min-h-0 w-full flex-col border-b border-line bg-panel lg:max-h-none lg:w-[300px] lg:border-b-0 lg:border-r">
          <Watchlist
            items={watchlist}
            prices={stream.prices}
            history={stream.history}
            selected={selected}
            onSelect={setSelected}
            onAdd={onAdd}
            onRemove={onRemove}
          />
        </aside>
        <main className="grid min-h-0 min-w-0 flex-1 auto-rows-min grid-cols-1 gap-2 p-2 lg:overflow-y-auto xl:grid-cols-2 xl:grid-rows-[minmax(260px,1.3fr)_auto_minmax(200px,1fr)_minmax(160px,0.9fr)] xl:overflow-hidden">
          <div className="h-[300px] xl:col-span-2 xl:h-auto xl:min-h-0 [&>section]:h-full">
            <MainChart
              ticker={selected}
              name={selectedName}
              live={selected ? stream.prices[selected] : undefined}
              fallbackPrice={selected ? priceOf(selected) : null}
              points={selected ? (stream.history[selected] ?? []) : []}
            />
          </div>
          <div className="xl:col-span-2">
            <TradeBar selected={selected} priceOf={priceOf} onTrade={onTrade} />
          </div>
          <div className="h-[240px] xl:h-auto xl:min-h-0 [&>section]:h-full">
            <Heatmap positions={live?.positions ?? []} />
          </div>
          <div className="h-[240px] xl:h-auto xl:min-h-0 [&>section]:h-full">
            <PnlChart snapshots={snapshots} liveTotal={live?.totalValue ?? null} />
          </div>
          <div className="max-h-[320px] xl:col-span-2 xl:max-h-none xl:min-h-0 [&>section]:h-full">
            <PositionsTable positions={live?.positions ?? []} onSelect={setSelected} />
          </div>
        </main>
        <div className="flex h-[520px] min-h-0 lg:h-auto">
          <ChatPanel open={chatOpen} onToggle={() => setChatOpen((o) => !o)} onSend={onChat} loadHistory={api.chatHistory} />
        </div>
      </div>
    </div>
  );
}
