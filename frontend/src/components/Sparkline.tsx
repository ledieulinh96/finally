import type { PricePoint } from "@/lib/types";

interface Props {
  points: PricePoint[];
  width?: number;
  height?: number;
  baseline?: number | null;
}

/** Tiny SVG sparkline; colour follows the last price versus the session open. */
export function Sparkline({ points, width = 84, height = 24, baseline }: Props) {
  if (points.length < 2) {
    return <svg width={width} height={height} aria-hidden className="opacity-40" />;
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values, baseline ?? Infinity);
  const max = Math.max(...values, baseline ?? -Infinity);
  const span = max - min || 1;
  const stepX = width / (points.length - 1);
  const y = (v: number) => height - 1 - ((v - min) / span) * (height - 2);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const last = values[values.length - 1];
  const ref = baseline ?? values[0];
  const color = last > ref ? "#2fbf71" : last < ref ? "#e5484d" : "#8590a8";
  return (
    <svg width={width} height={height} aria-hidden>
      {baseline != null && baseline >= min && baseline <= max && (
        <line x1={0} x2={width} y1={y(baseline)} y2={y(baseline)} stroke="#273049" strokeDasharray="2 2" />
      )}
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} strokeLinejoin="round" />
    </svg>
  );
}
