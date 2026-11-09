"""Operational read-only services."""

from mt5_connection import mt5
from reconciliation import reconcile


def get_last_error():
    code, message = mt5.last_error()
    return {"error_code": code, "error_message": message}


def reconcile_account(magic=None):
    return reconcile(magic)
