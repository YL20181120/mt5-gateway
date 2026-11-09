"""Pre-trade order validation without sending an order."""

from constants import TRADE_ACTION_DEAL, TRADE_ACTION_PENDING
from lib import (
    validate_pending_price,
    validate_sl_tp,
    validate_symbol,
    validate_type_filling,
    validate_volume,
)
from mt5_connection import mt5
from order_requests import build_trade_request
from order_time import apply_expiration
from services.errors import ServiceError
from time_utils import ServerOffsetUnavailable, tick_time_ms


def check_order(data):
    if not data:
        raise ServiceError("Order data is required", status=400, error_type="validation_error")
    required = ["symbol", "volume", "type"]
    if not all(field in data for field in required):
        raise ServiceError(
            "Missing required fields",
            status=400,
            error_type="validation_error",
            details={"required": required},
        )
    symbol = data["symbol"]
    if not validate_symbol(symbol):
        raise ServiceError(
            f"Symbol not found or not selectable: {symbol}",
            status=400,
            error_type="validation_error",
        )

    type_map = {
        "BUY": mt5.ORDER_TYPE_BUY,
        "SELL": mt5.ORDER_TYPE_SELL,
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
    }
    type_name = data["type"].upper() if isinstance(data["type"], str) else str(data["type"])
    if type_name not in type_map:
        raise ServiceError(f"Invalid order type: {data['type']}", status=400, error_type="validation_error")
    order_type = type_map[type_name]

    try:
        volume = float(data["volume"])
    except (TypeError, ValueError) as error:
        raise ServiceError("Volume must be positive", status=400, error_type="validation_error") from error
    if volume <= 0:
        raise ServiceError("Volume must be positive", status=400, error_type="validation_error")
    valid, message = validate_volume(symbol, volume)
    if not valid:
        raise ServiceError(message, status=400, error_type="validation_error")

    if order_type in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL):
        action = TRADE_ACTION_DEAL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ServiceError(f"Failed to get symbol price for {symbol}", status=400, error_type="validation_error")
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    else:
        action = TRADE_ACTION_PENDING
        if "price" not in data:
            raise ServiceError("Price required for pending orders", status=400, error_type="validation_error")
        try:
            price = float(data["price"])
        except (TypeError, ValueError) as error:
            raise ServiceError("Price must be positive", status=400, error_type="validation_error") from error
        if price <= 0:
            raise ServiceError("Price must be positive", status=400, error_type="validation_error")
        valid, message = validate_pending_price(order_type, symbol, price)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")

    sl = float(data["sl"]) if data.get("sl") is not None else None
    tp = float(data["tp"]) if data.get("tp") is not None else None
    if sl is not None or tp is not None:
        valid, message = validate_sl_tp(order_type, price, sl, tp)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")

    type_filling = mt5.ORDER_FILLING_IOC
    if "type_filling" in data:
        type_filling, message = validate_type_filling(data["type_filling"])
        if message:
            raise ServiceError(message, status=400, error_type="validation_error")
    request_data = build_trade_request(
        action=action,
        symbol=symbol,
        volume=volume,
        order_type=order_type,
        price=price,
        deviation=int(data.get("deviation", 20)),
        magic=int(data.get("magic", 0)),
        comment=data.get("comment", ""),
        type_time=mt5.ORDER_TIME_GTC,
        type_filling=type_filling,
        sl=sl,
        tp=tp,
    )
    try:
        apply_expiration(
            request_data,
            data,
            symbol=symbol,
            read_tick_ms=lambda: tick_time_ms(mt5.symbol_info_tick(symbol)),
        )
    except ServerOffsetUnavailable as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error

    result = mt5.order_check(request_data)
    if result is None:
        raise ServiceError("Order check failed - MT5 returned None", status=400, error_type="validation_error")
    if result.retcode != mt5.TRADE_RETCODE_DONE and result.retcode != 0:
        return {
            "valid": False,
            "retcode": result.retcode,
            "comment": result.comment,
            "margin": getattr(result, "margin", None),
            "margin_free": getattr(result, "margin_free", None),
        }, 400
    return {"valid": True, **result._asdict()}
