# Frontend data-testid contract

Stable `data-testid` attributes the E2E suite (`test/`) may rely on. Owned by `frontend`; changes are announced to `tester`.
`<T>` = 6-char ticker code, e.g. `005930`.

## Header
| testid | element | notes |
|---|---|---|
| `header-total-value` | total portfolio value | text like `₩10,000,000`, updates live with prices |
| `header-cash` | cash balance | text like `₩10,000,000` |
| `connection-status` | status dot | attribute `data-status` = `connected` \| `reconnecting` \| `disconnected` |
| `market-closed-badge` | "Market closed" badge | only rendered in yfinance mode outside regular/closing_auction |

## Watchlist
| testid | element | notes |
|---|---|---|
| `watchlist` | panel container | |
| `watchlist-row-<T>` | row for a ticker | clicking selects ticker for main chart; attribute `data-flash` = `up`\|`down`\|`` during flash |
| `watchlist-price-<T>` | price cell | `₩75,400`, or `—` before first price |
| `watchlist-change-<T>` | session change % cell | e.g. `+0.80%` |
| `watchlist-remove-<T>` | remove button (in row) | |
| `watchlist-add-input` | ticker input for adding | |
| `watchlist-add-button` | add button | |
| `watchlist-error` | error message for add/remove | only rendered when there is an error |

## Main chart
| testid | element | notes |
|---|---|---|
| `main-chart` | chart container | attribute `data-ticker` = selected ticker |

## Trade bar
| testid | element | notes |
|---|---|---|
| `trade-ticker-input` | ticker input | prefilled with selected ticker |
| `trade-quantity-input` | quantity input | positive integer |
| `trade-buy-button` | Buy | |
| `trade-sell-button` | Sell | |
| `trade-message` | result line | attribute `data-status` = `success` \| `error`; error text is the backend `error` string (e.g. `Insufficient cash`) |

## Portfolio
| testid | element | notes |
|---|---|---|
| `positions-table` | positions table | |
| `positions-empty` | empty state | shown when no positions |
| `position-row-<T>` | row per position | |
| `position-qty-<T>` | quantity cell | plain integer, e.g. `5` |
| `heatmap` | treemap container | |
| `heatmap-cell-<T>` | treemap rectangle | attribute `data-pnl` = `profit` \| `loss` \| `flat` |
| `pnl-chart` | P&L line chart container | attribute `data-points` = number of points plotted |

## Chat
| testid | element | notes |
|---|---|---|
| `chat-panel` | chat sidebar | |
| `chat-toggle` | collapse/expand button | |
| `chat-input` | message textarea | Enter sends, Shift+Enter newline |
| `chat-send` | send button | |
| `chat-messages` | message list | |
| `chat-message` | each message | attribute `data-role` = `user` \| `assistant` |
| `chat-loading` | loading indicator | present only while waiting for `/api/chat` |
| `chat-action` | inline trade/watchlist confirmation | attribute `data-success` = `true` \| `false` |
