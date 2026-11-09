"""Historical deal, order, and tick read operations."""

from datetime import datetime

from deal_window import DealWindowError, parse_deal_window
from lib import get_deal_from_ticket, get_order_from_ticket
from mt5_connection import mt5
from request_limits import validate_date_range, validate_tick_flags
from services.errors import ServiceError


def get_deal(ticket):
    ticket = _ticket(ticket)
    deal = get_deal_from_ticket(ticket)
    if deal is None:
        raise ServiceError(f"Deal not found: {ticket}", status=404, error_type="not_found")
    return deal


def get_order(ticket):
    ticket = _ticket(ticket)
    order = get_order_from_ticket(ticket)
    if order is None:
        raise ServiceError(f"Order not found: {ticket}", status=404, error_type="not_found")
    return order


def get_deals(from_date, to_date, position=None):
    try:
        from_timestamp, to_timestamp, position = parse_deal_window(
            {"from_date": from_date, "to_date": to_date, "position": position}
        )
    except DealWindowError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    if position is not None:
        deals = mt5.history_deals_get(position=position)
        if deals is not None:
            deals = [deal for deal in deals if from_timestamp <= deal.time <= to_timestamp]
    else:
        deals = mt5.history_deals_get(from_timestamp, to_timestamp)
    if deals is None:
        raise _mt5_error("Get deals history")
    return [deal._asdict() for deal in deals]


def get_orders(ticket):
    ticket = _ticket(ticket)
    orders = mt5.history_orders_get(ticket=ticket)
    if orders is None:
        raise _mt5_error("Get orders history")
    return [order._asdict() for order in orders]


def get_deals_range(from_date, to_date, magic=None):
    from_dt, to_dt = _date_range(from_date, to_date)
    try:
        magic = None if magic is None else int(magic)
    except (TypeError, ValueError) as error:
        raise ServiceError("Invalid magic format", status=400, error_type="validation_error") from error
    deals = mt5.history_deals_get(int(from_dt.timestamp()), int(to_dt.timestamp()))
    if deals is None:
        raise _mt5_error("Get deals history range")
    result = [deal._asdict() for deal in deals]
    return [deal for deal in result if magic is None or deal.get("magic") == magic]


def copy_ticks_range(symbol, from_date, to_date, flags=None):
    from_dt, to_dt = _date_range(from_date, to_date, required_message="symbol, from_date, to_date parameters are required", symbol=symbol)
    try:
        tick_flags = mt5.COPY_TICKS_ALL if flags is None else validate_tick_flags(flags)
    except ValueError as error:
        raise ServiceError("Invalid flags format", status=400, error_type="validation_error") from error
    ticks = mt5.copy_ticks_range(symbol, from_dt, to_dt, tick_flags)
    if ticks is None:
        raise _mt5_error("Copy ticks range")
    result = []
    for tick in ticks:
        row = {"time": int(tick["time"]), "bid": float(tick["bid"]), "ask": float(tick["ask"])}
        names = tick.dtype.names if hasattr(tick, "dtype") else ()
        for name, converter in (("time_msc", int), ("last", float), ("volume", int), ("flags", int)):
            if name in names:
                row[name] = converter(tick[name])
        result.append(row)
    return result


def _ticket(value):
    if value in (None, ""):
        raise ServiceError("Ticket parameter is required", status=400, error_type="validation_error")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ServiceError("Invalid ticket format", status=400, error_type="validation_error") from error


def _date_range(from_date, to_date, required_message=None, symbol=True):
    if required_message and (not symbol or not from_date or not to_date):
        raise ServiceError(required_message, status=400, error_type="validation_error")
    if not from_date or not to_date:
        raise ServiceError("from_date and to_date parameters are required", status=400, error_type="validation_error")
    try:
        from_dt = datetime.fromisoformat(str(from_date).replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(str(to_date).replace("Z", "+00:00"))
        if from_dt >= to_dt:
            raise ValueError("from_date must be before to_date")
        validate_date_range(from_dt, to_dt)
        return from_dt, to_dt
    except ValueError as error:
        raise ServiceError(f"Invalid date format: {error}", status=400, error_type="validation_error") from error


def _mt5_error(operation):
    return ServiceError(
        f"{operation} failed because MT5 is unavailable",
        status=503,
        error_type="connection_error",
        details={"mt5_error": {"last_error": mt5.last_call_error()}},
    )
