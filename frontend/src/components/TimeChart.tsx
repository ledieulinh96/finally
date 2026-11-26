"use client";

import { useEffect, useRef } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { PricePoint } from "@/lib/types";
import { formatKRW, formatKRWCompact } from "@/lib/format";

interface Props {
  data: PricePoint[];
  color: string;
  /** Horizontal reference line (session open / starting value). */
  baseline?: number | null;
  compactAxis?: boolean;
  showSeconds?: boolean;
  className?: string;
}

/** Canvas area chart (lightweight-charts), created lazily on the client. */
export function TimeChart({ data, color, baseline, compactAxis, showSeconds = true, className }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);
  const baseLine = useRef<ReturnType<ISeriesApi<"Area">["createPriceLine"]> | null>(null);
  const latest = useRef({ data, color, baseline });
  latest.current = { data, color, baseline };

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | null = null;
    import("lightweight-charts").then(({ createChart, ColorType, LineStyle, CrosshairMode }) => {
      if (disposed || !host.current) return;
      const c = createChart(host.current, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#8590a8",
          fontFamily: '"IBM Plex Sans", system-ui, sans-serif',
          fontSize: 11,
        },
        grid: { vertLines: { color: "#1b2337" }, horzLines: { color: "#1b2337" } },
        rightPriceScale: { borderColor: "#273049" },
        timeScale: { borderColor: "#273049", timeVisible: true, secondsVisible: showSeconds },
        crosshair: { mode: CrosshairMode.Magnet },
        localization: {
          priceFormatter: (p: number) => (compactAxis ? formatKRWCompact(p) : formatKRW(p)),
        },
        handleScroll: false,
        handleScale: false,
      });
      const s = c.addAreaSeries({
        lineColor: latest.current.color,
        topColor: `${latest.current.color}55`,
        bottomColor: `${latest.current.color}05`,
        lineWidth: 2,
        priceLineVisible: true,
        priceLineColor: "#ecad0a",
        lastValueVisible: true,
      });
      chart.current = c;
      series.current = s;
      s.setData(latest.current.data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
      if (latest.current.baseline != null) {
        baseLine.current = s.createPriceLine({
          price: latest.current.baseline,
          color: "#5b6580",
          lineStyle: LineStyle.Dashed,
          lineWidth: 1,
          axisLabelVisible: false,
          title: "",
        });
      }
      c.timeScale().fitContent();
      if (typeof ResizeObserver !== "undefined") {
        ro = new ResizeObserver(() => c.timeScale().fitContent());
        ro.observe(host.current);
      }
    });
    return () => {
      disposed = true;
      ro?.disconnect();
      chart.current?.remove();
      chart.current = null;
      series.current = null;
      baseLine.current = null;
    };
  }, [compactAxis, showSeconds]);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    s.setData(data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chart.current?.timeScale().fitContent();
  }, [data]);

  useEffect(() => {
    series.current?.applyOptions({ lineColor: color, topColor: `${color}55`, bottomColor: `${color}05` });
  }, [color]);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    if (baseLine.current) {
      s.removePriceLine(baseLine.current);
      baseLine.current = null;
    }
    if (baseline != null) {
      baseLine.current = s.createPriceLine({
        price: baseline,
        color: "#5b6580",
        lineStyle: 2,
        lineWidth: 1,
        axisLabelVisible: false,
        title: "",
      });
    }
  }, [baseline]);

  return <div ref={host} className={className} />;
}
