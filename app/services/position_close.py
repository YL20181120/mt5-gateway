"""Position-closing operations."""

import math

from close_confirm import confirm_close

from lib import (
    close_position,
    get_symbol_filling_mode,
    validate_symbol,
    validate_volume,
)
from mt5_connection import mt5
from retcodes import classify_retcode
from services.errors import ServiceError


def close_one(position, request_id=None):
    if not position:
        raise ServiceError("Position data is required", status=400, error_type="validation_error")
    result = close_position(position)
    if result is None:
        raise ServiceError("Failed to close position", status=400, error_type="validation_error")
    info = classify_retcode(result.retcode)
    if not info.is_success:
        raise ServiceError(
            f"Close position failed: {result.comment}",
            status=400,
            error_type="mt5_rejected",
            details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}},
        )
    result_data = result._asdict()
    result_data["partial"] = info.name == "DONE_PARTIAL"
    if result_data["partial"]:
        original_volume = float(position.get("volume", result.volume))
        result_data["remaining_volume"] = max(0.0, original_volume - float(result.volume))
    return {
        "message": "Position closed successfully",
        "result": result_data,
        "fill_price_source": confirm_close(result_data, int(position["ticket"]), request_id),
    }


def close_partial(data, request_id=None):
    if not data:
        raise ServiceError("Position data is required", status=400, error_type="validation_error")
    required = ["ticket", "volume"]
    if not all(field in data for field in required):
        raise ServiceError("Missing required fields", status=400, error_type="validation_error", details={"required": required})
    try:
        ticket = int(data["ticket"])
        volume = float(data["volume"])
    except (TypeError, ValueError) as error:
        raise ServiceError("Ticket and volume must be numeric", status=400, error_type="validation_error") from error
    if not math.isfinite(volume) or volume <= 0:
        raise ServiceError("Volume must be positive", status=400, error_type="validation_error")
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        raise ServiceError(f"Position {ticket} not found", status=400, error_type="validation_error")
    position = positions[0]
    symbol = position.symbol
    position_type = position.type
    if "symbol" in data and data["symbol"] != symbol:
        raise ServiceError(f"Symbol does not match position {ticket}", status=400, error_type="validation_error")
    if "type" in data and int(data["type"]) != position_type:
        raise ServiceError(f"Type does not match position {ticket}", status=400, error_type="validation_error")
    if not validate_symbol(symbol):
        raise ServiceError(f"Symbol not found or not selectable: {symbol}", status=400, error_type="validation_error")
    valid, message = validate_volume(symbol, volume)
    if not valid:
        raise ServiceError(message, status=400, error_type="validation_error")
    if volume >= position.volume:
        raise ServiceError(f"Volume to close ({volume}) must be less than position volume ({position.volume}). Use /close_position to close entire position.", status=400, error_type="validation_error")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise ServiceError(f"Failed to get tick for {symbol}", status=400, error_type="validation_error")
    order_types = {0: mt5.ORDER_TYPE_SELL, 1: mt5.ORDER_TYPE_BUY}
    if position_type not in order_types:
        raise ServiceError(f"Invalid position type: {position_type}. Must be 0 (BUY) or 1 (SELL)", status=400, error_type="validation_error")
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": symbol,
        "volume": volume,
        "type": order_types[position_type],
        "price": tick.bid if position_type == 0 else tick.ask,
        "deviation": data.get("deviation", 20),
        "magic": position.magic,
        "comment": data.get("comment", "Partial close"),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": get_symbol_filling_mode(symbol),
    })
    if result is None:
        raise ServiceError("Partial close position outcome is unknown", status=502, error_type="unknown_outcome", details={"retry_guidance": "Reconcile positions and order/deal history before retrying."})
    info = classify_retcode(result.retcode)
    if not info.is_success:
        raise ServiceError(f"Partial close position failed: {result.comment}", status=400, error_type="mt5_rejected", details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}})
    result_data = result._asdict()
    filled = float(result_data.get("volume") or volume)
    return {
        "message": "Position partially closed successfully",
        "result": result_data,
        "partial": info.name == "DONE_PARTIAL",
        "remaining_volume": max(0.0, float(position.volume) - filled),
        "fill_price_source": confirm_close(result_data, ticket, request_id),
    }
