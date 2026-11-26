"use client";

import { formatKRW, formatSignedKRW, trendOf } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/types";
import { usePriceFlash } from "@/hooks/usePriceFlash";

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Disconnected",
};

const DOT: Record<ConnectionStatus, string> = {
  connected: "bg-up shadow-[0_0_8px_rgba(47,191,113,0.8)]",
  reconnecting: "bg-accent animate-pulse",
  disconnected: "bg-down",
};

interface Props {
  totalValue: number | null;
  cash: number | null;
  unrealizedPnl: number | null;
  status: ConnectionStatus;
  marketClosed: boolean;
  source?: string;
}

export function Header({ totalValue, cash, unrealizedPnl, status, marketClosed, source }: Props) {
  const flash = usePriceFlash(totalValue === null ? null : Math.round(totalValue));
  const trend = trendOf(unrealizedPnl);
  return (
    <header className="flex items-center gap-6 border-b border-line bg-panel px-4 py-2">
      <div className="flex items-baseline gap-2">
        <span className="text-lg font-semibold tracking-tight text-fg">
          Fin<span className="text-accent">Ally</span>
        </span>
        <span className="hidden text-2xs text-faint sm:inline">KRX trading workstation</span>
      </div>

      <div className="ml-auto flex items-center gap-6">
        <div className="text-right">
          <div className="text-2xs text-muted">Portfolio value</div>
          <div
            data-testid="header-total-value"
            className={`num rounded px-1 text-xl font-semibold leading-tight text-fg ${flash ? `flash-${flash}` : ""}`}
          >
            {formatKRW(totalValue)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xs text-muted">Unrealized P&amp;L</div>
          <div
            className={`num text-sm font-medium ${trend === "up" ? "text-up" : trend === "down" ? "text-down" : "text-muted"}`}
          >
            {formatSignedKRW(unrealizedPnl)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xs text-muted">Cash</div>
          <div data-testid="header-cash" className="num text-sm font-medium text-fg">
            {formatKRW(cash)}
          </div>
        </div>
        {marketClosed && (
          <span
            data-testid="market-closed-badge"
            className="rounded border border-accent/50 px-2 py-0.5 text-2xs text-accent"
            title="KRX is outside regular hours; prices are frozen at the last close."
          >
            Market closed
          </span>
        )}
        <div className="flex items-center gap-2" title={source ? `Source: ${source}` : undefined}>
          <span
            data-testid="connection-status"
            data-status={status}
            aria-label={`Price stream ${STATUS_LABEL[status].toLowerCase()}`}
            className={`inline-block h-2.5 w-2.5 rounded-full ${DOT[status]}`}
          />
          <span className="text-2xs text-muted">{STATUS_LABEL[status]}</span>
        </div>
      </div>
    </header>
  );
}
