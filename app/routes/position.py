import services.position_close as position_close_service
from flasgger import swag_from
from flask import Blueprint, g, jsonify, request
from services.errors import ServiceError
from services.position_close import close_one, close_partial
from services.position_controls import close_all, modify_sl_tp
from services.positions import get_open_positions, get_positions_total

from decorators import require_mt5_connection
from errors import (
    internal_error_response,
    validation_error_response,
)
from lib import close_position

position_bp = Blueprint("position", __name__)


def _request_id():
    return getattr(g, "request_id", None)


@position_bp.route("/close_position", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/ClosePositionRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Position closed successfully.",
                "schema": {"$ref": "#/definitions/ClosePositionResponse"},
            },
            400: {"description": "Bad request or failed to close position."},
            500: {"description": "Internal server error."},
        },
    }
)
def close_position_endpoint():
    """
    Close a Specific Position
    ---
    description: Close a specific trading position based on the provided position data.
    """
    try:
        position_close_service.close_position = close_position
        data = request.get_json(silent=True) or {}
        return jsonify(close_one(data.get("position"), _request_id()))
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("close_position", error)


@position_bp.route("/position_close_partial", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "summary": "Partially close position",
        "description": "Close a portion of an open position by specifying the volume to close. The remaining volume stays open.",
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/ClosePositionPartialRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Position partially closed successfully.",
                "schema": {"$ref": "#/definitions/ClosePositionPartialResponse"},
            },
            400: {"description": "Validation error or failed to close position."},
            503: {"description": "MT5 unavailable"},
        },
    }
)
def close_position_partial_endpoint():
    """
    Partially Close Position
    ---
    description: Close a specific volume of an open position, leaving the remainder open.
    """
    try:
        position_close_service.close_position = close_position
        return jsonify(close_partial(request.get_json(silent=True), _request_id()))
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("close_position_partial", error)

@position_bp.route("/close_all_positions", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": False,
                "schema": {"$ref": "#/definitions/CloseAllPositionsRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "Closed positions successfully.",
                "schema": {"$ref": "#/definitions/CloseAllPositionsResponse"},
            },
            400: {"description": "Bad request or no positions were closed."},
            500: {"description": "Internal server error."},
        },
    }
)
def close_all_positions_endpoint():
    """
    Close All Positions
    ---
    description: Close all open trading positions based on optional filters like order type and magic number.
    """
    try:
        data = request.get_json(silent=True) or {}
        result = close_all(data.get("order_type", "all"), data.get("magic"))
        return jsonify(result), 207 if result.get("failed") else 200
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("close_all_positions", error)


@position_bp.route("/modify_sl_tp", methods=["POST"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "parameters": [
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"$ref": "#/definitions/ModifySLTPRequest"},
            }
        ],
        "responses": {
            200: {
                "description": "SL/TP modified successfully.",
                "schema": {"$ref": "#/definitions/ModifySLTPResponse"},
            },
            400: {"description": "Bad request or failed to modify SL/TP."},
            500: {"description": "Internal server error."},
        },
    }
)
def modify_sl_tp_endpoint():
    """
    Modify Stop Loss and Take Profit
    ---
    description: Modify the Stop Loss (SL) and Take Profit (TP) levels for a specific position.
    """
    try:
        return jsonify(modify_sl_tp(request.get_json(silent=True)))
    except ServiceError as error:
        return jsonify({"error": error.message, "error_type": error.error_type, **(error.details or {})}), error.status
    except Exception as error:
        return internal_error_response("modify_sl_tp", error)


@position_bp.route("/get_positions", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "parameters": [
            {
                "name": "magic",
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Magic number to filter positions.",
            }
        ],
        "responses": {
            200: {
                "description": "Positions retrieved successfully.",
                "schema": {"$ref": "#/definitions/PositionsResponse"},
            },
            400: {"description": "Bad request or failed to retrieve positions."},
            500: {"description": "Internal server error."},
        },
    }
)
def get_positions_endpoint():
    """
    Get Open Positions
    ---
    description: Retrieve all open trading positions, optionally filtered by magic number.
    """
    try:
        magic = request.args.get("magic", type=int)

        return jsonify(get_open_positions(magic)), 200

    except ServiceError as error:
        return internal_error_response("get_positions", error)

    except Exception as e:
        return internal_error_response("get_positions", e)


@position_bp.route("/positions_total", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Position"],
        "responses": {
            200: {
                "description": "Total number of open positions retrieved successfully.",
                "schema": {"$ref": "#/definitions/PositionsTotalResponse"},
            },
            400: {"description": "Failed to get positions total."},
            500: {"description": "Internal server error."},
        },
    }
)
def positions_total_endpoint():
    """
    Get Total Open Positions
    ---
    description: Retrieve the total number of open trading positions.
    """
    try:
        return jsonify(get_positions_total())

    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        return internal_error_response("positions_total", error)

    except Exception as e:
        return internal_error_response("positions_total", e)
