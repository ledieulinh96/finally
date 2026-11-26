import { act, renderHook } from "@testing-library/react";
import { usePriceStream } from "@/hooks/usePriceStream";

class FakeES {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeES[] = [];
  readyState = FakeES.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeES.instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = FakeES.CLOSED;
  }
  open() {
    this.readyState = FakeES.OPEN;
    this.onopen?.();
  }
  fail(fatal: boolean) {
    this.readyState = fatal ? FakeES.CLOSED : FakeES.CONNECTING;
    this.onerror?.();
  }
}

describe("usePriceStream", () => {
  beforeEach(() => {
    FakeES.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeES);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("streams prices and builds history", () => {
    const { result } = renderHook(() => usePriceStream("/s", 100));
    const es = FakeES.instances[0];
    act(() => es.open());
    expect(result.current.status).toBe("connected");
    act(() => {
      es.onmessage?.({
        data: JSON.stringify({ ticker: "005930", name: "Samsung", price: 75400, prev_price: 75200, session_open: 74800, session_change_pct: 0.8, direction: "up", timestamp: "2026-11-13T09:30:01Z" }),
      });
      vi.advanceTimersByTime(100);
    });
    expect(result.current.prices["005930"].price).toBe(75400);
    expect(result.current.history["005930"]).toHaveLength(1);
  });

  it("shows reconnecting while the browser retries a dropped connection", () => {
    const { result } = renderHook(() => usePriceStream("/s"));
    act(() => FakeES.instances[0].open());
    act(() => FakeES.instances[0].fail(false));
    expect(result.current.status).toBe("reconnecting");
    act(() => vi.advanceTimersByTime(20_000));
    expect(FakeES.instances).toHaveLength(1); // browser handles it natively
  });

  it("recreates the EventSource with backoff after a fatal (CLOSED) error", () => {
    const { result, unmount } = renderHook(() => usePriceStream("/s"));
    act(() => FakeES.instances[0].fail(true));
    expect(result.current.status).toBe("disconnected");
    expect(FakeES.instances[0].closed).toBe(true);

    act(() => vi.advanceTimersByTime(999));
    expect(FakeES.instances).toHaveLength(1);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeES.instances).toHaveLength(2);

    act(() => FakeES.instances[1].fail(true)); // second failure waits 2 s
    act(() => vi.advanceTimersByTime(1999));
    expect(FakeES.instances).toHaveLength(2);
    act(() => vi.advanceTimersByTime(1));
    expect(FakeES.instances).toHaveLength(3);

    act(() => FakeES.instances[2].open());
    expect(result.current.status).toBe("connected");

    act(() => FakeES.instances[2].fail(true)); // backoff reset after a successful open
    act(() => vi.advanceTimersByTime(1000));
    expect(FakeES.instances).toHaveLength(4);

    unmount();
    expect(FakeES.instances[3].closed).toBe(true);
    act(() => FakeES.instances[3].fail(true));
    act(() => vi.advanceTimersByTime(20_000));
    expect(FakeES.instances).toHaveLength(4);
  });
});
