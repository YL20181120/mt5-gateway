from flasgger import swag_from
from flask import Blueprint, jsonify, request
from services.errors import ServiceError
from services.history import (
    copy_ticks_range,
    get_deal,
    get_deals,
    get_deals_range,
    get_order,
    get_orders,
)

from decorators import require_mt5_connection
from errors import (
    internal_error_response,
    mt5_connection_error_response,
    not_found_response,
    validation_error_response,
)
from mt5_connection import mt5  # noqa: F401

history_bp = Blueprint("history", __name__)


@history_bp.route("/get_deal_from_ticket", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "ticket",
                "in": "query",
                "type": "integer",
                "required": True,
                "description": "Position ticket number to retrieve deal information.",
            }
        ],
        "responses": {
            200: {
                "description": "Deal information retrieved successfully.",
                "schema": {"$ref": "#/definitions/DealInfo"},
            },
            400: {"description": "Invalid ticket format."},
            404: {"description": "Failed to get deal information."},
            500: {"description": "Internal server error."},
        },
    }
)
def get_deal_from_ticket_endpoint():
    """
    Get Deal Information from Position Ticket
    ---
    description: Retrieve deal information associated with a specific position ticket number.
    """
    try:
        return jsonify(get_deal(request.args.get("ticket")))

    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 404:
            return not_found_response("deal", request.args.get("ticket"))
        return internal_error_response("get_deal_from_ticket", error)

    except Exception as e:
        return internal_error_response("get_deal_from_ticket", e)


@history_bp.route("/get_order_from_ticket", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "ticket",
                "in": "query",
                "type": "integer",
                "required": True,
                "description": "Ticket number to retrieve order information.",
            }
        ],
        "responses": {
            200: {
                "description": "Order information retrieved successfully.",
                "schema": {"$ref": "#/definitions/HistoryOrder"},
            },
            400: {"description": "Invalid ticket format."},
            404: {"description": "Failed to get order information."},
            500: {"description": "Internal server error."},
        },
    }
)
def get_order_from_ticket_endpoint():
    """
    Get Order Information from Ticket
    ---
    description: Retrieve order information associated with a specific ticket number.
    """
    try:
        return jsonify(get_order(request.args.get("ticket")))

    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 404:
            return not_found_response("order", request.args.get("ticket"))
        return internal_error_response("get_order_from_ticket", error)

    except Exception as e:
        return internal_error_response("get_order_from_ticket", e)


@history_bp.route("/history_deals_get", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "from_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "Start date in ISO format.",
            },
            {
                "name": "to_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "End date in ISO format.",
            },
            {
                "name": "position",
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Position number to filter deals. Omit for every deal in the range.",
            },
        ],
        "responses": {
            200: {
                "description": "Deals history retrieved successfully.",
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/DealInfo"},
                },
            },
            400: {"description": "Invalid parameter format or missing parameters."},
            404: {"description": "Failed to get deals history."},
            500: {"description": "Internal server error."},
        },
    }
)
def history_deals_get_endpoint():
    """
    Get Deals History
    ---
    description: Retrieve historical deals within a date range, optionally filtered to one position.
    """
    try:
        return jsonify(
            get_deals(
                request.args.get("from_date"),
                request.args.get("to_date"),
                request.args.get("position"),
            )
        )
    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 503:
            return mt5_connection_error_response(
                "Get deals history", error.details.get("mt5_error")
            )
        return internal_error_response("history_deals_get", error)
    except Exception as error:
        return internal_error_response("history_deals_get", error)


@history_bp.route("/history_orders_get", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "ticket",
                "in": "query",
                "type": "integer",
                "required": True,
                "description": "Ticket number to retrieve orders history.",
            }
        ],
        "responses": {
            200: {
                "description": "Orders history retrieved successfully.",
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/HistoryOrder"},
                },
            },
            400: {"description": "Invalid ticket format or missing parameter."},
            404: {"description": "Failed to get orders history."},
            500: {"description": "Internal server error."},
        },
    }
)
def history_orders_get_endpoint():
    """
    Get Orders History
    ---
    description: Retrieve historical orders associated with a specific ticket number.
    """
    try:
        return jsonify(get_orders(request.args.get("ticket")))
    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 503:
            return mt5_connection_error_response(
                "Get orders history", error.details.get("mt5_error")
            )
        return internal_error_response("history_orders_get", error)
    except Exception as error:
        return internal_error_response("history_orders_get", error)


@history_bp.route("/history_deals_range", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "from_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "Start date in ISO format.",
            },
            {
                "name": "to_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "End date in ISO format.",
            },
            {
                "name": "magic",
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Optional magic number to filter deals.",
            },
        ],
        "responses": {
            200: {
                "description": "Deals retrieved.",
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/DealInfo"},
                },
            },
            400: {"description": "Invalid parameters."},
            500: {"description": "Internal error."},
        },
    }
)
def history_deals_range_endpoint():
    """
    Bulk Deals History (date range, optional magic filter)
    ---
    description: Retrieve historical deals within a date range without requiring a position ticket.
    """
    try:
        return jsonify(
            get_deals_range(
                request.args.get("from_date"),
                request.args.get("to_date"),
                request.args.get("magic"),
            )
        )
    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 503:
            return mt5_connection_error_response(
                "Get deals history range", error.details.get("mt5_error")
            )
        return internal_error_response("history_deals_range", error)
    except Exception as error:
        return internal_error_response("history_deals_range", error)


@history_bp.route("/copy_ticks_range", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["History"],
        "parameters": [
            {
                "name": "symbol",
                "in": "query",
                "type": "string",
                "required": True,
                "description": "Symbol name (e.g. XAUUSDm).",
            },
            {
                "name": "from_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
            },
            {
                "name": "to_date",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
            },
            {
                "name": "flags",
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "MT5 COPY_TICKS flag (default = ALL).",
            },
        ],
        "responses": {
            200: {
                "description": "Ticks retrieved.",
                "schema": {"type": "array", "items": {"type": "object"}},
            },
            400: {"description": "Invalid parameters."},
            500: {"description": "Internal error."},
        },
    }
)
def copy_ticks_range_endpoint():
    """
    Tick History (date range)
    ---
    description: Retrieve raw tick data for a symbol within a date range.
    """
    try:
        return jsonify(
            copy_ticks_range(
                request.args.get("symbol"),
                request.args.get("from_date"),
                request.args.get("to_date"),
                request.args.get("flags"),
            )
        )
    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 503:
            return mt5_connection_error_response(
                "Copy ticks range", error.details.get("mt5_error")
            )
        return internal_error_response("copy_ticks_range", error)
    except Exception as error:
        return internal_error_response("copy_ticks_range", error)
