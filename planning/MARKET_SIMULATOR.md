# Market Data Simulator — Design

**Status:** Implemented 2026-11-17 (see `MARKET_DATA_SUMMARY.md`); originally the design for the Market Data agent · **Date:** 2026-11-16
**Related:** [`PLAN.md`](PLAN.md) §6–7, [`MARKET_DATA_INTERFACE.md`](MARKET_DATA_INTERFACE.md), [`MARKET_DATA_SOURCES.md`](MARKET_DATA_SOURCES.md)

The simulator is FinAlly's **default** price source. It must:
- look like a live KRX tape: integer KRW prices on real tick sizes, correlated sector moves, occasional dramatic jumps;
- stay stable for hours of demo time;
- be fully deterministic under test.

It implements `MarketDataSource` from `MARKET_DATA_INTERFACE.md` and writes only to the `PriceCache`.

---

## 1. Model at a glance

Each step (Δt = 0.5 s wall-clock), for every tracked ticker *i*:

```
log-return_i =  μ_i·Δτ − ½σ_i²·Δτ                         (GBM drift with Itô correction)
              + σ_i·√Δτ · ( β_m·Z_market + β_s·Z_sector(i) + β_e·ε_i )   (correlated shock)
              − κ_i·(x_i − x̄_i)·Δt                         (weak mean-reversion, wall-clock)
              + J_i                                          (rare jump event)

x_i ← x_i + log-return_i        (x = log of the internal "true" price, a float)
published price = snap_to_tick( clamp( exp(x_i), ±30% of session_open ) )
```

| Symbol | Meaning |
|---|---|
| Δτ | Market time per step = Δt × `TIME_SCALE` / seconds-per-trading-year (§2) |
| Z_market, Z_sector, ε_i | Independent standard normals; one Z_market per step, one Z_sector per sector per step |
| β_m² + β_s² + β_e² = 1 | Keeps σ_i equal to the ticker's total volatility |
| κ_i | Mean-reversion speed toward log seed price x̄_i (§5) |
| J_i | Event jump: usually 0, occasionally ±2–5 % (§4) |

The building blocks:
- **Geometric Brownian motion (GBM)** — the standard model of stock prices. Log-returns are normal; prices stay positive and move proportionally.
- A **one-factor-plus-sector** correlation structure. It is simpler than a full Cholesky decomposition and handles tickers added at runtime.
- A **Poisson jump** term in the spirit of Merton jump-diffusion, for "drama".
- An **Ornstein–Uhlenbeck pull** on log-price, so a demo that runs all afternoon doesn't drift to the ±30% limit.

---

## 2. Time scaling: why realistic volatility is too boring

The first design decision is the most important one.

A trading year on KRX is about 252 days × 6.5 h = **5,896,800 s**. With real-time Δτ = 0.5 s and a realistic σ = 30 %/yr, Samsung (₩75,000) moves about **₩6.6 per step**. But its tick is **₩100**. After snapping to ticks, the displayed price would change roughly once every couple of minutes, and the demo would look dead.

Per-step move (1σ) versus tick size, computed for the seed universe:

| `TIME_SCALE` | Samsung 005930 (tick 100) | SK Hynix 000660 (tick 100) | Samsung Bio 207940 (tick 1,000) | 1 real hour ≈ | 1-h σ (σ=35 %) |
|---|---|---|---|---|---|
| 1 (realistic) | ₩6.6 (0.07 tick) | ₩24 (0.24) | ₩70 (0.07) | 0.15 trading days | 0.9 % |
| 60 | ₩51 (0.51) | ₩183 (1.8) | ₩541 (0.54) | 9 trading days | 6.7 % |
| **200 (default)** | **₩93 (0.93)** | **₩334 (3.3)** | **₩988 (0.99)** | **31 trading days** | **12 %** |
| 600 | ₩161 (1.6) | ₩578 (5.8) | ₩1,712 (1.7) | 92 trading days | 21 % |

**Decision:** `TIME_SCALE = 200` by default (env `SIM_TIME_SCALE`). At this setting:
- most tickers move about 1 tick per step, so the watchlist flickers constantly, like a real tape;
- sparklines show visible structure within a minute;
- σ stays in realistic annual units, so per-ticker parameters remain meaningful.

The mean reversion in §5 keeps the faster clock from running away.

---

## 3. Seed universe and parameters

Seed prices come from PLAN §7. σ is annualized volatility, a rough historical-style figure for each name chosen for plausibility, not precision.

| Ticker | Name | Seed ₩ | Sector | σ | β_m | β_s |
|---|---|---|---|---|---|---|
| 005930 | Samsung Electronics | 75,000 | semis | 0.30 | 0.55 | 0.65 |
| 000660 | SK Hynix | 180,000 | semis | 0.45 | 0.50 | 0.70 |
| 035420 | NAVER | 200,000 | internet | 0.35 | 0.45 | 0.60 |
| 035720 | Kakao | 40,000 | internet | 0.40 | 0.45 | 0.60 |
| 005380 | Hyundai Motor | 230,000 | autos | 0.30 | 0.50 | 0.65 |
| 000270 | Kia | 100,000 | autos | 0.30 | 0.50 | 0.65 |
| 373220 | LG Energy Solution | 350,000 | battery | 0.45 | 0.45 | 0.65 |
| 005490 | POSCO Holdings | 300,000 | battery | 0.40 | 0.50 | 0.55 |
| 207940 | Samsung Biologics | 800,000 | bio | 0.30 | 0.35 | 0.60 |
| 068270 | Celltrion | 200,000 | bio | 0.35 | 0.35 | 0.60 |
| *(any other)* | — | derived (§8) | other | 0.40 | 0.45 | 0.00 |

β_e is derived: `β_e = sqrt(1 − β_m² − β_s²)`. For Samsung that is `sqrt(1 − 0.3025 − 0.4225) ≈ 0.52`.

**Implied correlations:**
- Same sector: ρ = β_m,i·β_m,j + β_s,i·β_s,j. Samsung–SK Hynix ≈ 0.55·0.50 + 0.65·0.70 = **0.73**.
- Different sectors: ρ = β_m,i·β_m,j. Samsung–NAVER ≈ **0.25**.

This gives the PLAN behaviour: semiconductor stocks move together, and the market factor gives the whole board a common "mood". POSCO Holdings is placed in the battery-materials group because of its lithium/cathode exposure; it could equally go in "steel/materials". Drift is μ = 0.05 for all tickers. At these time scales drift is negligible next to noise, but it keeps the model honest.

The parameter table lives in code as a dict (`SEED_PARAMS`), not in the DB.

---

## 4. Random events (jumps)

PLAN asks for "occasional random 'events' — sudden 2–5% moves on a ticker".

- Each step, each ticker has probability `p_event = λ·Δt`. The default λ = 1/600 per ticker-second, so each ticker has about one event per 10 min. With 10 tickers, the **board sees an event about every minute**.
- Magnitude: `|J| ~ Uniform(0.02, 0.05)`. Sign is ±1 with equal odds, so `J = ln(1 ± |J|)`.
- Optional **sector contagion**: with probability 0.3, peers in the same sector receive 40 % of the jump in the same direction. Example: "SK Hynix +4 % on HBM news, Samsung +1.6 %".
- Events are emitted as a log line (and optionally an internal hook) with `ticker, pct`. The AI chat could later reference "unusual moves". Out of scope for v1.

Env: `SIM_EVENT_RATE` (events per ticker-minute, default 0.1). Set it to `0` to disable.

---

## 5. Mean reversion (keeping long demos sane)

Pure GBM at 200× wanders about 12 % per real hour, so after a long session prices would pin against the ±30 % limit. An OU pull on log-price toward the seed bounds the wander:

```
x_i ← x_i − κ·(x_i − x̄_i)·Δt          (Δt in wall-clock seconds)
stationary std of log-price ≈ σ_real / sqrt(2κ),   σ_real = σ·sqrt(TIME_SCALE / 5,896,800)  per √s
```

Choose κ per ticker so the stationary band is about **±15 % (1σ)**:
`κ = σ_real² / (2·0.15²)`. For σ = 0.35 that gives κ ≈ 9×10⁻⁵ s⁻¹, a half-life of about **2 hours**. Short-term moves look purely random, while hours-long sessions stay within believable ranges. Compute κ from σ and `TIME_SCALE` at construction; don't hard-code it.

x̄_i is the log of the **seed** price, not of `session_open`. In this simulator they are the same, because each server start begins at the seed.

---

## 6. KRX realism layer

### 6.1 Tick snapping
Keep the internal price `exp(x)` as a float. Publish `snap_to_tick(p)` using the KRX table (`MARKET_DATA_SOURCES.md` §2.3):

```python
# ticks.py
_TICKS = ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500))

def tick_size(price: float) -> int:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return 1_000

def snap_to_tick(price: float) -> int:
    t = tick_size(price)
    return max(t, int(round(price / t)) * t)
```

Never feed the snapped price back into the model. If you did, sub-tick moves would be erased every step and the price would stick.

### 6.2 Price limit (±30 %)
After the step, clamp the internal price to `[0.7·session_open, 1.3·session_open]`, then snap.
- Snap the upper bound **down** and the lower bound **up**, so the published price never leaves the band. This is the real "상한가 / 하한가" behaviour.
- When clamped, also clamp `x_i`, so the price doesn't sit beyond the limit internally and then "teleport" back.

### 6.3 Integers only
Everything written to the cache is an `int`. KRW has no subunit in trading.

---

## 7. Update loop

```python
class SimulatorSource(MarketDataSource):
    def __init__(self, cache, update_interval=0.5, time_scale=200.0, seed=None,
                 event_rate_per_min=0.1, clock=time.monotonic):
        super().__init__(cache)
        self._rng = np.random.default_rng(seed)        # seed=None → random; tests pass an int
        self._dt = update_interval
        self._dtau = update_interval * time_scale / 5_896_800
        self._state: dict[str, TickerState] = {}       # x, x_bar, sigma, betas, kappa, sector, session_open
        self._task = None
        ...

    async def start(self, tickers):
        for t in tickers:
            await self.add_ticker(t)                   # writes the seed price immediately
        self._task = asyncio.create_task(self._run())

    async def _run(self):
        next_t = time.monotonic()
        while True:
            self.step()                                # pure, synchronous, ~µs for 50 tickers
            next_t += self._dt
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))   # drift-free cadence

    def step(self) -> None:
        """One simulation step. Public so tests can drive it without asyncio."""
        z_m = self._rng.standard_normal()
        z_s = {s: self._rng.standard_normal() for s in self._sectors()}
        for t, st in self._state.items():
            shock = st.bm * z_m + st.bs * z_s[st.sector] + st.be * self._rng.standard_normal()
            dx = (st.mu - 0.5 * st.sigma**2) * self._dtau + st.sigma * math.sqrt(self._dtau) * shock
            dx -= st.kappa * (st.x - st.x_bar) * self._dt
            dx += self._maybe_jump(t, st)
            st.x = self._clamp_limit(st, st.x + dx)
            price = snap_to_tick(math.exp(st.x))
            if price != self.cache.price(t):           # only publish real changes
                self.cache.update(t, price)
```

Notes:
- **numpy** is the only extra dependency. Python's `random.gauss` would also work for ≤ 50 tickers, and numpy is not strictly required.
- **Drift-free cadence:** sleep until `next_t` rather than a fixed `sleep(0.5)`, so the loop doesn't slowly fall behind.
- **Skip unchanged prices.** About 30–60 % of steps leave a given ticker on the same tick at the default scale. Not writing those keeps SSE frames small and makes `direction` meaningful.
- The simulator runs **24/7** and ignores KRX market hours. That's a demo choice: students run it in the evening. A future `SIM_RESPECT_MARKET_HOURS=true` could freeze prices outside 09:00–15:30 KST.

---

## 8. Tickers added at runtime

When a user adds a ticker that isn't in `SEED_PARAMS`:
1. **Seed price:** look up the bundled listing CSV (`MARKET_DATA_SOURCES.md` §4.5) for a last-close column if the team includes one. Otherwise derive a **deterministic** pseudo-price from the ticker string: `rng = Random(hash_stable(ticker)); price = snap_to_tick(10 ** rng.uniform(3.7, 5.7))`, i.e. about ₩5,000–₩500,000. The same ticker always starts at the same price across restarts. Use `zlib.crc32`, not Python's salted `hash()`.
2. **Parameters:** sector `other`, σ = 0.40, β_m = 0.45, β_s = 0, so it only shares the market factor.
3. **Validation:** the simulator accepts any well-formed code (`^[0-9A-Z]{6}$`), so `add_ticker` always returns `True`. Only the yfinance source can say "unknown ticker".

---

## 9. Configuration

| Env var | Default | Purpose |
|---|---|---|
| `SIM_SEED` | unset (random) | Integer seed. E2E tests set it for reproducible prices. |
| `SIM_TIME_SCALE` | `200` | Market-time speed-up (§2) |
| `SIM_EVENT_RATE` | `0.1` | Events per ticker per minute (§4); `0` disables them |
| `SIM_UPDATE_INTERVAL` | `0.5` | Seconds per step (PLAN: ~500 ms) |

All are optional and should be added to `.env.example` as commented-out lines.

---

## 10. Testing

| Test | Assertion |
|---|---|
| Integer & tick-aligned | 10,000 steps: every published price is `int`, > 0, and `price % tick_size(price) == 0`. |
| Price band | With jumps forced every step, prices stay within `[0.7, 1.3] × session_open` (after snapping). |
| GBM math | With κ = 0, jumps off and `TIME_SCALE` fixed, the sample mean and variance of internal log-returns match `(μ − σ²/2)Δτ` and `σ²Δτ` within tolerance over about 100k steps. Test on internal `x`, not snapped prices. |
| Correlation | The sample correlation of Samsung vs SK Hynix log-returns is about 0.73 ± 0.05; Samsung vs NAVER is about 0.25 ± 0.05. |
| Mean reversion | After a forced +25 % displacement, about half the gap closes within the theoretical half-life (tolerance band). |
| Determinism | Two simulators with `seed=42` produce identical price sequences. |
| Interface conformance | Shared suite from `MARKET_DATA_INTERFACE.md` §11: start prices every ticker; add/remove idempotent; stop idempotent. |
| Unknown ticker | `add_ticker("123456")` returns `True` and gives the same seed price across two instances. |
| Events | With `event_rate` very high, observed single-step jumps fall in the 2–5 % band. |

Unit tests call `step()` directly. Only one smoke test needs the asyncio loop.

---

## 11. What we deliberately do not model

| Not modeled | Why |
|---|---|
| Order book, bid/ask, volume | Market orders fill at the last price (PLAN). There is no order-book UI. |
| VI (volatility interruption) 2-minute auctions | Adds complexity for little demo value |
| Opening/closing auctions, market hours | The demo runs 24/7 |
| Volatility clustering (GARCH) | GBM plus jumps already looks convincingly "alive" |
| Dividends, splits, ex-rights | Irrelevant within a session |

## References
- Black–Scholes/GBM and the Itô drift correction: standard; see any quantitative finance text (e.g. Hull, *Options, Futures, and Other Derivatives*, ch. on Wiener processes).
- Merton (1976), "Option pricing when underlying stock returns are discontinuous": the jump-diffusion idea behind §4.
- Ornstein–Uhlenbeck process: mean-reverting diffusion used in §5.
- KRX tick sizes and ±30 % limit: see `MARKET_DATA_SOURCES.md` §2.
