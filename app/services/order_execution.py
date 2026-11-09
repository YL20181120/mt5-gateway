"""Order execution service shared by HTTP and MCP adapters."""

import logging
import os
import time

from audit import order_audit
from constants import TRADE_ACTION_DEAL, TRADE_ACTION_PENDING
from idempotency import Decision, IdempotencyStore, magic_from_key, request_fingerprint
from lib import (
    get_symbol_filling_mode,
    validate_pending_price,
    validate_sl_tp,
    validate_symbol,
    validate_type_filling,
)
from metrics import metrics
from money import (
    NumericValidationError,
    finite_float,
    normalize_price,
    normalize_volume,
)
from mt5_connection import mt5
from order_requests import build_trade_request
from order_time import apply_expiration
from pretrade import PreTradeError, validate_order_intent, validate_price_band
from retcodes import classify_retcode, success_state
from services.errors import ServiceError
from time_utils import ServerOffsetUnavailable, tick_time_ms

idempotency_store = IdempotencyStore(
    ttl_seconds=float(os.getenv("MT5_IDEMPOTENCY_TTL", "3600"))
)
logger = logging.getLogger(__name__)
FILL_CONFIRM_TIMEOUT_MS = int(os.getenv("MT5_FILL_CONFIRM_TIMEOUT_MS", "3000"))
FILL_CONFIRM_POLL_MS = int(os.getenv("MT5_FILL_CONFIRM_POLL_MS", "200"))


def send_order(data, idempotency_key=None, request_id="unknown"):
    if not data:
        raise ServiceError("Order data is required", status=400, error_type="validation_error")
    try:
        validate_order_intent(data)
    except PreTradeError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    body_key = data.get("client_order_id")
    if body_key and idempotency_key and body_key != idempotency_key:
        raise ServiceError("client_order_id and Idempotency-Key must match", status=400, error_type="validation_error")
    key = body_key or idempotency_key
    fingerprint = None
    reserved = False
    completed = False
    if key is not None:
        if not isinstance(key, str) or not 1 <= len(key.strip()) <= 128:
            raise ServiceError("client_order_id must contain 1 to 128 characters", status=400, error_type="validation_error")
        key = key.strip()
        fingerprint = request_fingerprint(data)
        decision, stored = idempotency_store.begin(key, fingerprint)
        if decision is Decision.REPLAY:
            return {"payload": stored.payload, "status": stored.status_code, "replayed": True}
        if decision is Decision.CONFLICT:
            raise ServiceError("Idempotency key was already used with different parameters", status=409, error_type="idempotency_conflict")
        if decision is Decision.IN_PROGRESS:
            raise ServiceError("An order with this idempotency key is in progress", status=409, error_type="idempotency_in_progress")
        reserved = True
    try:
        result = _execute(data, key, request_id)
        if key:
            idempotency_store.complete(key, fingerprint, result, 200)
        completed = True
        return {"payload": result, "status": 200, "replayed": False}
    except ServiceError as error:
        if reserved and error.error_type == "unknown_outcome":
            idempotency_store.complete(key, fingerprint, {"error": error.message, "error_type": error.error_type}, error.status)
            completed = True
        raise
    finally:
        if reserved and key and not completed:
            idempotency_store.abandon(key, fingerprint)


def _execute(data, key, request_id):
    required = ["symbol", "volume", "type"]
    if not all(field in data for field in required):
        raise ServiceError("Missing required fields", status=400, error_type="validation_error", details={"required": required})
    symbol = data["symbol"]
    if not validate_symbol(symbol):
        raise ServiceError(f"Symbol not found or not selectable: {symbol}", status=400, error_type="validation_error")
    order_types = {
        "BUY": mt5.ORDER_TYPE_BUY, "SELL": mt5.ORDER_TYPE_SELL,
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP, "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        "BUY_STOP_LIMIT": mt5.ORDER_TYPE_BUY_STOP_LIMIT, "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    type_name = str(data["type"]).upper()
    if type_name not in order_types:
        raise ServiceError(f"Invalid order type: {data['type']}", status=400, error_type="validation_error")
    order_type = order_types[type_name]
    info = mt5.symbol_info(symbol)
    if info is None:
        raise ServiceError("Symbol info unavailable", status=400, error_type="validation_error")
    try:
        volume = normalize_volume(data["volume"], info)
    except NumericValidationError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    if order_type in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL):
        action = TRADE_ACTION_DEAL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ServiceError(f"Failed to get symbol price for {symbol}", status=400, error_type="validation_error")
        raw_price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        market_price = raw_price
    else:
        action = TRADE_ACTION_PENDING
        if "price" not in data:
            raise ServiceError("Price required for pending orders", status=400, error_type="validation_error")
        market_tick = mt5.symbol_info_tick(symbol)
        if market_tick is None:
            raise ServiceError(f"Failed to get symbol price for {symbol}", status=400, error_type="validation_error")
        market_price = market_tick.ask if order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP) else market_tick.bid
        raw_price = data["price"]
        if order_type in (mt5.ORDER_TYPE_BUY_STOP_LIMIT, mt5.ORDER_TYPE_SELL_STOP_LIMIT) and "stoplimit" not in data:
            raise ServiceError("stoplimit required for stop-limit orders", status=400, error_type="validation_error")
        valid, message = validate_pending_price(order_type, symbol, raw_price)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")
        try:
            validate_price_band(float(raw_price), market_price)
        except PreTradeError as error:
            raise ServiceError(str(error), status=400, error_type="validation_error") from error
    try:
        price = normalize_price(raw_price, info)
        sl = normalize_price(data["sl"], info, "sl") if data.get("sl") is not None else None
        tp = normalize_price(data["tp"], info, "tp") if data.get("tp") is not None else None
        deviation = finite_float(data.get("deviation", 20), "deviation")
        stoplimit = normalize_price(data["stoplimit"], info) if data.get("stoplimit") is not None else None
    except NumericValidationError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    if sl is not None or tp is not None:
        valid, message = validate_sl_tp(order_type, price, sl, tp)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")
    filling = get_symbol_filling_mode(symbol)
    if "type_filling" in data:
        filling, message = validate_type_filling(data["type_filling"])
        if message:
            raise ServiceError(message, status=400, error_type="validation_error")
    request_data = build_trade_request(action=action, symbol=symbol, volume=volume, order_type=order_type, price=price, deviation=int(deviation), magic=data.get("magic", magic_from_key(key) if key else 0), comment=data.get("comment", ""), type_time=mt5.ORDER_TIME_GTC, type_filling=filling, sl=sl, tp=tp, stoplimit=stoplimit)
    try:
        apply_expiration(request_data, data, symbol=symbol, read_tick_ms=lambda: tick_time_ms(mt5.symbol_info_tick(symbol)))
    except ServerOffsetUnavailable as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    check = mt5.order_check(request_data)
    if check is None:
        raise ServiceError(f"Broker pre-trade check unavailable: {mt5.last_call_error()}", status=400, error_type="validation_error")
    if check.retcode not in (0, mt5.TRADE_RETCODE_DONE):
        raise ServiceError(f"Broker pre-trade check rejected order: {check.comment}", status=400, error_type="validation_error", details={"retcode": check.retcode})
    started = time.monotonic()
    result = mt5.order_send(request_data)
    metrics.inc("orders_submitted_total", (("symbol", symbol), ("side", type_name)))
    order_audit.emit("broker_response", client_order_id=key, mt5_ticket=getattr(result, "order", None), deal=getattr(result, "deal", None), symbol=symbol, side=type_name, order_type=type_name, volume_requested=volume, volume_filled=getattr(result, "volume", None), price_requested=price, price_filled=getattr(result, "price", None), retcode=getattr(result, "retcode", None), retcode_name=classify_retcode(result.retcode).name if result else "NONE", latency_ms=round((time.monotonic() - started) * 1000, 3), account_mode=None, magic=request_data["magic"])
    if result is None:
        raise ServiceError("Send order outcome is unknown", status=502, error_type="unknown_outcome", details={"retry_guidance": "Reconcile positions and order/deal history before retrying."})
    retcode = classify_retcode(result.retcode)
    if not retcode.is_success:
        raise ServiceError(f"Send order failed: {result.comment}", status=502 if retcode.is_ambiguous else 400, error_type="unknown_outcome" if retcode.is_ambiguous else "mt5_rejected", details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}})
    result_dict = result._asdict()
    state = success_state(result.retcode)
    fill_price_source = "order_send"
    if action == TRADE_ACTION_DEAL and not result_dict.get("price"):
        fill_price_source = _resolve_async_fill(result_dict, result)
    return {"message": f"Order {'executed' if action == TRADE_ACTION_DEAL else 'placed'} successfully", "state": state, "result": result_dict, "sl_confirmed": result_dict.get("sl"), "tp_confirmed": result_dict.get("tp"), "partial_fill": state == "partially_executed", "fill_price_source": fill_price_source, **({"client_order_id": key} if key else {})}


def _resolve_async_fill(result_dict, result):
    deadline = time.monotonic() + FILL_CONFIRM_TIMEOUT_MS / 1000.0
    while time.monotonic() < deadline:
        time.sleep(FILL_CONFIRM_POLL_MS / 1000.0)
        try:
            if getattr(result, "deal", 0):
                deals = mt5.history_deals_get(ticket=result.deal)
                if deals:
                    deal = deals[0]._asdict()
                    if deal.get("price"):
                        result_dict["price"] = deal["price"]
                        if not result_dict.get("volume"):
                            result_dict["volume"] = deal.get("volume")
                        return "deal"
            if getattr(result, "order", 0):
                positions = mt5.positions_get(ticket=result.order)
                if positions:
                    position = positions[0]._asdict()
                    if position.get("price_open"):
                        result_dict["price"] = position["price_open"]
                        return "position"
        except Exception as error:
            logger.debug("async fill lookup failed: %s", error)
            continue
    return "unresolved"
