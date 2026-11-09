"""Symbol and quote read operations."""

from lib import invalidate_symbol, validate_symbol
from mt5_connection import mt5
from services.errors import ServiceError


def list_symbols(search="*"):
    symbols = mt5.symbols_get(group=search)
    if symbols is None:
        return {"total": 0, "symbols": []}
    names = sorted(symbol.name for symbol in symbols)
    return {"total": len(names), "symbols": names}


def get_symbol_info(symbol):
    _ensure_symbol(symbol)
    info = mt5.symbol_info(symbol)
    if info is None:
        invalidate_symbol(symbol)
        raise ServiceError(
            f"Symbol info not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "symbol info"},
        )
    return info._asdict()


def get_symbol_tick(symbol):
    _ensure_symbol(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        invalidate_symbol(symbol)
        raise ServiceError(
            f"Symbol tick info not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "symbol tick info"},
        )
    return tick._asdict()


def _ensure_symbol(symbol):
    if not validate_symbol(symbol):
        raise ServiceError(
            f"Symbol not found: {symbol}",
            status=404,
            error_type="not_found",
            details={"resource": "symbol (not found or not selectable)"},
        )
