from flasgger import swag_from
from flask import Blueprint, g, jsonify, request
from services import order_execution as order_execution_service
from services.errors import ServiceError
from services.order_calculations import calculate_margin, calculate_profit
from services.order_check import check_order
from services.order_execution import send_order as send_order_service
from services.order_modify import modify_order as modify_pending_order
from services.pending_orders import cancel_order as cancel_pending_order
from services.pending_orders import list_pending_orders

from decorators import require_mt5_connection
from errors import internal_error_response, validation_error_response
from mt5_connection import mt5  # noqa: F401

order_bp = Blueprint("order", __name__)
FILL_CONFIRM_TIMEOUT_MS = order_execution_service.FILL_CONFIRM_TIMEOUT_MS
FILL_CONFIRM_POLL_MS = order_execution_service.FILL_CONFIRM_POLL_MS
idempotency_store = order_execution_service.idempotency_store


@order_bp.route("/order", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Send market or pending order",
        "description": "Execute a market order immediately or place a pending order. Market orders (BUY/SELL) execute at current price. Pending orders (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP) are placed and triggered when price conditions are met.",
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/OrderRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Order executed or placed successfully.",
                "schema": {"$ref": "#/definitions/OrderResponse"},
            },
            400: {
                "description": "Validation error or order rejected by broker.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            503: {
                "description": "MT5 connection unavailable",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def send_market_order_endpoint():
    """
    Send Order
    ---
    description: Execute a market order or place a pending order for a specified symbol.
    """
    try:
        order_execution_service.idempotency_store = idempotency_store
        order_execution_service.FILL_CONFIRM_TIMEOUT_MS = FILL_CONFIRM_TIMEOUT_MS
        order_execution_service.FILL_CONFIRM_POLL_MS = FILL_CONFIRM_POLL_MS
        result = send_order_service(
            request.get_json(silent=True),
            request.headers.get("Idempotency-Key"),
            getattr(g, "request_id", "unknown"),
        )
        response = jsonify(result["payload"])
        if result.get("replayed"):
            response.headers["Idempotent-Replayed"] = "true"
        return response, result["status"]
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("send_order", error)


@order_bp.route("/order_check", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Validate order without executing",
        "description": "Check if an order would be accepted and calculate margin requirements without actually placing it. Useful for pre-trade validation and risk management.",
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/OrderCheckRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Order validation result (valid=true means order would be accepted).",
                "schema": {"$ref": "#/definitions/OrderCheckResponse"},
            },
            400: {
                "description": "Validation failed - order parameters invalid or would be rejected.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def order_check_endpoint():
    """
    Check Order Validity
    ---
    description: Validate an order without executing it to check margin requirements and feasibility.
    """
    try:
        result = check_order(request.get_json(silent=True))
        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
        return jsonify(result)
    except ServiceError as error:
        return validation_error_response(error.message, error.details)
    except Exception as error:
        return internal_error_response("order_check", error)


@order_bp.route("/order_calc_margin", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Calculate required margin",
        "description": "Calculate how much margin (collateral) would be required to open a position. Does not place any order.",
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/MarginCalculationRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Margin calculated successfully.",
                "schema": {"$ref": "#/definitions/MarginCalculationResponse"},
            },
            400: {
                "description": "Invalid parameters or margin calculation unavailable for this symbol.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def order_calc_margin_endpoint():
    """
    Calculate Order Margin
    ---
    description: Calculate the required margin for an order without placing it.
    """
    try:
        return jsonify(calculate_margin(**(request.get_json(silent=True) or {})))
    except ServiceError as error:
        return validation_error_response(error.message, error.details)
    except Exception as error:
        return internal_error_response("order_calc_margin", error)


@order_bp.route("/order_calc_profit", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Calculate hypothetical profit",
        "description": "Calculate profit/loss for a hypothetical position between two prices. Does NOT include swap or commission - only price difference profit.",
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/ProfitCalculationRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Profit calculated successfully.",
                "schema": {"$ref": "#/definitions/ProfitCalculationResponse"},
            },
            400: {
                "description": "Invalid parameters or profit calculation unavailable for this symbol.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def order_calc_profit_endpoint():
    """
    Calculate Order Profit
    ---
    description: Calculate the hypothetical profit for closing a position at a given price.
    """
    try:
        return jsonify(calculate_profit(**(request.get_json(silent=True) or {})))
    except ServiceError as error:
        return validation_error_response(error.message, error.details)
    except Exception as error:
        return internal_error_response("order_calc_profit", error)


@order_bp.route("/orders", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Get pending orders",
        "description": "Retrieve all pending orders (LIMIT and STOP orders that have not been triggered yet). Does NOT include active positions - use /positions for that.",
        "parameters": [
            {
                "name": "symbol",
                "in": "query",
                "type": "string",
                "required": False,
                "description": "Filter pending orders by symbol (e.g., EURUSD)",
                "example": "EURUSD",
            },
            {
                "name": "ticket",
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Get specific pending order by ticket number",
                "example": 123456789,
            },
        ],
        "responses": {
            200: {
                "description": "Pending orders retrieved successfully. Returns empty array if no pending orders.",
                "schema": {"$ref": "#/definitions/PendingOrdersResponse"},
            },
            400: {
                "description": "Invalid parameters (e.g., invalid symbol or ticket format).",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            503: {
                "description": "MT5 unavailable or failed to retrieve orders.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def get_pending_orders():
    """
    Get Pending Orders
    ---
    description: Retrieve all pending orders, optionally filtered by symbol or ticket.
    """
    try:
        return jsonify(
            list_pending_orders(
                request.args.get("symbol"), request.args.get("ticket")
            )
        )
    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        return jsonify({"error": error.message, "error_type": error.error_type}), error.status
    except Exception as error:
        return internal_error_response("get_pending_orders", error)


@order_bp.route("/orders/<int:ticket>", methods=["DELETE"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Cancel pending order",
        "description": "Cancel a pending order by ticket number. Only works for pending orders (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP). Cannot cancel executed market orders or active positions.",
        "parameters": [
            {
                "name": "ticket",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "Order ticket number to cancel",
                "example": 123456789,
            }
        ],
        "responses": {
            200: {
                "description": "Order cancelled successfully.",
                "schema": {"$ref": "#/definitions/OrderResponse"},
            },
            400: {
                "description": "Invalid ticket or order cannot be cancelled.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            404: {
                "description": "Order not found.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            503: {
                "description": "MT5 unavailable",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def cancel_order(ticket):
    """
    Cancel Pending Order
    ---
    description: Cancel a pending order using TRADE_ACTION_REMOVE.
    """
    try:
        return jsonify(cancel_pending_order(ticket))
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("cancel_order", error)


@order_bp.route("/orders/<int:ticket>", methods=["PUT"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Order"],
        "summary": "Modify pending order",
        "description": "Modify a pending order's price, stop loss, or take profit. Only works for pending orders (BUY_LIMIT, SELL_LIMIT, BUY_STOP, SELL_STOP).",
        "parameters": [
            {
                "name": "ticket",
                "in": "path",
                "type": "integer",
                "required": True,
                "description": "Order ticket number to modify",
                "example": 123456789,
            },
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/OrderModificationRequest"},
            },
        ],
        "responses": {
            200: {
                "description": "Order modified successfully.",
                "schema": {"$ref": "#/definitions/OrderResponse"},
            },
            400: {
                "description": "Invalid parameters or modification rejected.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            404: {
                "description": "Order not found.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
            503: {
                "description": "MT5 unavailable",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def modify_order(ticket):
    """
    Modify Pending Order
    ---
    description: Modify a pending order's price, SL, or TP using TRADE_ACTION_MODIFY.
    """
    try:
        return jsonify(modify_pending_order(ticket, request.get_json(silent=True)))
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("modify_order", error)
