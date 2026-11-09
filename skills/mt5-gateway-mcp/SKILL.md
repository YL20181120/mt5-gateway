---
name: mt5-gateway-mcp
description: Use the MT5 Gateway MCP tools to inspect account, symbols, quotes, positions, orders, history, risk calculations, and trading operations safely.
---

# MT5 Gateway MCP usage skill

Use this skill when interacting with MetaTrader 5 through the mt5-gateway MCP server. Prefer the MCP tools over constructing HTTP requests manually. The tools expose the gateway's real broker state and can include live trading side effects.

## Operating rules

- Read `tools/list` before using an unfamiliar tool. Treat each tool's `inputSchema` as authoritative.
- Do not invent symbols, order types, volumes, prices, tickets, magic numbers, or account settings. Query the gateway when the value is unknown.
- Treat every account, quote, position, order, and history result as broker state, not as local memory.
- Treat timestamps returned by this MCP as `UTC+3` unless the tool result explicitly says otherwise. Convert user-supplied times to `UTC+3` before querying time ranges, and state the timezone when presenting bars, deals, orders, or ticks.
- Before any order, cancellation, modification, or close operation, make sure the user has clearly authorized that exact side effect. If important parameters are missing, ask instead of guessing.
- Prefer `check_order`, `calculate_margin`, and `calculate_profit` before placing an order when the request requires a safety or cost check.
- Use a stable `idempotency_key` for retryable order operations. Do not retry a timed-out trading call blindly; reconcile broker state first.
- After a side-effecting operation, inspect the returned state and use `reconcile` when the result is ambiguous or broker confirmation is incomplete.
- Never claim an order was filled, cancelled, or closed unless the tool result or a follow-up broker-state query confirms it.
- Do not expose passwords, API keys, or other credentials in tool arguments or responses.

## Tool selection

### Account, symbols, and market data

- `get_account` — account balance, equity, margin, leverage, currency, and trading permissions.
- `list_symbols` — discover broker-specific symbol names; use `search` when the exact name is unknown.
- `get_symbol_info` — symbol trading properties, digits, volume limits, and filling constraints.
- `get_symbol_tick` — current bid/ask and latest quote for a symbol.
- `get_bars` — recent candles for a symbol and timeframe.
- `get_bars_range` — candles within a start/end time range.
- `copy_ticks_range` — raw ticks within a start/end time range.

### Positions, orders, and history

- `get_positions` — current open positions; optionally filter by `magic`.
- `get_positions_total` — current open-position count.
- `get_pending_orders` — current pending orders; optionally filter by symbol or ticket.
- `get_deal` — one deal by ticket.
- `get_historical_order` — one historical order by ticket.
- `get_deals` — deals in a time range, optionally filtered by position.
- `get_historical_orders` — historical orders by ticket.
- `get_deals_range` — deals in a time range, optionally filtered by magic.

### Validation and calculation

- `check_order` — broker pre-check; it does not place an order.
- `calculate_margin` — required margin for an order.
- `calculate_profit` — estimated profit or loss between open and close prices.

### Trading operations

These tools have external side effects and require explicit user intent:

- `place_order` — place a market or pending order. Include `idempotency_key` for safe retries.
- `cancel_order` — cancel a pending order by ticket.
- `modify_order` — modify pending-order price, stop-loss, take-profit, or expiration.
- `close_position` — close a specified position.
- `close_position_partial` — close part of a specified position.
- `close_all_positions` — close all positions or positions matching `order_type`/`magic`; treat as high risk.
- `modify_position_sl_tp` — modify or clear a position's stop-loss/take-profit.

### Operations and safety

- `get_health` — gateway health state.
- `reconcile` — retrieve broker-truth positions, pending orders, and recent deals after uncertainty or restart.
- `get_last_error` — inspect the latest MT5 error when an operation fails.
- `engage_kill_switch` — stop trading, optionally flatten positions; high risk.
- `release_kill_switch` — release the trading kill switch only when explicitly requested.

## Recommended workflows

### Discover and inspect an instrument

1. Call `list_symbols` with a search pattern if the broker-specific symbol name is unknown.
2. Call `get_symbol_info` for trading constraints.
3. Call `get_symbol_tick` for the current bid/ask.
4. Use `get_bars` or `get_bars_range` only when candle history is needed.

### Prepare and place an order

1. Confirm the symbol with `get_symbol_info` and current pricing with `get_symbol_tick`.
2. Validate the requested direction, volume, price, stop-loss, take-profit, and order type.
3. Run `check_order`; calculate margin or expected profit if relevant.
4. Present the final order parameters to the user when confirmation is required.
5. Call `place_order` with a stable `idempotency_key`.
6. If the result is ambiguous, call `reconcile` before retrying.

### Close or modify a position

1. Call `get_positions` and identify the exact position ticket.
2. Confirm the requested ticket, volume, stop-loss, and take-profit changes.
3. Call the narrowest operation that matches the request; do not use `close_all_positions` for a single-position request.
4. Verify the result with `get_positions` or `reconcile`.

### Recover from an uncertain result

1. Do not repeat a side-effecting call immediately.
2. Call `get_last_error` for diagnostic information.
3. Call `reconcile` to compare broker-truth positions, pending orders, and recent deals.
4. Report the confirmed state and ask before taking a compensating action.

## Result handling

Tool results contain machine-readable `structuredContent` and may also contain a text compatibility block. Prefer `structuredContent`.

The normal result envelope is:

```json
{
  "status": 200,
  "data": {}
}
```

For errors, inspect `status`, `data.error`, `data.error_type`, and any additional details. A successful tool response means the gateway accepted the operation; for trading operations, verify the broker state when execution or fill status matters.

## Scope boundary

This skill describes how to use the exposed MT5 Gateway MCP tools. It does not authorize live trading by itself. User intent, broker permissions, account state, and the tool result remain authoritative.
