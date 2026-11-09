import json

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
