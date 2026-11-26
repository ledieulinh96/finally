"use client";

import { useEffect, useState } from "react";
import { formatKRW, formatQty, isValidTicker, normalizeTicker } from "@/lib/format";
import type { Side, TradeResult } from "@/lib/types";

interface Props {
  selected: string | null;
  priceOf: (ticker: string) => number | null;
  onTrade: (ticker: string, quantity: number, side: Side) => Promise<TradeResult>;
}

export function TradeBar({ selected, priceOf, onTrade }: Props) {
  const [ticker, setTicker] = useState(selected ?? "");
  const [qty, setQty] = useState("1");
  const [busy, setBusy] = useState<Side | null>(null);
  const [result, setResult] = useState<{ status: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (selected) setTicker(selected);
  }, [selected]);

  const t = normalizeTicker(ticker);
  const q = Number(qty);
  const qtyValid = /^\d+$/.test(qty.trim()) && q > 0;
  const est = isValidTicker(t) && qtyValid ? priceOf(t) : null;

  const submit = async (side: Side) => {
    if (!isValidTicker(t)) {
      setResult({ status: "error", text: "Enter a 6-character KRX code, e.g. 005930" });
      return;
    }
    if (!qtyValid) {
      setResult({ status: "error", text: "Quantity must be a whole number of shares above zero" });
      return;
    }
    setBusy(side);
    const r = await onTrade(t, q, side);
    setBusy(null);
    if (r.success) {
      setResult({
        status: "success",
        text: `${r.side === "buy" ? "Bought" : "Sold"} ${formatQty(r.quantity)} ${r.ticker} at ${formatKRW(r.price)}`,
      });
    } else {
      setResult({ status: "error", text: r.error });
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit("buy");
      }}
      className="flex flex-wrap items-center gap-2 rounded border border-line bg-panel px-3 py-2"
      aria-label="Market order"
    >
      <span className="text-xs font-semibold text-fg">Market order</span>
      <label className="flex items-center gap-1 text-2xs text-muted">
        Ticker
        <input
          data-testid="trade-ticker-input"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          maxLength={16}
          className="num w-24 rounded border border-line bg-ink px-2 py-1 text-xs text-fg focus:border-primary focus:outline-none"
        />
      </label>
      <label className="flex items-center gap-1 text-2xs text-muted">
        Shares
        <input
          data-testid="trade-quantity-input"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          inputMode="numeric"
          className="num w-20 rounded border border-line bg-ink px-2 py-1 text-right text-xs text-fg focus:border-primary focus:outline-none"
        />
      </label>
      <span className="num w-28 text-2xs text-faint" aria-live="polite">
        {est !== null ? `≈ ${formatKRW(est * q)}` : ""}
      </span>
      <button
        type="button"
        data-testid="trade-buy-button"
        disabled={busy !== null}
        onClick={() => submit("buy")}
        className="rounded bg-up/90 px-4 py-1 text-xs font-semibold text-ink hover:bg-up disabled:opacity-50"
      >
        {busy === "buy" ? "Buying…" : "Buy"}
      </button>
      <button
        type="button"
        data-testid="trade-sell-button"
        disabled={busy !== null}
        onClick={() => submit("sell")}
        className="rounded bg-down/90 px-4 py-1 text-xs font-semibold text-white hover:bg-down disabled:opacity-50"
      >
        {busy === "sell" ? "Selling…" : "Sell"}
      </button>
      {result && (
        <span
          data-testid="trade-message"
          data-status={result.status}
          role={result.status === "error" ? "alert" : "status"}
          className={`num text-xs ${result.status === "error" ? "text-down" : "text-up"}`}
        >
          {result.text}
        </span>
      )}
    </form>
  );
}
