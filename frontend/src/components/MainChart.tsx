"use client";

import { formatKRW, formatPct, trendOf } from "@/lib/format";
import type { LivePrice, PricePoint } from "@/lib/types";
import { TimeChart } from "./TimeChart";

interface Props {
  ticker: string | null;
  name: string;
  live?: LivePrice;
  fallbackPrice?: number | null;
  points: PricePoint[];
}

export function MainChart({ ticker, name, live, fallbackPrice, points }: Props) {
  const price = live?.price ?? fallbackPrice ?? null;
  const trend = trendOf(live?.session_change_pct);
  const color = trend === "down" ? "#e5484d" : trend === "up" ? "#2fbf71" : "#209dd7";
  const delta = live ? live.price - live.session_open : null;
  return (
    <section
      data-testid="main-chart"
      data-ticker={ticker ?? ""}
      className="flex min-h-0 flex-col rounded border border-line bg-panel"
    >
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 pb-1 pt-3">
        {ticker ? (
          <>
            <div className="flex items-baseline gap-2">
              <span className="num text-sm font-semibold text-accent">{ticker}</span>
              <span className="text-sm text-fg">{name}</span>
            </div>
            <span className="num text-3xl font-semibold tracking-tight text-fg">{formatKRW(price)}</span>
            <span
              className={`num text-sm font-medium ${trend === "up" ? "text-up" : trend === "down" ? "text-down" : "text-muted"}`}
            >
              {delta === null ? "" : `${delta > 0 ? "+" : delta < 0 ? "-" : ""}${formatKRW(Math.abs(delta))} `}
              {formatPct(live?.session_change_pct)}
            </span>
            <span className="ml-auto text-2xs text-faint">
              Since session open {live ? formatKRW(live.session_open) : "—"}
            </span>
          </>
        ) : (
          <span className="text-sm text-muted">Select a ticker from the watchlist to chart it.</span>
        )}
      </div>
      <div className="relative min-h-0 flex-1">
        {ticker && <TimeChart key={ticker} data={points} color={color} baseline={live?.session_open} className="absolute inset-0" />}
        {ticker && points.length < 2 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-faint">
            Collecting prices since page load…
          </div>
        )}
      </div>
    </section>
  );
}
