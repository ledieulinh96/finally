"use client";

import { useState, type FormEvent } from "react";
import { formatKRW, formatPct, isValidTicker, normalizeTicker, trendOf } from "@/lib/format";
import type { LivePrice, PricePoint, WatchlistItem } from "@/lib/types";
import { usePriceFlash } from "@/hooks/usePriceFlash";
import { Sparkline } from "./Sparkline";

interface RowProps {
  item: WatchlistItem;
  live?: LivePrice;
  points: PricePoint[];
  selected: boolean;
  onSelect: (ticker: string) => void;
  onRemove: (ticker: string) => void;
}

export function WatchlistRow({ item, live, points, selected, onSelect, onRemove }: RowProps) {
  const price = live?.price ?? item.price;
  const change = live?.session_change_pct ?? item.session_change_pct;
  const open = live?.session_open ?? item.session_open;
  const flash = usePriceFlash(price);
  const trend = trendOf(change);
  return (
    <li
      data-testid={`watchlist-row-${item.ticker}`}
      data-flash={flash}
      aria-current={selected ? "true" : undefined}
      onClick={() => onSelect(item.ticker)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(item.ticker);
        }
      }}
      tabIndex={0}
      className={`group relative grid cursor-pointer grid-cols-[1fr_auto] items-center gap-x-2 border-b border-line/60 py-1.5 pl-3 pr-2 outline-none transition-colors hover:bg-raised/60 focus-visible:bg-raised ${
        selected ? "bg-raised" : ""
      } ${flash ? `flash-${flash}` : ""}`}
    >
      {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden />}
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="num text-sm font-semibold text-fg">{item.ticker}</span>
          <span
            data-testid={`watchlist-price-${item.ticker}`}
            className="num ml-auto text-sm font-medium text-fg"
          >
            {formatKRW(price)}
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="truncate text-2xs text-muted" title={item.name}>
            {item.name}
          </span>
          <span
            data-testid={`watchlist-change-${item.ticker}`}
            className={`num ml-auto text-2xs font-medium ${
              trend === "up" ? "text-up" : trend === "down" ? "text-down" : "text-muted"
            }`}
          >
            {formatPct(change)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Sparkline points={points} baseline={open} />
        <button
          type="button"
          data-testid={`watchlist-remove-${item.ticker}`}
          aria-label={`Remove ${item.ticker} from watchlist`}
          title="Remove from watchlist"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(item.ticker);
          }}
          className="flex h-5 w-5 items-center justify-center rounded text-faint opacity-40 hover:bg-down/20 hover:text-down group-hover:opacity-100 focus-visible:opacity-100"
        >
          ×
        </button>
      </div>
    </li>
  );
}

interface Props {
  items: WatchlistItem[];
  prices: Record<string, LivePrice | undefined>;
  history: Record<string, PricePoint[] | undefined>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  /** Resolve to an error message, or null on success. */
  onAdd: (ticker: string) => Promise<string | null>;
  onRemove: (ticker: string) => Promise<string | null>;
}

export function Watchlist({ items, prices, history, selected, onSelect, onAdd, onRemove }: Props) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const ticker = normalizeTicker(input);
    if (!isValidTicker(ticker)) {
      setError("Enter a 6-character KRX code, e.g. 005930");
      return;
    }
    if (items.some((i) => i.ticker === ticker)) {
      setError(`${ticker} is already on your watchlist`);
      return;
    }
    setBusy(true);
    const err = await onAdd(ticker);
    setBusy(false);
    setError(err);
    if (!err) setInput("");
  };

  const remove = async (ticker: string) => {
    const err = await onRemove(ticker);
    setError(err);
  };

  return (
    <section data-testid="watchlist" className="flex min-h-0 flex-col">
      <div className="flex items-center justify-between px-3 pb-1 pt-2">
        <h2 className="text-xs font-semibold text-fg">Watchlist</h2>
        <span className="num text-2xs text-faint">{items.length} tickers</span>
      </div>
      <form onSubmit={submit} className="flex gap-1 px-3 pb-2">
        <input
          data-testid="watchlist-add-input"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (error) setError(null);
          }}
          placeholder="Add ticker, e.g. 247540"
          aria-label="Ticker to add"
          maxLength={16}
          className="num min-w-0 flex-1 rounded border border-line bg-ink px-2 py-1 text-xs text-fg placeholder:text-faint focus:border-primary focus:outline-none"
        />
        <button
          data-testid="watchlist-add-button"
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded border border-primary/60 px-2 text-xs font-medium text-primary hover:bg-primary/15 disabled:opacity-40"
        >
          {busy ? "Adding…" : "Add"}
        </button>
      </form>
      {error && (
        <p data-testid="watchlist-error" role="alert" className="px-3 pb-2 text-2xs text-down">
          {error}
        </p>
      )}
      <ul className="min-h-0 flex-1 overflow-y-auto border-t border-line/60">
        {items.map((item) => (
          <WatchlistRow
            key={item.ticker}
            item={item}
            live={prices[item.ticker]}
            points={history[item.ticker] ?? []}
            selected={selected === item.ticker}
            onSelect={onSelect}
            onRemove={remove}
          />
        ))}
        {items.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-muted">
            Your watchlist is empty. Add a KRX code above to start streaming prices.
          </li>
        )}
      </ul>
    </section>
  );
}
