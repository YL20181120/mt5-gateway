"""Pending-order modification."""

from lib import validate_pending_price, validate_sl_tp
from mt5_connection import mt5
from order_time import apply_expiration
from retcodes import classify_retcode
from services.errors import ServiceError
from time_utils import ServerOffsetUnavailable, tick_time_ms


def modify_order(ticket, data):
    if not data:
        raise ServiceError("Modification data is required", status=400, error_type="validation_error")
    if not any(field in data for field in ("price", "sl", "tp")):
        raise ServiceError("At least one of price, sl, or tp must be provided", status=400, error_type="validation_error")
    orders = mt5.orders_get(ticket=ticket)
    if orders is None:
        raise ServiceError("Failed to retrieve order information", status=503, error_type="connection_error")
    if not orders:
        raise ServiceError(f"Order with ticket {ticket} not found", status=404, error_type="not_found")
    order = orders[0]
    try:
        new_price = float(data["price"]) if "price" in data else order.price_open
        new_sl = float(data["sl"]) if "sl" in data else order.sl
        new_tp = float(data["tp"]) if "tp" in data else order.tp
    except (TypeError, ValueError) as error:
        raise ServiceError("Price and protection values must be numeric", status=400, error_type="validation_error") from error
    if new_price <= 0:
        raise ServiceError("Price must be positive", status=400, error_type="validation_error")
    if new_sl is not None and new_sl < 0:
        raise ServiceError("Stop loss must be non-negative (use 0 to remove)", status=400, error_type="validation_error")
    if new_tp is not None and new_tp < 0:
        raise ServiceError("Take profit must be non-negative (use 0 to remove)", status=400, error_type="validation_error")
    if "price" in data:
        valid, message = validate_pending_price(order.type, order.symbol, new_price)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")
    if (new_sl and new_sl > 0) or (new_tp and new_tp > 0):
        valid, message = validate_sl_tp(order.type, new_price, new_sl or None, new_tp or None)
        if not valid:
            raise ServiceError(message, status=400, error_type="validation_error")
    request_data = {
        "action": mt5.TRADE_ACTION_MODIFY,
        "order": ticket,
        "price": new_price,
        "sl": new_sl,
        "tp": new_tp,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    try:
        apply_expiration(
            request_data,
            data,
            existing_order=order,
            symbol=order.symbol,
            read_tick_ms=lambda: tick_time_ms(mt5.symbol_info_tick(order.symbol)),
        )
    except ServerOffsetUnavailable as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    result = mt5.order_send(request_data)
    if result is None:
        raise ServiceError("Modify order outcome is unknown", status=502, error_type="unknown_outcome", details={"retry_guidance": "Reconcile positions and order/deal history before retrying."})
    info = classify_retcode(result.retcode)
    if not info.is_success:
        raise ServiceError(f"Modify order failed: {result.comment}", status=400, error_type="mt5_rejected", details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}})
    return {"message": "Order modified successfully", "result": result._asdict()}
