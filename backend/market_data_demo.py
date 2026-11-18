"""FinAlly — Market Data Demo.

A plain terminal demo (no UI library) that runs the KRX market simulator and
shows it producing live data: tickers, red/green price moves and text
sparklines. At the end it checks every quote it saw and prints PASS/FAIL.

    uv run market_data_demo.py                 # 30 s live view
    uv run market_data_demo.py -d 10 --seed 42 # short, reproducible run
    uv run market_data_demo.py --plain | cat   # log-style snapshots (auto when piped)

Exit code is 0 when every check passes, 1 otherwise. Colours honour NO_COLOR.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field

from app.market.cache import PriceCache
from app.market.models import PriceQuote
from app.market.names import NameRegistry
from app.market.seed_data import DEFAULT_TICKERS
from app.market.simulator import SimulatorSource
from app.market.ticks import limit_band, snap_to_tick

SPARK = "▁▂▃▄▅▆▇█"
SPARK_WIDTH = 40
SSE_KEYS = {
    "ticker", "name", "price", "prev_price", "session_open",
    "session_change_pct", "direction", "timestamp",
}  # fmt: skip


# --------------------------------------------------------------------- colours


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, s: str) -> str:
        return f"\x1b[{code}m{s}\x1b[0m" if self.enabled else s

    def green(self, s: str) -> str:
        return self._wrap("32", s)

    def red(self, s: str) -> str:
        return self._wrap("31", s)

    def dim(self, s: str) -> str:
        return self._wrap("2", s)

    def bold(self, s: str) -> str:
        return self._wrap("1", s)

    def yellow(self, s: str) -> str:
        return self._wrap("33", s)

    def by_sign(self, value: float, s: str) -> str:
        if value > 0:
            return self.green(s)
        if value < 0:
            return self.red(s)
        return self.dim(s)


# --------------------------------------------------------------------- helpers


def krw(price: int) -> str:
    return f"₩{price:,}"


def sparkline(values: list[int], width: int = SPARK_WIDTH) -> str:
    """Unicode sparkline of the last ``width`` values (flat line if no range)."""
    vals = values[-width:]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return SPARK[3] * len(vals)
    top = len(SPARK) - 1
    return "".join(SPARK[round((v - lo) / (hi - lo) * top)] for v in vals)


def pad(s: str, width: int, right: bool = False) -> str:
    """Pad to a visible width (the strings here contain no ANSI codes yet)."""
    return s.rjust(width) if right else s.ljust(width)[:width]


@dataclass
class Stats:
    """What the demo observed, used for the final checks."""

    updates: dict[str, int] = field(default_factory=dict)
    ups: int = 0
    downs: int = 0
    failures: list[str] = field(default_factory=list)
    last_version: int = 0

    def check(self, q: PriceQuote, name: str) -> None:
        def fail(msg: str) -> None:
            if len(self.failures) < 20:
                self.failures.append(f"{q.ticker}: {msg}")

        if not isinstance(q.price, int):
            fail(f"price {q.price!r} is not an int")
            return
        if snap_to_tick(q.price) != q.price:
            fail(f"price {q.price} is not on the KRX tick grid")
        lo, hi = limit_band(q.session_open)
        if not lo <= q.price <= hi:
            fail(f"price {q.price} outside ±30% band [{lo}, {hi}]")
        if q.version <= self.last_version:
            fail(f"cache version {q.version} did not increase")
        if set(q.to_event(name)) != SSE_KEYS:
            fail("SSE payload keys differ from PLAN §6")


# --------------------------------------------------------------------- render


def render(
    st: Style,
    cache: PriceCache,
    names: NameRegistry,
    history: dict[str, deque[int]],
    events: deque[str],
    stats: Stats,
    elapsed: float,
    duration: float,
    seed: int | None,
) -> str:
    total = sum(stats.updates.values())
    lines = [
        st.bold(st.yellow("FinAlly"))
        + st.bold(" — Market Data Demo")
        + st.dim(
            f"   source: simulator · seed: {seed if seed is not None else 'random'}"
            f" · {elapsed:4.1f}s / {duration:.0f}s · {total} price updates"
            f" ({stats.ups}▲ {stats.downs}▼)"
        ),
        "",
        st.bold(
            f"{'TICKER':<7} {'NAME':<20} {'PRICE':>11}   {'CHANGE':>8} {'SESSION':>8}  "
            f"TREND (last {SPARK_WIDTH} updates)"
        ),
    ]
    for t in DEFAULT_TICKERS:
        q = cache.get(t)
        if q is None:
            lines.append(f"{t:<7} {pad(names.get(t), 20)} {'—':>11}")
            continue
        arrow = {"up": "▲", "down": "▼"}.get(q.direction, "·")
        hist = list(history[t])
        trend = hist[-1] - hist[0] if hist else 0
        lines.append(
            f"{t:<7} {pad(names.get(t), 20)} "
            + st.by_sign(q.change, f"{krw(q.price):>11} {arrow}")
            + " "
            + st.by_sign(q.change, f"{q.change:>+8,}")
            + " "
            + st.by_sign(q.session_change_pct, f"{q.session_change_pct:>+7.2f}%")
            + "  "
            + st.by_sign(trend, sparkline(hist))
        )
    lines += ["", st.bold("Jump events (2–5% shocks):")]
    lines += [f"  {e}" for e in events] or [st.dim("  none yet — about 1 per ticker per 10 min")]
    return "\n".join(lines)


# --------------------------------------------------------------------- main


async def run(args: argparse.Namespace) -> int:
    live = sys.stdout.isatty() and not args.plain
    st = Style(enabled=sys.stdout.isatty() and not args.no_color and "NO_COLOR" not in os.environ)

    cache, names, stats = PriceCache(), NameRegistry(), Stats()
    source = SimulatorSource(
        cache,
        update_interval=args.interval,
        seed=args.seed,
        event_rate_per_min=args.event_rate,
    )
    history: dict[str, deque[int]] = {t: deque(maxlen=SPARK_WIDTH) for t in DEFAULT_TICKERS}
    events: deque[str] = deque(maxlen=5)
    seen_events = 0

    await source.start(DEFAULT_TICKERS)
    for q in cache.changed_since(0):  # initial snapshot
        stats.check(q, names.get(q.ticker))
        stats.last_version = max(stats.last_version, q.version)
        history[q.ticker].append(q.price)

    start = time.monotonic()
    next_snapshot = 0.0
    if live:
        sys.stdout.write("\x1b[?25l")  # hide cursor
    try:
        while (elapsed := time.monotonic() - start) < args.duration:
            await asyncio.sleep(0.1)
            for q in cache.changed_since(stats.last_version):
                stats.check(q, names.get(q.ticker))
                stats.last_version = q.version
                stats.updates[q.ticker] = stats.updates.get(q.ticker, 0) + 1
                stats.ups += q.direction == "up"
                stats.downs += q.direction == "down"
                history[q.ticker].append(q.price)

            fresh = min(source.event_count - seen_events, len(source.events))
            seen_events = source.event_count
            for t, pct in list(source.events)[len(source.events) - fresh :]:
                price = cache.price(t)
                events.appendleft(
                    st.dim(time.strftime("%H:%M:%S"))
                    + "  "
                    + st.by_sign(pct, f"{'▲' if pct > 0 else '▼'} {t} {names.get(t)} {pct:+.2f}%")
                    + (f"  → {krw(price)}" if price else "")
                )

            frame = render(
                st, cache, names, history, events, stats, elapsed, args.duration, args.seed
            )
            if live:
                sys.stdout.write("\x1b[H\x1b[J" + frame + "\n")
                sys.stdout.flush()
            elif elapsed >= next_snapshot:
                print(frame + "\n", flush=True)
                next_snapshot += args.snapshot_every
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await source.stop()
        if live:
            sys.stdout.write("\x1b[?25h")

    if not live:  # final frame for piped output
        print(
            render(
                st, cache, names, history, events, stats, args.duration, args.duration, args.seed
            )
        )
    return report(st, stats)


def report(st: Style, stats: Stats) -> int:
    total = sum(stats.updates.values())
    silent = [t for t in DEFAULT_TICKERS if not stats.updates.get(t)]
    checks = [
        (total > 0, f"simulator produced live updates ({total} total)"),
        (not silent, "every ticker moved" + (f" (silent: {', '.join(silent)})" if silent else "")),
        (
            stats.ups > 0 and stats.downs > 0,
            f"prices moved both ways ({stats.ups} up, {stats.downs} down)",
        ),
        (
            not stats.failures,
            "every quote: int KRW, on tick grid, inside ±30% band, valid SSE payload",
        ),
    ]
    print("\n" + st.bold("Checks"))
    for ok, label in checks:
        print(f"  {st.green('PASS') if ok else st.red('FAIL')}  {label}")
    for f in stats.failures:
        print("        " + st.red(f))
    passed = all(ok for ok, _ in checks)
    print(
        "\n"
        + (
            st.green(st.bold("Market data simulator is working."))
            if passed
            else st.red(st.bold("Market data simulator check FAILED."))
        )
    )
    return 0 if passed else 1


def main() -> None:
    p = argparse.ArgumentParser(description="FinAlly Market Data Demo (terminal)")
    p.add_argument("-d", "--duration", type=float, default=30, help="seconds to run (default 30)")
    p.add_argument("--seed", type=int, default=None, help="SIM seed for a reproducible run")
    p.add_argument(
        "--interval", type=float, default=0.5, help="simulator step in seconds (default 0.5)"
    )
    p.add_argument(
        "--event-rate", type=float, default=0.1, help="jumps per ticker per minute (default 0.1)"
    )
    p.add_argument(
        "--plain", action="store_true", help="print snapshots instead of redrawing in place"
    )
    p.add_argument(
        "--snapshot-every", type=float, default=5, help="seconds between snapshots in plain mode"
    )
    p.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    args = p.parse_args()
    try:
        sys.exit(asyncio.run(run(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
