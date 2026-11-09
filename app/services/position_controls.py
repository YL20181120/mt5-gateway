"""Bulk position close and protection updates."""

from lib import close_all_positions, validate_sl_tp
from mt5_connection import mt5
from order_requests import OrderRequestError, build_sltp_request
from retcodes import classify_retcode
from services.errors import ServiceError


def close_all(order_type="all", magic=None):
    outcome = close_all_positions(order_type, magic)
    if not outcome["closed"] and not outcome["failed"]:
        return {"message": "No positions were closed"}
    return {
        "message": f"Closed {len(outcome['closed'])} positions; {len(outcome['failed'])} failed",
        **outcome,
    }


def modify_sl_tp(data):
    if not data or "position" not in data:
        raise ServiceError("Position data is required", status=400, error_type="validation_error")
    try:
        position = int(data["position"])
    except (TypeError, ValueError) as error:
        raise ServiceError("Position must be an integer", status=400, error_type="validation_error") from error
    positions = mt5.positions_get(ticket=position)
    if not positions:
        raise ServiceError(f"Position {position} not found", status=400, error_type="validation_error")
    try:
        request_data = build_sltp_request(data, positions[0], mt5.TRADE_ACTION_SLTP)
    except OrderRequestError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    current = positions[0]
    valid, message = validate_sl_tp(
        current.type,
        current.price_current,
        request_data["sl"] if request_data["sl"] > 0 else None,
        request_data["tp"] if request_data["tp"] > 0 else None,
    )
    if not valid:
        raise ServiceError(message, status=400, error_type="validation_error")
    result = mt5.order_send(request_data)
    if result is None:
        raise ServiceError("Modify SL/TP outcome is unknown", status=502, error_type="unknown_outcome", details={"retry_guidance": "Reconcile positions and order/deal history before retrying."})
    info = classify_retcode(result.retcode)
    if not info.is_success:
        raise ServiceError(f"Modify SL/TP failed: {result.comment}", status=400, error_type="mt5_rejected", details={"mt5_error": {"retcode": result.retcode, "comment": result.comment}})
    return {"message": "SL/TP modified successfully", "result": result._asdict()}
