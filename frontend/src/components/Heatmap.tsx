"use client";

import { useEffect, useRef, useState } from "react";
import { formatKRW, formatPct } from "@/lib/format";
import { pnlColor, squarify } from "@/lib/portfolio";
import type { Position } from "@/lib/types";

export function Heatmap({ positions }: { positions: Position[] }) {
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 400, h: 220 });

  useEffect(() => {
    const el = host.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const total = positions.reduce((s, p) => s + p.market_value, 0);
  const cells = squarify(
    positions.map((p) => ({ item: p, value: p.market_value })),
    { x: 0, y: 0, w: size.w, h: size.h },
  );

  return (
    <section className="flex min-h-0 flex-col rounded border border-line bg-panel">
      <div className="flex items-baseline justify-between px-3 pb-1 pt-2">
        <h2 className="text-xs font-semibold text-fg">Holdings map</h2>
        <span className="text-2xs text-faint">Size by weight, colour by P&amp;L</span>
      </div>
      <div ref={host} data-testid="heatmap" className="relative mx-2 mb-2 min-h-[140px] flex-1 overflow-hidden rounded-sm">
        {cells.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-faint">
            No positions yet. Buy a ticker from the trade bar and it appears here.
          </div>
        )}
        {cells.map(({ item: p, rect }) => {
          const pnl = p.pnl_pct > 0 ? "profit" : p.pnl_pct < 0 ? "loss" : "flat";
          const roomy = rect.w > 70 && rect.h > 44;
          const weight = total ? (p.market_value / total) * 100 : 0;
          return (
            <div
              key={p.ticker}
              data-testid={`heatmap-cell-${p.ticker}`}
              data-pnl={pnl}
              title={`${p.ticker} ${p.name}\n${formatKRW(p.market_value)}, ${weight.toFixed(1)}% of holdings\nP&L ${formatPct(p.pnl_pct)}`}
              className="absolute overflow-hidden border border-ink/70 px-1.5 py-1 transition-[background-color] duration-500"
              style={{
                left: rect.x,
                top: rect.y,
                width: rect.w,
                height: rect.h,
                backgroundColor: pnlColor(p.pnl_pct),
              }}
            >
              <div className="num truncate text-xs font-semibold text-white">{p.ticker}</div>
              {roomy && (
                <>
                  <div className="truncate text-2xs text-white/75">{p.name}</div>
                  <div className="num text-2xs font-medium text-white">{formatPct(p.pnl_pct)}</div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
