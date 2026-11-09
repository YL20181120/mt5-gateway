"""Non-mutating order calculations."""

from constants import TRADE_ACTION_DEAL, TRADE_ACTION_PENDING
from lib import validate_symbol, validate_volume
from mt5_connection import mt5
from services.errors import ServiceError

_ORDER_TYPES = {
    "BUY": mt5.ORDER_TYPE_BUY,
    "SELL": mt5.ORDER_TYPE_SELL,
    "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
}


def calculate_margin(symbol, volume, type, price):
    data = _validate_common(symbol, volume, type)
    price = _positive(price, "Price")
    action = TRADE_ACTION_DEAL if data in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL) else TRADE_ACTION_PENDING
    margin = mt5.order_calc_margin(action, symbol, float(volume), price)
    if margin is None:
        raise ServiceError("Margin calculation unavailable", status=400, error_type="validation_error", details={"reason": "Symbol may not support this calculation or parameters are invalid"})
    if margin < 0:
        raise ServiceError("Invalid margin calculation result", status=400, error_type="validation_error")
    return {"margin": margin}


def calculate_profit(symbol, volume, type, price_open, price_close):
    data = _validate_common(symbol, volume, type, allowed=("BUY", "SELL"))
    opening = _positive(price_open, "Opening price")
    closing = _positive(price_close, "Closing price")
    profit = mt5.order_calc_profit(data, symbol, float(volume), opening, closing)
    if profit is None:
        raise ServiceError("Profit calculation unavailable", status=400, error_type="validation_error", details={"reason": "Symbol may not support this calculation"})
    return {"profit": profit}


def _validate_common(symbol, volume, type, allowed=None):
    if not symbol or volume is None or type is None:
        raise ServiceError("Missing required fields", status=400, error_type="validation_error")
    if not validate_symbol(symbol):
        raise ServiceError(f"Symbol not found or not selectable: {symbol}", status=400, error_type="validation_error")
    order_type = str(type).upper()
    allowed_types = allowed or _ORDER_TYPES.keys()
    if order_type not in allowed_types:
        raise ServiceError(f"Invalid order type: {type}", status=400, error_type="validation_error")
    try:
        numeric_volume = float(volume)
    except (TypeError, ValueError) as error:
        raise ServiceError("Volume must be positive", status=400, error_type="validation_error") from error
    if numeric_volume <= 0:
        raise ServiceError("Volume must be positive", status=400, error_type="validation_error")
    valid, message = validate_volume(symbol, numeric_volume)
    if not valid:
        raise ServiceError(message, status=400, error_type="validation_error")
    return _ORDER_TYPES[order_type]


def _positive(value, label):
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise ServiceError(f"{label} must be positive", status=400, error_type="validation_error") from error
    if numeric <= 0:
        raise ServiceError(f"{label} must be positive", status=400, error_type="validation_error")
    return numeric
