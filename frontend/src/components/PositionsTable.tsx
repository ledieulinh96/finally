import { formatKRW, formatPct, formatQty, formatSignedKRW } from "@/lib/format";
import type { Position } from "@/lib/types";

interface Props {
  positions: Position[];
  onSelect: (ticker: string) => void;
}

export function PositionsTable({ positions, onSelect }: Props) {
  const tone = (v: number) => (v > 0 ? "text-up" : v < 0 ? "text-down" : "text-muted");
  return (
    <section className="flex min-h-0 flex-col rounded border border-line bg-panel">
      <div className="flex items-baseline justify-between px-3 pb-1 pt-2">
        <h2 className="text-xs font-semibold text-fg">Positions</h2>
        <span className="num text-2xs text-faint">{positions.length} open</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table data-testid="positions-table" className="num w-full text-xs">
          <thead className="sticky top-0 bg-panel text-2xs text-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-1 text-left font-medium">Ticker</th>
              <th className="px-2 py-1 text-left font-medium">Company</th>
              <th className="px-2 py-1 text-right font-medium">Qty</th>
              <th className="px-2 py-1 text-right font-medium">Avg cost</th>
              <th className="px-2 py-1 text-right font-medium">Price</th>
              <th className="px-2 py-1 text-right font-medium">Unrealized P&amp;L</th>
              <th className="px-3 py-1 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr
                key={p.ticker}
                data-testid={`position-row-${p.ticker}`}
                onClick={() => onSelect(p.ticker)}
                className="cursor-pointer border-b border-line/50 hover:bg-raised/60"
              >
                <td className="px-3 py-1 font-semibold text-fg">{p.ticker}</td>
                <td className="max-w-[160px] truncate px-2 py-1 text-muted" title={p.name}>
                  {p.name}
                </td>
                <td data-testid={`position-qty-${p.ticker}`} className="px-2 py-1 text-right text-fg">
                  {formatQty(p.quantity)}
                </td>
                <td className="px-2 py-1 text-right text-muted">{formatKRW(p.avg_cost)}</td>
                <td className="px-2 py-1 text-right text-fg">{formatKRW(p.current_price)}</td>
                <td className={`px-2 py-1 text-right font-medium ${tone(p.unrealized_pnl)}`}>
                  {formatSignedKRW(p.unrealized_pnl)}
                </td>
                <td className={`px-3 py-1 text-right ${tone(p.pnl_pct)}`}>{formatPct(p.pnl_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {positions.length === 0 && (
          <p data-testid="positions-empty" className="px-3 py-4 text-xs text-faint">
            You hold no shares. Your ₩ cash is ready — place a market order above or ask the assistant.
          </p>
        )}
      </div>
    </section>
  );
}
