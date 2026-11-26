"""Optional OpenDART enrichment (PLAN §9 step 3, Q3).

Only active when ``OPENDART_API_KEY`` is set and the message mentions fundamentals.
Fetches ``company.json`` (profile) and ``fnlttSinglAcnt.json`` (revenue, operating
profit, net income) per ticker. Results are cached in memory for 24 h. Every failure
is swallowed — enrichment must never break chat.

``stock_code → corp_code`` comes from ``corpCode.xml`` (a zip), downloaded once and
cached on disk next to the SQLite file.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

BASE_URL = "https://opendart.fss.or.kr/api/"
CACHE_TTL_S = 24 * 3600
MAX_TICKERS = 4
HTTP_TIMEOUT_S = 10

FUNDAMENTAL_KEYWORDS = (
    "revenue", "sales", "profit", "earning", "eps", "valuation", "fundamental",
    "financial", "income", "margin", "p/e", "per ", "balance sheet", "dividend",
    "매출", "실적", "영업이익", "순이익", "이익", "재무", "펀더멘털", "밸류에이션", "배당",
)  # fmt: skip

ACCOUNTS = {"매출액": "revenue", "수익(매출액)": "revenue", "영업이익": "operating_profit",
            "당기순이익": "net_income", "당기순이익(손실)": "net_income"}  # fmt: skip
REPORT_NAMES = {"11011": "annual", "11012": "half-year", "11013": "Q1", "11014": "Q3"}

_TICKER_RE = re.compile(r"(?<![0-9A-Z])([0-9][0-9A-Z]{5})(?![0-9A-Z])")

# (key -> (expires_at, value))
_cache: dict[str, tuple[float, object]] = {}
_corp_codes: dict[str, str] | None = None

Fetcher = Callable[[str, dict], bytes]


def api_key() -> str:
    return os.environ.get("OPENDART_API_KEY", "").strip()


def wants_fundamentals(message: str) -> bool:
    text = message.lower()
    return any(k in text for k in FUNDAMENTAL_KEYWORDS)


def mentioned_tickers(message: str, known: dict[str, str], held: Iterable[str]) -> list[str]:
    """Tickers named by code or by (known) company name in the message, then held ones."""
    upper = message.upper()
    lower = message.lower()
    found: list[str] = []
    for code in _TICKER_RE.findall(upper):
        if code not in found:
            found.append(code)
    for code, name in known.items():
        if name and name.lower() in lower and code not in found:
            found.append(code)
    for code in held:
        if code not in found:
            found.append(code)
    return found[:MAX_TICKERS]


def _http_get(endpoint: str, params: dict) -> bytes:
    url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "finally-app"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310
        return resp.read()


def _corp_code_cache_path() -> Path:
    db_path = os.environ.get("DB_PATH")
    base = Path(db_path).parent if db_path else Path(__file__).resolve().parents[3] / "db"
    return base / "dart_corp_codes.json"


def parse_corp_code_zip(blob: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    root = ElementTree.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        corp = (item.findtext("corp_code") or "").strip()
        if stock and corp:
            mapping[stock] = corp
    return mapping


def load_corp_codes(key: str, fetch: Fetcher = _http_get) -> dict[str, str]:
    global _corp_codes
    if _corp_codes is not None:
        return _corp_codes
    path = _corp_code_cache_path()
    try:
        if path.exists() and time.time() - path.stat().st_mtime < 30 * 86400:
            _corp_codes = json.loads(path.read_text("utf-8"))
            return _corp_codes
    except Exception:  # corrupt cache → refetch
        logger.debug("ignoring unreadable DART corp-code cache", exc_info=True)
    mapping = parse_corp_code_zip(fetch("corpCode.xml", {"crtfc_key": key}))
    _corp_codes = mapping
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping), "utf-8")
    except Exception:
        logger.debug("could not write DART corp-code cache", exc_info=True)
    return mapping


def _report_candidates(today: date) -> list[tuple[str, str]]:
    """Most-recent-first (year, reprt_code) guesses; filings lag the period by ~45-90 days."""
    y = today.year
    return [(str(y), "11014"), (str(y), "11012"), (str(y), "11013"),
            (str(y - 1), "11011"), (str(y - 1), "11014")]  # fmt: skip


def _parse_amount(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s.replace(",", "").strip())
    except ValueError:
        return None


def fetch_company_summary(
    ticker: str, key: str, fetch: Fetcher = _http_get, today: date | None = None
) -> dict | None:
    corp_code = load_corp_codes(key, fetch).get(ticker)
    if not corp_code:
        return None
    summary: dict = {"ticker": ticker}

    profile = json.loads(fetch("company.json", {"crtfc_key": key, "corp_code": corp_code}))
    if profile.get("status") == "000":
        summary["name"] = display_name(profile.get("corp_name_eng") or "") or profile.get(
            "corp_name"
        )
        summary["industry_code"] = profile.get("induty_code")
        summary["established"] = profile.get("est_dt")

    for year, rcode in _report_candidates(today or date.today()):
        data = json.loads(
            fetch(
                "fnlttSinglAcnt.json",
                {"crtfc_key": key, "corp_code": corp_code, "bsns_year": year, "reprt_code": rcode},
            )
        )
        if data.get("status") != "000" or not data.get("list"):
            continue
        rows = data["list"]
        # Prefer consolidated (CFS) statements, else separate (OFS).
        cfs = [r for r in rows if r.get("fs_div") == "CFS"]
        financials: dict[str, int] = {}
        for r in cfs or rows:
            field = ACCOUNTS.get((r.get("account_nm") or "").strip())
            amount = _parse_amount(r.get("thstrm_amount"))
            if field and amount is not None and field not in financials:
                financials[field] = amount
        if financials:
            summary["period"] = f"{year} {REPORT_NAMES.get(rcode, rcode)}"
            summary["financials_krw"] = financials
            break
    return summary if len(summary) > 1 else None


def _cached_summary(ticker: str, key: str, fetch: Fetcher) -> dict | None:
    now = time.time()
    hit = _cache.get(ticker)
    if hit and hit[0] > now:
        return hit[1]  # type: ignore[return-value]
    try:
        value = fetch_company_summary(ticker, key, fetch)
    except Exception:
        logger.info("OpenDART lookup failed for %s", ticker, exc_info=True)
        value = None
    _cache[ticker] = (now + CACHE_TTL_S, value)
    return value


def format_summaries(summaries: list[dict]) -> str:
    lines = ["COMPANY FUNDAMENTALS (OpenDART, KRW):"]
    for s in summaries:
        head = f"- {s['ticker']} {s.get('name', '')}".rstrip()
        fin = s.get("financials_krw") or {}
        parts = [f"{k.replace('_', ' ')} ₩{v:,}" for k, v in fin.items()]
        if parts:
            head += f" — {s.get('period', '')} report: " + ", ".join(parts)
        lines.append(head)
    return "\n".join(lines)


async def enrichment(
    message: str,
    known_names: dict[str, str],
    held: Iterable[str],
    fetch: Fetcher = _http_get,
) -> str | None:
    """Return a context block of fundamentals, or None. Never raises."""
    try:
        key = api_key()
        if not key or not wants_fundamentals(message):
            return None
        tickers = mentioned_tickers(message, known_names, held)
        if not tickers:
            return None

        def work() -> list[dict]:
            return [s for t in tickers if (s := _cached_summary(t, key, fetch))]

        summaries = await asyncio.to_thread(work)
        return format_summaries(summaries) if summaries else None
    except Exception:
        logger.info("OpenDART enrichment failed", exc_info=True)
        return None


def _reset_for_tests() -> None:
    global _corp_codes
    _cache.clear()
    _name_cache.clear()
    _corp_codes = None


_name_cache: dict[str, str | None] = {}

_SUFFIX_RE = re.compile(
    r"[\s,.]*\b(?:CO\s*[.,]*\s*,?\s*LTD|COMPANY\s+LIMITED|COMPANY|CORPORATION|CORP|"
    r"INCORPORATED|INC|LIMITED|LTD|PLC)\b[\s,.]*$",
    re.IGNORECASE,
)


# Brand names / acronyms that stay upper-case when title-casing an all-caps name.
KEEP_UPPER = frozenset(
    {"NAVER", "POSCO", "KCC", "BNK", "DGB", "HMM", "KT&G", "S-OIL", "SKC", "LIG", "KEPCO",
     "HDC", "OCI", "DL", "ESG", "IT", "AI", "KRX", "KOSPI", "KOSDAQ", "BGF", "SPC"}
)  # fmt: skip


def _title_token(tok: str) -> str:
    # Keep short acronyms (SK, LG, KB, CJ), known brands and alphanumeric codes as-is.
    if len(tok) <= 2 or tok in KEEP_UPPER or any(ch.isdigit() for ch in tok):
        return tok
    return "-".join(part[:1].upper() + part[1:].lower() for part in tok.split("-"))


def display_name(raw: str) -> str | None:
    """'SAMSUNG ELECTRONICS CO,.LTD' -> 'Samsung Electronics'.

    Trims trailing corporate suffixes and title-cases names that are all caps.
    """
    name = " ".join((raw or "").split())
    prev = None
    while name and name != prev:  # strip stacked suffixes ("... CO., LTD.")
        prev = name
        name = _SUFFIX_RE.sub("", name).strip(" ,.")
    if not name:
        return None
    letters = [c for c in name if c.isalpha()]
    if letters and all(c.isupper() for c in letters if c.isascii()):
        name = " ".join(_title_token(t) for t in name.split(" "))
    return name


async def resolve_name(ticker: str, fetch: Fetcher = _http_get) -> str | None:
    """Name resolver for ``PortfolioService.add_name_resolver``: OpenDART ``corp_name_eng``.

    Returns None when no key is configured or on any failure.
    """
    key = api_key()
    if not key:
        return None
    if ticker in _name_cache:
        return _name_cache[ticker]

    def work() -> str | None:
        corp_code = load_corp_codes(key, fetch).get(ticker)
        if not corp_code:
            return None
        data = json.loads(fetch("company.json", {"crtfc_key": key, "corp_code": corp_code}))
        if data.get("status") != "000":
            return None
        return display_name(data.get("corp_name_eng") or "")

    try:
        name = await asyncio.to_thread(work)
    except Exception:
        logger.info("OpenDART name lookup failed for %s", ticker, exc_info=True)
        return None
    _name_cache[ticker] = name
    return name
