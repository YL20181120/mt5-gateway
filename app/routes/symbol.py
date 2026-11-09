import logging

from flasgger import swag_from
from flask import Blueprint, jsonify, request
from services.errors import ServiceError
from services.symbol import (
    get_symbol_info as get_symbol_info_service,
)
from services.symbol import (
    get_symbol_tick as get_symbol_tick_service,
)
from services.symbol import (
    list_symbols as list_symbols_service,
)

from decorators import require_mt5_connection
from errors import internal_error_response, not_found_response

symbol_bp = Blueprint("symbol", __name__)
logger = logging.getLogger(__name__)


@symbol_bp.route("/symbols", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Symbol"],
        "parameters": [
            {
                "name": "search",
                "in": "query",
                "type": "string",
                "required": False,
                "description": 'Filter symbols by name (e.g., "*EUR*", "USD*").',
            }
        ],
        "responses": {
            200: {
                "description": "List of symbols retrieved successfully.",
                "schema": {"$ref": "#/definitions/SymbolsListResponse"},
            },
            500: {"description": "Internal server error."},
        },
    }
)
def get_symbols_endpoint():
    """
    Get All Available Symbols
    ---
    description: Retrieve a list of all symbol names available on the MT5 server.
    """
    try:
        search = request.args.get("search", "*")
        return jsonify(list_symbols_service(search))

    except Exception as e:
        return internal_error_response("get_symbols", e)


@symbol_bp.route("/symbol_info_tick/<symbol>", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Symbol"],
        "parameters": [
            {
                "name": "symbol",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "Symbol name to retrieve tick information.",
            }
        ],
        "responses": {
            200: {
                "description": "Tick information retrieved successfully.",
                "schema": {"$ref": "#/definitions/SymbolTickInfo"},
            },
            404: {"description": "Failed to get symbol tick info."},
        },
    }
)
def get_symbol_info_tick_endpoint(symbol):
    """
    Get Symbol Tick Information
    ---
    description: Retrieve the latest tick information for a given symbol.
    """
    try:
        return jsonify(get_symbol_tick_service(symbol))

    except ServiceError as e:
        if e.status == 404:
            return not_found_response(e.details.get("resource", "symbol tick info"), symbol)
        return internal_error_response("get_symbol_info_tick", e)
    except Exception as e:
        return internal_error_response("get_symbol_info_tick", e)


@symbol_bp.route("/symbol_info/<symbol>", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Symbol"],
        "parameters": [
            {
                "name": "symbol",
                "in": "path",
                "type": "string",
                "required": True,
                "description": "Symbol name to retrieve information.",
            }
        ],
        "responses": {
            200: {
                "description": "Symbol information retrieved successfully.",
                "schema": {"$ref": "#/definitions/SymbolInfo"},
            },
            404: {"description": "Failed to get symbol info."},
        },
    }
)
def get_symbol_info(symbol):
    """
    Get Symbol Information
    ---
    description: Retrieve detailed information for a given symbol.
    """
    try:
        return jsonify(get_symbol_info_service(symbol))

    except ServiceError as e:
        if e.status == 404:
            return not_found_response(e.details.get("resource", "symbol info"), symbol)
        return internal_error_response("get_symbol_info", e)
    except Exception as e:
        return internal_error_response("get_symbol_info", e)
