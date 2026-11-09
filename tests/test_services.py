from collections import namedtuple
from types import SimpleNamespace

from services import account as account_service
from services import order_calculations as calculation_service
from services import symbol as symbol_service
from services.errors import ServiceError


def test_account_service_returns_serializable_snapshot(monkeypatch):
    account = namedtuple("Account", "login equity")(123, 100.5)
    monkeypatch.setattr(account_service.mt5, "account_info", lambda: account, raising=False)

    assert account_service.get_account_info() == {"login": 123, "equity": 100.5}


def test_account_service_preserves_mt5_error(monkeypatch):
    monkeypatch.setattr(account_service.mt5, "account_info", lambda: None, raising=False)
    monkeypatch.setattr(account_service.mt5, "last_error", lambda: (100, "offline"), raising=False)

    try:
        account_service.get_account_info()
    except ServiceError as error:
        assert error.status == 503
        assert error.details["mt5_error"]["error_string"] == "offline"
    else:
        raise AssertionError("expected ServiceError")


def test_symbol_service_lists_sorted_names(monkeypatch):
    monkeypatch.setattr(
        symbol_service.mt5,
        "symbols_get",
        lambda group: [SimpleNamespace(name="USDJPY"), SimpleNamespace(name="EURUSD")],
        raising=False,
    )

    assert symbol_service.list_symbols("*") == {
        "total": 2,
        "symbols": ["EURUSD", "USDJPY"],
    }


def test_symbol_service_rejects_unselectable_symbol(monkeypatch):
    monkeypatch.setattr(symbol_service, "validate_symbol", lambda symbol: False)

    try:
        symbol_service.get_symbol_tick("MISSING")
    except ServiceError as error:
        assert error.status == 404
        assert error.error_type == "not_found"
    else:
        raise AssertionError("expected ServiceError")


def test_margin_service_delegates_validated_request(monkeypatch):
    monkeypatch.setattr(calculation_service, "validate_symbol", lambda symbol: True)
    monkeypatch.setattr(calculation_service, "validate_volume", lambda symbol, volume: (True, ""))
    monkeypatch.setattr(calculation_service.mt5, "order_calc_margin", lambda *args: 12.5, raising=False)

    assert calculation_service.calculate_margin("EURUSD", 0.1, "BUY", 1.2) == {
        "margin": 12.5
    }


def test_profit_service_rejects_pending_order_type(monkeypatch):
    monkeypatch.setattr(calculation_service, "validate_symbol", lambda symbol: True)
    monkeypatch.setattr(calculation_service, "validate_volume", lambda symbol, volume: (True, ""))

    try:
        calculation_service.calculate_profit("EURUSD", 0.1, "BUY_LIMIT", 1.2, 1.3)
    except ServiceError as error:
        assert error.status == 400
    else:
        raise AssertionError("expected ServiceError")
