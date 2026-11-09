import json

import mcp as mcp_module

import app as app_module


def _rpc(client, method, request_id=1, params=None):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/mcp", json=payload)


def test_mcp_initialize_and_list_tools(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    application = app_module.create_app(start_mt5=False)
    client = application.test_client()

    initialized = _rpc(client, "initialize")
    assert initialized.status_code == 200
    assert initialized.json["result"]["capabilities"]["tools"] == {}
    assert initialized.headers["MCP-Protocol-Version"] == "2025-06-18"

    listed = _rpc(client, "tools/list")
    names = {tool["name"] for tool in listed.json["result"]["tools"]}
    assert {"get_account", "place_order", "close_position"} <= names
    account_schema = next(
        tool["inputSchema"]
        for tool in listed.json["result"]["tools"]
        if tool["name"] == "get_account"
    )
    assert account_schema["properties"] == {}
    assert account_schema["additionalProperties"] is False


def test_mcp_supports_stateless_streamable_http_shape(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    application = app_module.create_app(start_mt5=False)
    client = application.test_client()

    get_response = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert get_response.status_code == 405
    assert get_response.headers["Allow"] == "POST, GET"

    rejected = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "text/plain"},
    )
    assert rejected.status_code == 406


def test_mcp_delegates_to_existing_http_route(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    application = app_module.create_app(start_mt5=False)
    client = application.test_client()

    response = _rpc(
        client,
        "tools/call",
        params={"name": "get_health", "arguments": {}},
    )

    assert response.status_code == 200
    result = response.json["result"]
    assert result["isError"] is False
    delegated = json.loads(result["content"][0]["text"])
    assert delegated["status"] == 200
    assert delegated["data"]["ok"] is True
    assert result["structuredContent"] == delegated


def test_mcp_rejects_unknown_tools(monkeypatch):
    monkeypatch.setenv("API_KEY", "")
    application = app_module.create_app(start_mt5=False)
    client = application.test_client()

    response = _rpc(
        client,
        "tools/call",
        params={"name": "mt5_api", "arguments": {}},
    )

    assert response.json["error"]["code"] == -32602


def test_mcp_adapts_partial_close_arguments(monkeypatch):
    captured = {}

    def fake_close_partial(data):
        captured.update(data)
        return {"ok": True}

    monkeypatch.setattr(mcp_module, "close_partial", fake_close_partial)

    result = mcp_module._SERVICE_HANDLERS["close_position_partial"](
        ticket=123,
        volume=0.1,
        deviation=20,
        comment="test",
    )

    assert result == {"ok": True}
    assert captured == {
        "ticket": 123,
        "volume": 0.1,
        "deviation": 20,
        "comment": "test",
    }


def test_mcp_adapts_request_object_services(monkeypatch):
    calls = {}

    def fake_check_order(data):
        calls["check_order"] = data
        return {"valid": True}

    def fake_modify_sl_tp(data):
        calls["modify_sl_tp"] = data
        return {"ok": True}

    monkeypatch.setattr(mcp_module, "check_order", fake_check_order)
    monkeypatch.setattr(mcp_module, "modify_sl_tp", fake_modify_sl_tp)

    assert mcp_module._SERVICE_HANDLERS["check_order"](
        symbol="EURUSD", volume=0.1, type="BUY"
    ) == {"valid": True}
    assert mcp_module._SERVICE_HANDLERS["modify_position_sl_tp"](
        position=123, sl=1.0, tp=2.0
    ) == {"ok": True}
    assert calls == {
        "check_order": {"symbol": "EURUSD", "volume": 0.1, "type": "BUY"},
        "modify_sl_tp": {"position": 123, "sl": 1.0, "tp": 2.0},
    }
