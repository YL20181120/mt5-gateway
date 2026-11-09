"""Position read operations."""

from lib import get_positions
from mt5_connection import mt5
from services.errors import ServiceError


def get_open_positions(magic=None):
    positions = get_positions(magic)
    if positions is None:
        raise ServiceError(
            "Failed to retrieve positions",
            status=500,
            error_type="service_error",
        )
    if positions.empty:
        return []
    return positions.to_dict(orient="records")


def get_positions_total():
    total = mt5.positions_total()
    if total is None:
        raise ServiceError(
            "Failed to get positions total",
            status=400,
            error_type="validation_error",
        )
    return {"total": total}
