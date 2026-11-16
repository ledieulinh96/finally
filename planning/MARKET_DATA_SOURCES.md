# Korean Market Data Sources — Research

**Status:** Research reference for the Market Data agent · **Date:** 2026-11-16
**Related:** [`PLAN.md`](PLAN.md) §6, [`MARKET_DATA_INTERFACE.md`](MARKET_DATA_INTERFACE.md), [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md)

This document surveys the ways FinAlly can obtain prices for KOSPI/KOSDAQ stocks, summarizes the Korean market rules that affect a price feed, and recommends what to build.

> **Verification note.** Facts marked ✅ were confirmed from official or primary sources during research. Facts marked ⚠️ come from secondary sources (blogs, wrappers, news) and must be checked against the provider's official docs before coding against them.

---

## 1. Recommendation (TL;DR)

| Role | Choice | Why |
|---|---|---|
| **Default price feed** | Built-in simulator | Offline, deterministic, no keys, no rate limits. Unchanged from PLAN. |
| **Optional "real" feed** | `yfinance` (`USE_YFINANCE=true`) | No account or key; covers every KRX listing via `.KS` / `.KQ`. Delayed ~15–20 min. |
| **Company names / exchange lookup** | Bundled KRX listing snapshot, refreshed via `FinanceDataReader` (optional) → yfinance `shortName` fallback | Avoids an extra network round-trip per add; knows KOSPI vs KOSDAQ up front (resolves PLAN Q1). |
| **Fundamentals (AI enrichment)** | OpenDART (`OPENDART_API_KEY`) | Official FSS disclosure API; free with a key. Unchanged from PLAN. |
| **Future: true real-time** | KIS Developers (한국투자증권) WebSocket | The most widely used retail real-time API, but it needs a Korean brokerage account, so it stays out of scope for v1. |

Three corrections to PLAN.md:

1. **Delay wording.** Yahoo's own exchange list states a **20-minute** delay for Korea Stock Exchange (`.KS`) and KOSDAQ (`.KQ`) quotes ✅. PLAN says "15-min delayed". Use "~15–20 min delayed" in the UI and docs.
2. **Market hours.** Real prices only move during trading sessions. Outside them, yfinance returns the last close, so with `USE_YFINANCE=true` the UI shows flat prices for most of the day (see §2.1). The UI should show a "Market closed" badge rather than look broken.
3. **Company names.** OpenDART's `corp_name` is Korean. PLAN wants English names, so use `corp_name_eng` from OpenDART `company.json` (see §4.4).

---

## 2. Korean market facts that affect a price feed

### 2.1 Trading sessions (KST, UTC+9)

| Venue | Session | Time | Notes |
|---|---|---|---|
| KRX | Opening single-price auction | 08:30–09:00 | Orders accumulate; one opening price at 09:00 ✅ |
| KRX | Continuous trading | 09:00–15:20 | ✅ KRX official |
| KRX | Closing single-price auction | 15:20–15:30 | ✅ KRX official |
| KRX | After-market | 16:00–20:00 | Launched **2026-09-14** ⚠️ (news, Asiae/Herald). Covers most listed stocks; same VI rules as the regular session. |
| NXT (Nextrade, ATS) | Pre / main / after | 08:00–20:00 | Korea's first alternative exchange, live since **2025-03-04** ⚠️. Trades a selected subset of large-cap names only. Pauses during KRX auction windows. |

Implications:
- A "real" feed is quiet outside roughly 08:00–20:00 KST, on weekends and on KRX holidays.
- Multi-venue trading means "the price" can differ slightly between KRX and NXT. yfinance reports the KRX price, which is fine for this project.
- The simulator ignores the clock and trades 24/7. This is a deliberate demo choice (see `MARKET_SIMULATOR.md`).

### 2.2 Daily price limit
- **±30% of the base price**, which is normally the previous day's close. This applies on KOSPI, KOSDAQ and NXT ✅ (KRX global site; Hanwha WM guide). Stocks in liquidation trading (정리매매) are exempt.
- The simulator enforces this band around `session_open` (see `MARKET_SIMULATOR.md` §6).

### 2.3 Tick sizes (호가가격단위) — KOSPI, KOSDAQ and NXT share one table

| Price (KRW) | Tick |
|---|---|
| < 2,000 | 1 |
| 2,000 – < 5,000 | 5 |
| 5,000 – < 20,000 | 10 |
| 20,000 – < 50,000 | 50 |
| 50,000 – < 200,000 | 100 |
| 200,000 – < 500,000 | 500 |
| ≥ 500,000 | 1,000 |

Source: Korea Investment & Securities trading guide ⚠️. The page is undated. The table matches the unified KOSPI/KOSDAQ schedule introduced in 2023, but confirm it against krx.co.kr before treating it as authoritative.

**Why it matters:** real KRX prices are always integers on a tick boundary. Samsung at ₩75,000 moves in ₩100 steps, never ₩75,037. The simulator should publish tick-snapped prices so the demo looks authentic.

### 2.4 Volatility Interruption (VI)
- **Dynamic VI:** the price moves about ±3–6% from the previous trade. **Static VI:** the price moves ±10% from a reference price. Either one switches the stock to a **2-minute single-price auction** ✅ (KRX global site; Asiae 2026-09).
- FinAlly does not model VI. It is mentioned here so that "price frozen for ~2 minutes after a big jump" in real data is not mistaken for a bug.

### 2.5 Identifiers
- **Short code (단축코드):** 6 digits, e.g. `005930`. This is FinAlly's internal ticker key.
- **ISIN:** e.g. `KR7005930003`. Used by data.go.kr; not needed in FinAlly.
- **Leading zeros matter.** Always store and transmit tickers as `str`, never `int`.
- KRX has started issuing alphanumeric short codes for some newer listings and products ⚠️ (not verified in this research). Validate with `^[0-9A-Z]{6}$`, not `^\d{6}$`, to be safe.

---

## 3. Source comparison

| Source | Real-time? | Key / account | Cost | Coverage | Fit for FinAlly |
|---|---|---|---|---|---|
| **yfinance** (Yahoo, unofficial) | No, ~20 min delay | None | Free | All KRX listings (`.KS` / `.KQ`) | ✅ Optional feed (PLAN) |
| **KIS Developers** (한국투자증권 Open API) | Yes, WebSocket ticks | KIS brokerage account + app key/secret | Free with account | KRX + NXT, domestic & overseas | 🔜 Future "pro" feed |
| **Kiwoom REST API** (키움증권) | Yes, WebSocket | Kiwoom account + app key | Free with account | Domestic | Alternative to KIS (launched 2025-03) ⚠️ |
| **Toss Securities Open API** | Yes (reported) | Toss account | — | Domestic | Emerging (2026) ⚠️; not evaluated |
| **KRX Open API** (openapi.krx.co.kr) | No, end-of-day | KRX account + approved key | Free | Official EOD, indices | Possible EOD seed source |
| **data.go.kr — FSC 주식시세정보** (dataset 15094806) | No, prior-day close (T+1) | data.go.kr service key | Free | All listed stocks | Possible EOD seed source |
| **FinanceDataReader** (Python) | No, EOD/history | None | Free | Listings + history (KRX/Naver/Yahoo) | ✅ Listing snapshot & seed prices |
| **pykrx** (Python) | No, EOD/history | Some endpoints may need KRX login ⚠️ | Free | Prices, market cap, PER/PBR, investor flows | Optional; heavier than FDR |
| **OpenDART** | n/a (no prices) | OpenDART key | Free | Disclosures, financials, company profile | ✅ AI enrichment (PLAN) |

Not recommended:
- **Scraping Naver Finance** or `data.krx.co.kr` HTML/CSV. These pages are fragile and against the sites' terms. One report says bulk CSV on `data.krx.co.kr` returns 403 without login since mid-2026 ⚠️.
- **Paid aggregators** (EODHD, Twelve Data, marketplace proxies). They add cost and a third party, with no benefit for a demo.

---

## 4. Details per source

### 4.1 yfinance (optional feed, PLAN §6)

**Symbol mapping.** `005930` → `005930.KS` (KOSPI), `247540` → `247540.KQ` (KOSDAQ). The KRX listing tells us which suffix to use (§4.5). Otherwise try `.KS` first and fall back to `.KQ` (PLAN Q1).

**Recommended calls**
```python
import yfinance as yf

# Batch quote poll: one HTTP round-trip for all symbols
data = yf.download(
    tickers=["005930.KS", "000660.KS"],
    period="1d", interval="1m",
    group_by="ticker", progress=False, threads=False, auto_adjust=False,
)
# last price per symbol = last non-NaN "Close" in each sub-frame

# Single-symbol helpers (validation / name lookup on add)
t = yf.Ticker("005930.KS")
t.fast_info["last_price"]        # float; may be None if symbol unknown
t.fast_info["previous_close"]
t.info.get("shortName")          # e.g. "SamsungElec" — terse, slow (scrapes quoteSummary)
```

Practical notes:
- **Run in a thread.** yfinance is synchronous. Use `await asyncio.to_thread(...)` so the event loop is never blocked.
- **Batch, don't loop.** One `yf.download` per 15 s cycle for N tickers. Calling `Ticker(...)` N times per cycle invites rate limiting.
- **Rate limits are undocumented.** Yahoo throttles or blocks IPs that send too many requests, sometimes without warning ⚠️. Mitigations:
  - poll every 15 s (PLAN);
  - back off exponentially on errors, from 15 s up to 5 min;
  - never call `.info` in the polling loop.
- **Prices are floats** such as `75400.0`. Round with `int(round(x))`. Optionally snap to the tick table (§2.3) to absorb float noise.
- **Missing or delisted symbols** return an all-NaN frame or raise. Skip the ticker and keep the last cached price (PLAN).
- **`shortName` is terse and inconsistent** ("SamsungElec", "SK hynix"). Prefer the listing snapshot or OpenDART `corp_name_eng` for display names.
- **Session open:** use the first price received after the server starts, per PLAN. `previous_close` is also available if the team ever wants "day change %" instead of "session change %".
- **Terms:** Yahoo data is meant for personal, non-commercial use. That is acceptable for a course project, but document it.

### 4.2 KIS Developers — 한국투자증권 Open API (future real-time option)

Official portal: `apiportal.koreainvestment.com`. Official samples: `github.com/koreainvestment/open-trading-api`.

| Item | Value |
|---|---|
| REST (live) | `https://openapi.koreainvestment.com:9443` ⚠️ |
| REST (paper / 모의투자) | `https://openapivts.koreainvestment.com:29443` ⚠️ |
| WebSocket (live / paper) | `ws://ops.koreainvestment.com:21000` / `:31000` ⚠️ |
| REST auth | `POST /oauth2/tokenP` with `appkey`, `appsecret` → `access_token` |
| WebSocket auth | `POST /oauth2/Approval` with `appkey` and **`secretkey`** (not `appsecret`, a common pitfall) → `approval_key` ⚠️ |
| Real-time trade tick | `tr_id = H0STCNT0`, `tr_key = <6-digit code>`; `tr_type` `1` = subscribe, `2` = unsubscribe |
| Real-time order book | `H0STASP0` |
| Message frame | `flag|tr_id|count|body`. `flag` is `0` for plain text, `1` for encrypted. The body is `^`-delimited, and one frame may hold several records. Control messages are JSON. |
| `H0STCNT0` fields | `[0]` code, `[1]` time HHMMSS, `[2]` current price, `[3]` change sign, `[4]` change, `[5]` change %, `[7..9]` open/high/low, `[12]` trade qty, `[13]` cumulative volume ⚠️ |
| Keep-alive | The server sends `PINGPONG`; echo it back unchanged or the connection drops ⚠️ |
| Limits | REST has a per-second cap (error `EGW00201` when exceeded). WebSocket allows a limited number of registrations per session. Both numbers are commonly reported as about 20 req/s (live) and about 40 subscriptions, **but they were not verified**. Check the portal. |

**Why not in v1:**
- It needs a Korean brokerage account and app registration, which most course students won't have.
- Paper-trading accounts reportedly have restricted real-time coverage ⚠️.

The `MarketDataSource` interface is designed so that a `KisWebSocketSource` can be added later without touching the cache, SSE or frontend (see `MARKET_DATA_INTERFACE.md` §8).

### 4.3 Kiwoom REST API (alternative real-time option)
- Launched **2025-03-24**, replacing the Windows-only OCX OpenAPI+ ✅ (Asiae).
- WebSocket at `wss://api.kiwoom.com:10000/api/dostk/websocket`, with a mock-trading host `mockapi.kiwoom.com` ⚠️.
- Protocol: send `LOGIN` with the token, then `REG` with the stock code and type `0B` (trade). Responses use numeric FID keys ⚠️.
- About 40 real-time registrations per connection ⚠️.
- Official Python samples: `github.com/Kiwoom-Securities/Kiwoom-REST-API` ⚠️.
- Same account barrier as KIS. Listed here for completeness.

### 4.4 OpenDART (fundamentals and names; already in PLAN)
- Base URL: `https://opendart.fss.or.kr/api/`. Authentication is the `crtfc_key` query param.
- **Daily cap of about 20,000 calls per key ⚠️.**
- `corpCode.xml` is a zip file mapping **`stock_code` (6-digit) → `corp_code` (8-digit)**. Every other endpoint needs `corp_code`. Download it once at startup or on first use and cache it on disk. Listed companies have a non-empty `stock_code`.
- `company.json?corp_code=` returns `corp_name` (Korean), **`corp_name_eng`**, `stock_code`, `induty_code`, `est_dt`, CEO, homepage. Use this for the English display name.
- `fnlttSinglAcnt.json?corp_code=&bsns_year=&reprt_code=` returns key financial statement accounts (revenue, operating profit, net income). Report codes: `11011` annual, `11012` half-year, `11013` Q1, `11014` Q3.
- `list.json?corp_code=&bgn_de=&end_de=` returns recent disclosure filings (material events, earnings).
- Recommended answer to **PLAN Q3**: profile + key financials (`company.json` + `fnlttSinglAcnt.json`) for v1. Add recent filings (`list.json`) only if time allows.

### 4.5 Listing snapshot (names + KOSPI/KOSDAQ) — resolves PLAN Q1
`FinanceDataReader.StockListing("KRX")` returns every listed stock with `Code`, `Name` (Korean), and `Market` (`KOSPI` / `KOSDAQ` / `KONEX`).

Recommended approach:
1. Ship a small **bundled CSV** at `backend/schema/krx_listing.csv` with `ticker, name_en, market`. Generate it once with a script, so runtime needs no network.
2. On `POST /api/watchlist`, look up the ticker there. The `market` column gives the yfinance suffix directly, and the CSV gives the English name.
3. If the ticker is unknown (a new listing), fall back to `.KS` then `.KQ` probing, and use the yfinance `shortName` for the name.

This makes the `name` field in `POST /api/watchlist` optional (a Gemini review finding). The backend can resolve it itself.

### 4.6 EOD sources (KRX Open API, data.go.kr)
- **data.go.kr FSC 주식시세정보 (15094806)** ✅ provides prior-day closing data for all stocks, as REST with JSON or XML, free with a service key. Query params include `basDt` / `endBasDt`, `likeSrtnCd`, `isinCd` and `itmsNm`.
- **KRX Open API** provides official EOD data after an approval-based key request at openapi.krx.co.kr ⚠️.
- Neither is needed for v1. Both are possible sources for "refresh the simulator's seed prices to yesterday's close", which would be a nice touch.

---

## 5. Answers to open questions in PLAN.md

| # | Question | Recommendation |
|---|---|---|
| Q1 | KOSPI vs KOSDAQ suffix | Use the bundled listing snapshot (§4.5), which knows the market. Fall back to `.KS`, then `.KQ`. Cache the resolved symbol per ticker. |
| Q2 | Fractional shares | Enforce **positive integer** quantity at the API layer (Pydantic `conint(gt=0)`), matching KRX rules. The `REAL` column type can stay. |
| Q3 | OpenDART scope | Company profile and key financials for v1; disclosures list optional (§4.4). |

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Yahoo throttles or blocks the IP | yfinance mode freezes prices | Exponential back-off; keep last prices; surface `status: "degraded"` in `/api/health`. Simulator remains the default. |
| yfinance breaking change (it has broken several times before) | yfinance mode fails | Pin the version in `uv.lock`; isolate it behind the interface; unit-test the parser with recorded fixtures. |
| Students run during KST night | "Real" prices are flat | Show a "Market closed" badge; the default simulator is unaffected. |
| Ticker codes with letters | Validation rejects valid codes | Validate with `^[0-9A-Z]{6}$`. |

---

## Sources
- Yahoo — [Exchanges and data providers on Yahoo Finance](https://help.yahoo.com/kb/finance/SLN2310.html)
- KRX Global — [Price limit / base price](https://global.krx.co.kr/contents/GLB/06/0602/0602020202/GLB0602020202T2.jsp), [Trading sessions / VI](https://global.krx.co.kr/contents/GLB/06/0602/0602020204/GLB0602020204T7.jsp)
- Hanwha WM — [복수시장 주식거래 안내](https://www.hanwhawm.com/main/center/info/CS181_3p.cmd)
- Korea Investment & Securities — [호가가격단위 안내](https://securities.koreainvestment.com/main/customer/tradetransfer/_static/TF04da010000.jsp)
- Asiae — [KRX after-market debut and VI triggers (2026-09)](https://view.asiae.co.kr/en/article/2026091518034132669); [Kiwoom REST API launch (2025-03)](https://www.asiae.co.kr/en/article/2025032415230534675)
- Herald — [VI triggers surge in after-market](https://biz.heraldcorp.com/article/10874639)
- Newsis — [넥스트레이드 출범 (2025-02)](https://www.newsis.com/view/NISX20250214_0003065753); Shinhan — [NXT policy guide](https://open.shinhansec.com/mobilealpha/html/CS/NXTPolicyGuide_v2.html)
- AlgoLab — [KIS WebSocket real-time quotes (2026)](https://algolab.co.kr/blog/kis-api-websocket-realtime-quote-2026), [Kiwoom REST WebSocket (2026)](https://algolab.co.kr/blog/kiwoom-rest-api-realtime-websocket-0b-0d-2026)
- data.go.kr — [FSC Information on stock market prices (15094806)](https://www.data.go.kr/en/data/15094806/openapi.do)
- GitHub — [FinanceDataReader](https://github.com/FinanceData/FinanceDataReader), [kiwoom-rest-api wrapper](https://github.com/bamjun/kiwoom-rest-api)
- DEV — [yfinance alternatives 2026](https://dev.to/tildalice/yfinance-alternatives-2026-7-free-apis-compared-o4g)
