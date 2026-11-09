"""Account read operations."""

from mt5_connection import mt5
from services.errors import ServiceError


def get_account_info():
    account_info = mt5.account_info()
    if account_info is None:
        error_code, error_string = mt5.last_error()
        raise ServiceError(
            "Failed to get account info",
            status=503,
            error_type="connection_error",
            details={"mt5_error": {"error_code": error_code, "error_string": error_string}},
        )
    return account_info._asdict()
