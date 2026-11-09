"""Market data read operations."""

import pandas as pd

from lib import get_timeframe, validate_symbol
from mt5_connection import mt5
from request_limits import validate_date_range, validate_num_bars
from services.errors import ServiceError
from time_utils import parse_iso_utc, server_epoch_to_utc


def fetch_data_pos(symbol, timeframe="M1", num_bars=100):
    if not symbol:
        raise ServiceError("Symbol parameter is required", status=400, error_type="validation_error")
    _ensure_symbol(symbol)
    try:
        count = validate_num_bars(num_bars)
        mt5_timeframe = get_timeframe(timeframe)
    except ValueError as error:
        raise ServiceError(str(error), status=400, error_type="validation_error") from error
    rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
    if rates is None:
        raise ServiceError(
            f"Rates data not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "rates data"},
        )
    return _serialize_rates(rates)


def fetch_data_range(symbol, start, end, timeframe="M1"):
    if not all([symbol, start, end]):
        raise ServiceError(
            "Symbol, start, and end parameters are required",
            status=400,
            error_type="validation_error",
        )
    _ensure_symbol(symbol)
    try:
        mt5_timeframe = get_timeframe(timeframe)
        start_date = parse_iso_utc(start)
        end_date = parse_iso_utc(end)
        validate_date_range(start_date, end_date)
    except ValueError as error:
        raise ServiceError(
            f"Invalid parameter format: {error}",
            status=400,
            error_type="validation_error",
        ) from error
    rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_date, end_date)
    if rates is None:
        raise ServiceError(
            f"Rates data not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "rates data"},
        )
    return _serialize_rates(rates)


def _ensure_symbol(symbol):
    if not validate_symbol(symbol):
        raise ServiceError(
            f"Symbol not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "symbol (not found or not selectable)"},
        )


def _serialize_rates(rates):
    frame = pd.DataFrame(rates)
    frame["time"] = frame["time"].map(
        lambda value: server_epoch_to_utc(value).isoformat().replace("+00:00", "Z")
    )
    return frame.to_dict(orient="records")
