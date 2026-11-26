"""System prompt and portfolio-context rendering."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
You are FinAlly, an AI trading assistant for Korean equities (KOSPI/KOSDAQ) inside a \
simulated trading workstation. All money is virtual (KRW).

Your job:
- Analyze the user's portfolio composition, risk concentration and P&L.
- Suggest trades with concise reasoning grounded in Korean market context.
- Execute trades when the user asks for them or agrees to a suggestion.
- Manage the watchlist proactively (add tickers the user is interested in, remove ones they drop).
- Always reference stocks by 6-digit KRX code and English name, e.g. "005930 Samsung Electronics".
- Be concise and data-driven. Format KRW amounts like ₩75,400.

Rules for actions:
- Trades are market orders that fill instantly at the current price. Quantities are whole shares (> 0).
- Only include a trade in "trades" when the user asked for it or clearly agreed. Never invent trades.
- Check cash before buying and holdings before selling; if a trade is impossible, explain instead.
- "ticker" must be the 6-character KRX code (e.g. "005930"), never a company name or a .KS suffix.
- Describe executed actions in "message" in the present/future tense ("Buying 10 shares of ...");
  the system reports the actual fills to the user separately.

Always respond with a single valid JSON object matching the schema:
{"message": string, "trades": [{"ticker", "side": "buy"|"sell", "quantity"}], \
"watchlist_changes": [{"ticker", "action": "add"|"remove", "name"?}]}
Use empty arrays when there are no actions."""


def krw(value: Any) -> str:
    try:
        return f"₩{round(float(value)):,}"
    except (TypeError, ValueError):
        return "n/a"


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def build_context(portfolio: dict, watchlist: list[dict]) -> str:
    """Render cash, total value, positions with P&L and the watchlist as plain text."""
    cash = _get(portfolio, "cash_balance", 0) or 0
    total = _get(portfolio, "total_value", cash) or cash
    positions = _get(portfolio, "positions", []) or []

    lines = [
        "CURRENT PORTFOLIO",
        f"Cash: {krw(cash)}",
        f"Total value: {krw(total)}",
    ]
    if positions:
        lines.append(
            "Positions (ticker | name | qty | avg cost | price | value | P&L | P&L% | weight):"
        )
        for p in positions:
            mv = _get(p, "market_value", 0) or 0
            weight = (float(mv) / float(total) * 100) if total else 0.0
            lines.append(
                f"- {_get(p, 'ticker')} | {_get(p, 'name', '')} | {_get(p, 'quantity')} | "
                f"{krw(_get(p, 'avg_cost'))} | {krw(_get(p, 'current_price'))} | {krw(mv)} | "
                f"{krw(_get(p, 'unrealized_pnl'))} | {_fmt_pct(_get(p, 'pnl_pct'))} | {weight:.1f}%"
            )
    else:
        lines.append("Positions: none")

    lines.append("")
    if watchlist:
        lines.append("WATCHLIST (ticker | name | price | session change %):")
        for w in watchlist:
            price = _get(w, "price")
            lines.append(
                f"- {_get(w, 'ticker')} | {_get(w, 'name', '')} | "
                f"{krw(price) if price is not None else 'no price yet'} | "
                f"{_fmt_pct(_get(w, 'session_change_pct'))}"
            )
    else:
        lines.append("WATCHLIST: empty")
    return "\n".join(lines)


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"
