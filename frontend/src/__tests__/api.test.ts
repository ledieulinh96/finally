import { api, errorMessage } from "@/lib/api";

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns trade business-rule failures instead of throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ success: false, error: "Insufficient cash" }), { status: 400 })),
    );
    await expect(api.trade("005930", 1000, "buy")).resolves.toEqual({ success: false, error: "Insufficient cash" });
  });

  it("extracts FastAPI validation messages", () => {
    expect(errorMessage({ detail: [{ msg: "Input should be greater than 0" }] }, 422)).toBe("Input should be greater than 0");
    expect(errorMessage({ detail: "Ticker already in watchlist" }, 409)).toBe("Ticker already in watchlist");
    expect(errorMessage(null, 500)).toBe("Request failed (500)");
  });
});

describe("chatHistory", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("resolves [] when the endpoint is missing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    await expect(api.chatHistory()).resolves.toEqual([]);
  });
});
