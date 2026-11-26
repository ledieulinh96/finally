import { formatKRW, formatKRWCompact, formatPct, formatSignedKRW, isValidTicker, normalizeTicker } from "@/lib/format";

describe("KRW formatting", () => {
  it("prefixes ₩ and groups thousands", () => {
    expect(formatKRW(75400)).toBe("₩75,400");
    expect(formatKRW(10_000_000)).toBe("₩10,000,000");
    expect(formatKRW(0)).toBe("₩0");
  });
  it("rounds to whole won and handles negatives and missing values", () => {
    expect(formatKRW(1234.6)).toBe("₩1,235");
    expect(formatKRW(-1200)).toBe("-₩1,200");
    expect(formatKRW(null)).toBe("—");
    expect(formatKRW(undefined)).toBe("—");
    expect(formatKRW(NaN)).toBe("—");
  });
  it("signs P&L", () => {
    expect(formatSignedKRW(14000)).toBe("+₩14,000");
    expect(formatSignedKRW(-3000)).toBe("-₩3,000");
    expect(formatSignedKRW(0)).toBe("₩0");
  });
  it("compacts large values", () => {
    expect(formatKRWCompact(10_200_000)).toBe("₩10.20M");
    expect(formatKRWCompact(754_000)).toBe("₩754K");
  });
});

describe("percent formatting", () => {
  it("shows sign and 2dp", () => {
    expect(formatPct(0.8)).toBe("+0.80%");
    expect(formatPct(-1.234)).toBe("-1.23%");
    expect(formatPct(0)).toBe("0.00%");
    expect(formatPct(-0.001)).toBe("0.00%");
    expect(formatPct(null)).toBe("—");
  });
});

describe("ticker normalisation", () => {
  it("trims, upper-cases and strips suffixes", () => {
    expect(normalizeTicker(" 005930.ks ")).toBe("005930");
    expect(normalizeTicker("0126z0")).toBe("0126Z0");
    expect(isValidTicker("005930")).toBe(true);
    expect(isValidTicker("5930")).toBe(false);
    expect(isValidTicker("AAPL")).toBe(false);
  });
});
