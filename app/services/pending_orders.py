"""Pending-order operations."""

from constants import ORDER_TYPE_TO_STRING
from lib import validate_symbol
from mt5_connection import mt5
from retcodes import classify_retcode
from services.errors import ServiceError


def list_pending_orders(symbol=None, ticket=None):
    if ticket:
        try:
            orders = mt5.orders_get(ticket=int(ticket))
        except (TypeError, ValueError) as error:
            raise ServiceError("Ticket must be an integer", status=400, error_type="validation_error") from error
    elif symbol:
        if not validate_symbol(symbol):
            raise ServiceError(f"Invalid symbol: {symbol}", status=400, error_type="validation_error")
        orders = mt5.orders_get(symbol=symbol)
    else:
        orders = mt5.orders_get()
    if orders is None:
        raise ServiceError("Failed to retrieve pending orders", status=503, error_type="connection_error")
    result = []
    for order in orders:
        item = order._asdict()
        item["type_str"] = ORDER_TYPE_TO_STRING.get(order.type, f"UNKNOWN_{order.type}")
        result.append(item)
    return {"total": len(result), "orders": result}


def cancel_order(ticket):
    orders = mt5.orders_get(ticket=ticket)
    if orders is None:
        raise ServiceError("Failed to retrieve order information", status=503, error_type="connection_error")
    if not orders:
        raise ServiceError(f"Order with ticket {ticket} not found", status=404, error_type="not_found")
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": ticket,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    })
    if result is None:
        raise ServiceError("Cancel order outcome is unknown", status=502, error_type="unknown_outcome", details={"retry_guidance": "Reconcile positions and order/deal history before retrying."})
    info = classify_retcode(result.retcode)
    if not info.is_success:
        raise ServiceError(
            f"Cancel order failed: {result.comment}",
            status=400,
            error_type="mt5_rejected",
            details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}},
        )
    return {"message": "Order cancelled successfully", "result": result._asdict()}
