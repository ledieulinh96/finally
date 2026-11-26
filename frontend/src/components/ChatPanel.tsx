"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { formatKRW, formatQty } from "@/lib/format";
import type { ChatResponse, ChatTrade, ChatWatchlistChange, StoredChatMessage } from "@/lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  trades?: ChatTrade[];
  watchlist_changes?: ChatWatchlistChange[];
  error?: boolean;
}

interface Props {
  open: boolean;
  onToggle: () => void;
  onSend: (message: string) => Promise<ChatResponse>;
  /** Loads the stored conversation once on mount (survives page reloads). */
  loadHistory?: () => Promise<StoredChatMessage[]>;
}

const MAX_LEN = 2000;
const SUGGESTIONS = [
  "How concentrated is my portfolio?",
  "Buy 5 shares of 005930",
  "Add 247540 EcoPro BM to my watchlist",
];

let seq = 0;
const nextId = () => `m${Date.now()}-${seq++}`;

function tradeText(t: ChatTrade) {
  const verb = t.side === "buy" ? "Bought" : "Sold";
  if (t.success) return `${verb} ${formatQty(t.quantity)} ${t.ticker}${t.price ? ` at ${formatKRW(t.price)}` : ""}`;
  return `${t.side === "buy" ? "Buy" : "Sell"} ${formatQty(t.quantity)} ${t.ticker} failed: ${t.error ?? "rejected"}`;
}

function watchText(w: ChatWatchlistChange) {
  const label = `${w.ticker}${w.name ? ` ${w.name}` : ""}`;
  if (w.success) return w.action === "add" ? `Added ${label} to watchlist` : `Removed ${label} from watchlist`;
  return `${w.action === "add" ? "Add" : "Remove"} ${label} failed: ${w.error ?? "rejected"}`;
}

function Action({ success, text }: { success: boolean; text: string }) {
  return (
    <li
      data-testid="chat-action"
      data-success={String(success)}
      className={`num flex gap-1.5 rounded border px-2 py-1 text-2xs ${
        success ? "border-up/40 bg-up/10 text-up" : "border-down/40 bg-down/10 text-down"
      }`}
    >
      <span aria-hidden>{success ? "✓" : "!"}</span>
      <span>{text}</span>
    </li>
  );
}

export function ChatBubble({ m }: { m: ChatMessage }) {
  const actions = [
    ...(m.trades ?? []).map((t) => ({ success: t.success, text: tradeText(t) })),
    ...(m.watchlist_changes ?? []).map((w) => ({ success: w.success, text: watchText(w) })),
  ];
  const user = m.role === "user";
  return (
    <li data-testid="chat-message" data-role={m.role} className={`flex flex-col gap-1 ${user ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[92%] whitespace-pre-wrap break-words rounded px-2.5 py-1.5 text-xs leading-relaxed ${
          user
            ? "bg-primary/15 text-fg"
            : m.error
              ? "border border-down/40 bg-down/10 text-down"
              : "border border-line bg-raised text-fg"
        }`}
      >
        {m.content}
      </div>
      {actions.length > 0 && (
        <ul className="flex max-w-[92%] flex-col gap-1">
          {actions.map((a, i) => (
            <Action key={i} {...a} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function ChatPanel({ open, onToggle, onSend, loadHistory }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    if (!loadHistory) return;
    let cancelled = false;
    loadHistory().then((stored) => {
      if (cancelled || stored.length === 0) return;
      const restored: ChatMessage[] = stored.map((m) => ({
        id: `h-${m.id}`,
        role: m.role,
        content: m.content,
        trades: m.trades ?? [],
        watchlist_changes: m.watchlist_changes ?? [],
      }));
      // Anything sent before history arrived stays after it.
      setMessages((current) => [...restored, ...current]);
    });
    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  useEffect(() => {
    const el = list.current;
    if (el && typeof el.scrollTo === "function") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text: string) => {
    const msg = text.trim();
    if (!msg || loading) return;
    setMessages((m) => [...m, { id: nextId(), role: "user", content: msg }]);
    setInput("");
    setLoading(true);
    try {
      const r = await onSend(msg);
      setMessages((m) => [
        ...m,
        {
          id: nextId(),
          role: "assistant",
          content: r.message,
          trades: r.trades ?? [],
          watchlist_changes: r.watchlist_changes ?? [],
        },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          id: nextId(),
          role: "assistant",
          content: `Message not sent: ${e instanceof Error ? e.message : String(e)}`,
          error: true,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send(input);
  };

  if (!open) {
    return (
      <aside data-testid="chat-panel" data-open="false" className="flex w-10 flex-col items-center border-l border-line bg-panel py-2">
        <button
          data-testid="chat-toggle"
          type="button"
          onClick={onToggle}
          aria-label="Open assistant"
          aria-expanded={false}
          className="rounded px-1 py-2 text-xs font-medium text-accent [writing-mode:vertical-rl] hover:bg-raised"
        >
          Assistant
        </button>
      </aside>
    );
  }

  return (
    <aside data-testid="chat-panel" data-open="true" className="flex w-full flex-col border-l border-line bg-panel lg:w-[360px]">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <div>
          <h2 className="text-xs font-semibold text-fg">Assistant</h2>
          <p className="text-2xs text-faint">Analyses your book and places trades for you</p>
        </div>
        <button
          data-testid="chat-toggle"
          type="button"
          onClick={onToggle}
          aria-label="Collapse assistant"
          aria-expanded
          className="rounded px-2 py-1 text-xs text-muted hover:bg-raised hover:text-fg"
        >
          ›
        </button>
      </div>
      <ul data-testid="chat-messages" ref={list} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3" aria-live="polite">
        {messages.length === 0 && !loading && (
          <li className="flex flex-col gap-2 text-xs text-muted">
            <p>Ask about your positions, or tell me what to trade. Orders I place fill immediately at market.</p>
            <div className="flex flex-col items-start gap-1">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded border border-line px-2 py-1 text-left text-2xs text-fg hover:border-primary hover:text-primary"
                >
                  {s}
                </button>
              ))}
            </div>
          </li>
        )}
        {messages.map((m) => (
          <ChatBubble key={m.id} m={m} />
        ))}
        {loading && (
          <li data-testid="chat-loading" className="flex items-center gap-1.5 text-2xs text-muted" role="status">
            <span className="flex gap-0.5" aria-hidden>
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent" />
            </span>
            Thinking
          </li>
        )}
      </ul>
      <form onSubmit={submit} className="border-t border-line p-2">
        <textarea
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value.slice(0, MAX_LEN))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send(input);
            }
          }}
          rows={2}
          placeholder="Ask FinAlly…"
          aria-label="Message the assistant"
          className="w-full resize-none rounded border border-line bg-ink px-2 py-1.5 text-xs text-fg placeholder:text-faint focus:border-primary focus:outline-none"
        />
        <div className="mt-1 flex items-center justify-between">
          <span className="num text-2xs text-faint">
            {input.length > MAX_LEN - 200 ? `${input.length}/${MAX_LEN}` : "Enter to send, Shift+Enter for a new line"}
          </span>
          <button
            data-testid="chat-send"
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded bg-secondary px-3 py-1 text-xs font-semibold text-white hover:brightness-110 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </aside>
  );
}
