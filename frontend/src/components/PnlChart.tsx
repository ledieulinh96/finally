"use client";

import { useMemo } from "react";
import { formatSignedKRW, formatPct } from "@/lib/format";
import type { PricePoint, Snapshot } from "@/lib/types";
import { TimeChart } from "./TimeChart";

/** Snapshots → ascending, one point per second, plus the live total as the last point. */
export function buildPnlSeries(snapshots: Snapshot[], liveTotal: number | null, now = Date.now()): PricePoint[] {
  const byTime = new Map<number, number>();
  for (const s of snapshots) {
    const t = Date.parse(s.recorded_at);
    if (!Number.isFinite(t)) continue;
    byTime.set(Math.floor(t / 1000), s.total_value);
  }
  const pts = [...byTime.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }));
  if (liveTotal !== null) {
    const t = Math.floor(now / 1000);
    const last = pts[pts.length - 1];
    if (last && last.time >= t) last.value = liveTotal;
    else pts.push({ time: t, value: liveTotal });
  }
  return pts;
}

interface Props {
  snapshots: Snapshot[];
  liveTotal: number | null;
}

export function PnlChart({ snapshots, liveTotal }: Props) {
  // Re-evaluate the live point at most when the rounded total changes.
  const rounded = liveTotal === null ? null : Math.round(liveTotal);
  const data = useMemo(() => buildPnlSeries(snapshots, rounded), [snapshots, rounded]);
  const start = data[0]?.value ?? null;
  const end = data[data.length - 1]?.value ?? null;
  const change = start !== null && end !== null ? end - start : null;
  const pct = change !== null && start ? (change / start) * 100 : null;
  const color = change !== null && change < 0 ? "#e5484d" : "#209dd7";
  return (
    <section className="flex min-h-0 flex-col rounded border border-line bg-panel">
      <div className="flex items-baseline justify-between px-3 pb-1 pt-2">
        <h2 className="text-xs font-semibold text-fg">Portfolio value</h2>
        <span className={`num text-2xs font-medium ${change && change < 0 ? "text-down" : change ? "text-up" : "text-muted"}`}>
          {formatSignedKRW(change)} {pct !== null ? formatPct(pct) : ""}
        </span>
      </div>
      <div data-testid="pnl-chart" data-points={data.length} className="relative mx-1 mb-1 min-h-[140px] flex-1">
        <TimeChart data={data} color={color} baseline={start} compactAxis showSeconds={false} className="absolute inset-0" />
      </div>
    </section>
  );
}
