"use client";

import { useEffect, useRef, useState } from "react";
import type { ConnectionStatus, LivePrice, PriceEvent, PricePoint } from "@/lib/types";

export const RETRY_MIN_MS = 1000;
export const RETRY_MAX_MS = 10_000;
const MAX_POINTS = 1200; // ~10 min at 0.5 s; enough for sparklines and the main chart

export interface PriceStream {
  prices: Record<string, LivePrice>;
  history: Record<string, PricePoint[]>;
  status: ConnectionStatus;
}

/** Append a point, collapsing points that fall in the same second (charts need strictly ascending times). */
export function appendPoint(series: PricePoint[], point: PricePoint, max = MAX_POINTS): PricePoint[] {
  const last = series[series.length - 1];
  let next: PricePoint[];
  if (last && point.time <= last.time) {
    next = series.slice(0, -1);
    next.push({ time: last.time, value: point.value });
  } else {
    next = series.concat(point);
  }
  if (next.length > max) next = next.slice(next.length - max);
  return next;
}

/**
 * Subscribes to `/api/stream/prices` via native EventSource. Events are buffered in a ref and
 * flushed to React state at most every `flushMs` so a 500 ms tick across many tickers causes one
 * render instead of one per ticker.
 */
export function usePriceStream(url = "/api/stream/prices", flushMs = 200): PriceStream {
  const [state, setState] = useState<PriceStream>({ prices: {}, history: {}, status: "reconnecting" });
  const pending = useRef<PriceEvent[]>([]);

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setState((s) => ({ ...s, status: "disconnected" }));
      return;
    }
    const setStatus = (status: ConnectionStatus) =>
      setState((s) => (s.status === status ? s : { ...s, status }));

    // The browser retries dropped connections itself (readyState CONNECTING). A fatal failure
    // (non-200, wrong content-type) leaves it CLOSED for good, so we reconnect with backoff.
    let es: EventSource | null = null;
    let retryTimer: number | undefined;
    let backoff = RETRY_MIN_MS;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const source = new EventSource(url);
      es = source;
      source.onopen = () => {
        backoff = RETRY_MIN_MS;
        setStatus("connected");
      };
      source.onerror = () => {
        if (source.readyState !== EventSource.CLOSED) {
          setStatus("reconnecting");
          return;
        }
        setStatus("disconnected");
        source.close();
        if (es === source) es = null;
        window.clearTimeout(retryTimer);
        retryTimer = window.setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, RETRY_MAX_MS);
      };
      source.onmessage = (e: MessageEvent<string>) => {
        try {
          const ev = JSON.parse(e.data) as PriceEvent;
          if (ev && typeof ev.ticker === "string" && typeof ev.price === "number") pending.current.push(ev);
        } catch {
          /* ignore malformed frames */
        }
      };
    };
    connect();

    const timer = window.setInterval(() => {
      if (pending.current.length === 0) return;
      const batch = pending.current;
      pending.current = [];
      setState((s) => {
        const prices = { ...s.prices };
        const history = { ...s.history };
        for (const ev of batch) {
          prices[ev.ticker] = {
            price: ev.price,
            prev_price: ev.prev_price,
            session_open: ev.session_open,
            session_change_pct: ev.session_change_pct,
            direction: ev.direction,
            name: ev.name,
          };
          const t = Date.parse(ev.timestamp);
          const time = Math.floor((Number.isFinite(t) ? t : Date.now()) / 1000);
          history[ev.ticker] = appendPoint(history[ev.ticker] ?? [], { time, value: ev.price });
        }
        return { prices, history, status: "connected" };
      });
    }, flushMs);

    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.clearTimeout(retryTimer);
      es?.close();
    };
  }, [url, flushMs]);

  return state;
}
