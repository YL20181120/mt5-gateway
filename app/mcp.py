"""Typed MCP tools backed directly by the existing Flask route functions."""

import json
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, Response, current_app, request
from services import account as account_service
from services import symbol as symbol_service
from services.errors import ServiceError
from services.history import (
    copy_ticks_range,
    get_deal,
    get_deals,
    get_deals_range,
    get_order,
    get_orders,
)
from services.market import fetch_data_pos, fetch_data_range
from services.operational import get_last_error, reconcile_account
from services.order_calculations import calculate_margin, calculate_profit
from services.order_check import check_order
from services.order_execution import send_order
from services.order_modify import modify_order as modify_pending_order
from services.pending_orders import cancel_order as cancel_pending_order
from services.pending_orders import list_pending_orders
from services.position_close import close_one, close_partial
from services.position_controls import close_all, modify_sl_tp
from services.positions import get_open_positions, get_positions_total

from mt5_connection import MT5Connection

mcp_bp = Blueprint("mcp", __name__)
_SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
_SERVICE_HANDLERS = {
    "get_account": account_service.get_account_info,
    "list_symbols": symbol_service.list_symbols,
    "get_symbol_info": symbol_service.get_symbol_info,
    "get_symbol_tick": symbol_service.get_symbol_tick,
    "get_bars": fetch_data_pos,
    "get_bars_range": fetch_data_range,
    "get_positions": get_open_positions,
    "get_positions_total": get_positions_total,
    "get_deal": get_deal,
    "get_historical_order": get_order,
    "get_deals": get_deals,
    "get_historical_orders": get_orders,
    "get_deals_range": get_deals_range,
    "copy_ticks_range": copy_ticks_range,
    "calculate_margin": calculate_margin,
    "calculate_profit": calculate_profit,
    "check_order": check_order,
    "get_pending_orders": list_pending_orders,
    "cancel_order": cancel_pending_order,
    "modify_order": lambda ticket, **data: modify_pending_order(ticket, data),
    "close_position": lambda position: close_one(position),
    "close_position_partial": close_partial,
    "close_all_positions": lambda order_type="all", magic=None: close_all(order_type, magic),
    "modify_position_sl_tp": modify_sl_tp,
    "place_order": lambda idempotency_key=None, **data: send_order(data, idempotency_key)["payload"],
    "reconcile": reconcile_account,
    "get_last_error": get_last_error,
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    method: str
    endpoint: str
    path: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...] = ()
    query_fields: tuple[str, ...] = ()
    path_fields: tuple[str, ...] = ()


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


def _integer(description: str) -> dict[str, str]:
    return {"type": "integer", "description": description}


def _number(description: str) -> dict[str, str]:
    return {"type": "number", "description": description}


_TOOLS = (
    Tool("get_health", "获取 MT5 Gateway 健康状态。", "GET", "health.health_check", "/health", {}),
    Tool("get_account", "获取当前账户状态。", "GET", "account.get_account_info", "/account", {}),
    Tool("list_symbols", "列出可交易品种，可按名称模式过滤。", "GET", "symbol.get_symbols_endpoint", "/symbols", {"search": _string("过滤模式，例如 *EUR*")}, query_fields=("search",)),
    Tool("get_symbol_info", "获取指定品种的交易属性。", "GET", "symbol.get_symbol_info", "/symbol_info/{symbol}", {"symbol": _string("品种名称")}, ("symbol",), path_fields=("symbol",)),
    Tool("get_symbol_tick", "获取指定品种的最新报价。", "GET", "symbol.get_symbol_info_tick_endpoint", "/symbol_info_tick/{symbol}", {"symbol": _string("品种名称")}, ("symbol",), path_fields=("symbol",)),
    Tool("get_bars", "获取指定品种最近的 K 线。", "GET", "data.fetch_data_pos_endpoint", "/fetch_data_pos", {"symbol": _string("品种名称"), "timeframe": _string("周期，例如 M1、H1"), "num_bars": _integer("K 线数量")}, ("symbol",), ("symbol", "timeframe", "num_bars")),
    Tool("get_bars_range", "获取指定时间范围内的 K 线。", "GET", "data.fetch_data_range_endpoint", "/fetch_data_range", {"symbol": _string("品种名称"), "start": _string("ISO 8601 开始时间"), "end": _string("ISO 8601 结束时间"), "timeframe": _string("周期")}, ("symbol", "start", "end"), ("symbol", "start", "end", "timeframe")),
    Tool("get_positions", "获取当前持仓。", "GET", "position.get_positions_endpoint", "/get_positions", {"magic": _integer("可选 magic")}, query_fields=("magic",)),
    Tool("get_positions_total", "获取当前持仓数量。", "GET", "position.positions_total_endpoint", "/positions_total", {}),
    Tool("get_pending_orders", "获取当前挂单。", "GET", "order.get_pending_orders", "/orders", {"symbol": _string("可选品种"), "ticket": _integer("可选订单号")}, query_fields=("symbol", "ticket")),
    Tool("get_deal", "按 ticket 获取一笔成交。", "GET", "history.get_deal_from_ticket_endpoint", "/get_deal_from_ticket", {"ticket": _integer("成交 ticket")}, ("ticket",), ("ticket",)),
    Tool("get_historical_order", "按 ticket 获取一笔历史订单。", "GET", "history.get_order_from_ticket_endpoint", "/get_order_from_ticket", {"ticket": _integer("订单 ticket")}, ("ticket",), ("ticket",)),
    Tool("get_deals", "获取时间范围内的成交记录。", "GET", "history.history_deals_get_endpoint", "/history_deals_get", {"from_date": _string("ISO 8601 开始时间"), "to_date": _string("ISO 8601 结束时间"), "position": _integer("可选持仓号")}, ("from_date", "to_date"), ("from_date", "to_date", "position")),
    Tool("get_historical_orders", "获取指定 ticket 的历史订单。", "GET", "history.history_orders_get_endpoint", "/history_orders_get", {"ticket": _integer("订单 ticket")}, ("ticket",), ("ticket",)),
    Tool("get_deals_range", "按时间范围获取成交，可按 magic 过滤。", "GET", "history.history_deals_range_endpoint", "/history_deals_range", {"from_date": _string("ISO 8601 开始时间"), "to_date": _string("ISO 8601 结束时间"), "magic": _integer("可选 magic")}, ("from_date", "to_date"), ("from_date", "to_date", "magic")),
    Tool("copy_ticks_range", "获取时间范围内的原始 tick。", "GET", "history.copy_ticks_range_endpoint", "/copy_ticks_range", {"symbol": _string("品种名称"), "from_date": _string("ISO 8601 开始时间"), "to_date": _string("ISO 8601 结束时间"), "flags": _integer("MT5 tick flags")}, ("symbol", "from_date", "to_date"), ("symbol", "from_date", "to_date", "flags")),
    Tool("place_order", "直接下达 MT5 订单。建议提供稳定的 idempotency_key。", "POST", "order.send_market_order_endpoint", "/order", {"symbol": _string("品种名称"), "volume": _number("交易手数"), "type": _string("BUY、SELL 或挂单类型"), "price": _number("挂单价格"), "sl": _number("止损价"), "tp": _number("止盈价"), "deviation": _integer("允许滑点"), "magic": _integer("magic"), "comment": _string("订单备注"), "type_filling": _string("成交类型"), "expiration": _integer("GTD Unix 时间戳"), "client_order_id": _string("幂等订单 ID"), "idempotency_key": _string("幂等键")}, ("symbol", "volume", "type")),
    Tool("check_order", "执行 MT5 订单预检查，不实际下单。", "POST", "order.order_check_endpoint", "/order_check", {"symbol": _string("品种名称"), "volume": _number("交易手数"), "type": _string("订单类型"), "price": _number("价格")}, ("symbol", "volume", "type")),
    Tool("calculate_margin", "计算订单所需保证金。", "POST", "order.order_calc_margin_endpoint", "/order_calc_margin", {"symbol": _string("品种名称"), "volume": _number("交易手数"), "type": _string("订单类型"), "price": _number("价格")}, ("symbol", "volume", "type", "price")),
    Tool("calculate_profit", "计算订单预期盈亏。", "POST", "order.order_calc_profit_endpoint", "/order_calc_profit", {"symbol": _string("品种名称"), "volume": _number("交易手数"), "type": _string("订单类型"), "price_open": _number("开仓价"), "price_close": _number("平仓价")}, ("symbol", "volume", "type", "price_open", "price_close")),
    Tool("cancel_order", "取消指定挂单。", "DELETE", "order.cancel_order", "/orders/{ticket}", {"ticket": _integer("订单号")}, ("ticket",), path_fields=("ticket",)),
    Tool("modify_order", "修改指定挂单。", "PUT", "order.modify_order", "/orders/{ticket}", {"ticket": _integer("订单号"), "price": _number("新价格"), "sl": _number("止损价"), "tp": _number("止盈价"), "expiration": _integer("GTD Unix 时间戳")}, ("ticket",), path_fields=("ticket",)),
    Tool("close_position", "平掉指定持仓。", "POST", "position.close_position_endpoint", "/close_position", {"position": {"type": "object", "description": "包含 ticket 的持仓对象"}}, ("position",)),
    Tool("close_position_partial", "部分平掉指定持仓。", "POST", "position.close_position_partial_endpoint", "/position_close_partial", {"ticket": _integer("持仓号"), "volume": _number("平仓手数"), "deviation": _integer("允许滑点"), "comment": _string("订单备注")}, ("ticket", "volume")),
    Tool("close_all_positions", "平掉符合条件的全部持仓。", "POST", "position.close_all_positions_endpoint", "/close_all_positions", {"order_type": _string("BUY、SELL 或 all"), "magic": _integer("可选 magic")}),
    Tool("modify_position_sl_tp", "修改持仓止损止盈。", "POST", "position.modify_sl_tp_endpoint", "/modify_sl_tp", {"position": {"type": "object"}, "sl": _number("止损价"), "tp": _number("止盈价"), "clear_sl": {"type": "boolean"}, "clear_tp": {"type": "boolean"}, "idempotency_key": _string("幂等键")}, ("position",)),
    Tool("reconcile", "读取经纪商真实持仓、挂单和近期成交并对账。", "GET", "control.reconcile_endpoint", "/reconcile", {"magic": _integer("可选 magic")}, query_fields=("magic",)),
    Tool("get_last_error", "获取 MT5 最近错误。", "GET", "error.last_error_endpoint", "/last_error", {}),
    Tool("engage_kill_switch", "启用交易 kill switch，可选 flatten。", "POST", "control.engage_kill_switch", "/kill", {"flatten": {"type": "boolean"}}, query_fields=("flatten",)),
    Tool("release_kill_switch", "解除交易 kill switch。", "POST", "control.release_kill_switch", "/kill/release", {}),
)


def _jsonrpc(payload: dict[str, Any], status: int = 200) -> Response:
    response = Response(json.dumps(payload, ensure_ascii=False), status=status)
    response.content_type = "application/json"
    response.headers["X-Skip-Response-Envelope"] = "1"
    response.headers["MCP-Protocol-Version"] = _SUPPORTED_PROTOCOL_VERSIONS[0]
    return response


def _schema(tool: Tool) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": tool.properties,
        "required": list(tool.required),
        "additionalProperties": False,
    }


def _invoke(tool: Tool, arguments: dict[str, Any]) -> dict[str, Any]:
    missing = [name for name in tool.required if name not in arguments]
    if missing:
        return {"error": f"missing required arguments: {', '.join(missing)}"}
    unknown = sorted(set(arguments) - set(tool.properties))
    if unknown:
        return {"error": f"unknown arguments: {', '.join(unknown)}"}
    service_handler = _SERVICE_HANDLERS.get(tool.name)
    if service_handler is not None:
        connection = MT5Connection.get_instance()
        if not connection.ensure_connection():
            return {
                "status": 503,
                "data": {
                    "error": "MT5 unavailable",
                    "error_type": "connection_error",
                    "mt5_status": connection.get_status().value,
                    "detail": connection.get_last_error(),
                },
            }
        try:
            result = service_handler(**arguments)
            if isinstance(result, tuple) and len(result) == 2:
                return {"status": result[1], "data": result[0]}
            return {"status": 200, "data": result}
        except ServiceError as error:
            data = {"error": error.message, "error_type": error.error_type}
            if error.details:
                data.update(error.details)
            return {"status": error.status, "data": data}
    path = tool.path.format(**{name: arguments[name] for name in tool.path_fields})
    query = {name: arguments[name] for name in tool.query_fields if name in arguments}
    body = {name: value for name, value in arguments.items() if name not in tool.query_fields and name not in tool.path_fields and name != "idempotency_key"}
    headers = {}
    if arguments.get("idempotency_key"):
        headers["Idempotency-Key"] = arguments["idempotency_key"]
    if request.headers.get("Authorization"):
        headers["Authorization"] = request.headers["Authorization"]
    with current_app.test_request_context(path, method=tool.method, query_string=query, json=body or None, headers=headers):
        response = current_app.preprocess_request()
        if response is None:
            handler = current_app.view_functions[tool.endpoint]
            response = handler(**{name: arguments[name] for name in tool.path_fields})
        response = current_app.process_response(current_app.make_response(response))
        try:
            data = response.get_json()
        except Exception:
            data = response.get_data(as_text=True)
        return {"status": response.status_code, "data": data}


@mcp_bp.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    if request.method == "GET":
        response = Response(status=405)
        response.headers["Allow"] = "POST, GET"
        return response
    if request.method == "DELETE":
        response = Response(status=405)
        response.headers["Allow"] = "POST, GET"
        return response
    accept = request.headers.get("Accept", "")
    if accept and not any(value in accept for value in ("application/json", "text/event-stream", "*/*")):
        return _jsonrpc({"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "Accept must include application/json or text/event-stream"}}, 406)
    message = request.get_json(silent=True)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _jsonrpc({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        params = message.get("params", {})
        requested_version = params.get("protocolVersion") if isinstance(params, dict) else None
        version = requested_version if requested_version in _SUPPORTED_PROTOCOL_VERSIONS else _SUPPORTED_PROTOCOL_VERSIONS[0]
        response = _jsonrpc({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "mt5-gateway", "version": "1"}}})
        response.headers["MCP-Protocol-Version"] = version
        return response
    if method == "notifications/initialized":
        return Response(status=202)
    if method == "tools/list":
        tools = [{"name": tool.name, "description": tool.description, "inputSchema": _schema(tool)} for tool in _TOOLS]
        return _jsonrpc({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}})
    if method == "tools/call":
        params = message.get("params", {})
        selected = next((tool for tool in _TOOLS if isinstance(params, dict) and tool.name == params.get("name")), None)
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if selected is None or not isinstance(arguments, dict):
            return _jsonrpc({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Unknown tool or invalid arguments"}})
        result = _invoke(selected, arguments)
        is_error = "error" in result or result.get("status", 200) >= 400
        return _jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    # Keep text for clients that only consume content blocks.
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    # Expose the actual JSON result for MCP clients and agents.
                    "structuredContent": result,
                    "isError": is_error,
                },
            }
        )
    return _jsonrpc({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})
