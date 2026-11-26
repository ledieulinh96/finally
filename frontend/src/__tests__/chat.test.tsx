import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "@/components/ChatPanel";
import type { ChatResponse } from "@/lib/types";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("ChatPanel", () => {
  it("shows the user message, a loading indicator, then the reply with inline actions", async () => {
    const user = userEvent.setup();
    const d = deferred<ChatResponse>();
    const onSend = vi.fn(() => d.promise);
    render(<ChatPanel open onToggle={() => {}} onSend={onSend} />);

    await user.type(screen.getByTestId("chat-input"), "Buy 1 Samsung");
    await user.click(screen.getByTestId("chat-send"));

    expect(onSend).toHaveBeenCalledWith("Buy 1 Samsung");
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    expect(screen.getByTestId("chat-send")).toBeDisabled();
    const msgs = screen.getAllByTestId("chat-message");
    expect(msgs).toHaveLength(1);
    expect(msgs[0]).toHaveAttribute("data-role", "user");
    expect(screen.getByTestId("chat-input")).toHaveValue("");

    d.resolve({
      message: "Buying 1 share of 005930 Samsung Electronics and adding 035420 NAVER to your watchlist.",
      trades: [{ ticker: "005930", side: "buy", quantity: 1, price: 75400, success: true }],
      watchlist_changes: [
        { ticker: "035420", action: "add", name: "NAVER", success: true },
        { ticker: "999999", action: "add", success: false, error: "Unknown ticker" },
      ],
    });

    await waitFor(() => expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument());
    const all = screen.getAllByTestId("chat-message");
    expect(all[1]).toHaveAttribute("data-role", "assistant");
    expect(all[1]).toHaveTextContent("Buying 1 share of 005930");

    const actions = screen.getAllByTestId("chat-action");
    expect(actions).toHaveLength(3);
    expect(actions[0]).toHaveAttribute("data-success", "true");
    expect(actions[0]).toHaveTextContent("Bought 1 005930 at ₩75,400");
    expect(actions[1]).toHaveTextContent("Added 035420 NAVER to watchlist");
    expect(actions[2]).toHaveAttribute("data-success", "false");
    expect(actions[2]).toHaveTextContent("Unknown ticker");
  });

  it("sends on Enter and renders failures as an error bubble", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => {
      throw new Error("Can't reach the server");
    });
    render(<ChatPanel open onToggle={() => {}} onSend={onSend} />);
    await user.type(screen.getByTestId("chat-input"), "hello{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");
    expect(await screen.findByText(/Message not sent: Can't reach the server/)).toBeInTheDocument();
  });

  it("collapses to a toggle", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(<ChatPanel open={false} onToggle={onToggle} onSend={vi.fn()} />);
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("chat-toggle"));
    expect(onToggle).toHaveBeenCalled();
  });
});

describe("ChatPanel history", () => {
  it("restores the stored conversation with its actions", async () => {
    const loadHistory = vi.fn(async () => [
      { id: "1", role: "user" as const, content: "buy one samsung", trades: null, watchlist_changes: null, created_at: "2026-11-26T00:00:00Z" },
      {
        id: "2",
        role: "assistant" as const,
        content: "Done.",
        trades: [{ ticker: "005930", side: "buy" as const, quantity: 1, price: 75400, success: true }],
        watchlist_changes: [],
        created_at: "2026-11-26T00:00:01Z",
      },
    ]);
    render(<ChatPanel open onToggle={() => {}} onSend={vi.fn()} loadHistory={loadHistory} />);
    await waitFor(() => expect(screen.getAllByTestId("chat-message")).toHaveLength(2));
    expect(screen.getAllByTestId("chat-message")[0]).toHaveAttribute("data-role", "user");
    expect(screen.getByTestId("chat-action")).toHaveTextContent("Bought 1 005930 at ₩75,400");
  });

  it("shows the empty state when there is no history", async () => {
    render(<ChatPanel open onToggle={() => {}} onSend={vi.fn()} loadHistory={async () => []} />);
    expect(await screen.findByText(/Ask about your positions/)).toBeInTheDocument();
  });
});
