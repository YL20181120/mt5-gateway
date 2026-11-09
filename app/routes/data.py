from flasgger import swag_from
from flask import Blueprint, jsonify, request
from services.errors import ServiceError
from services.market import fetch_data_pos, fetch_data_range

from decorators import require_mt5_connection
from errors import (
    internal_error_response,
    not_found_response,
    validation_error_response,
)

data_bp = Blueprint("data", __name__)


@data_bp.route("/fetch_data_pos", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Data"],
        "parameters": [
            {
                "name": "symbol",
                "in": "query",
                "type": "string",
                "required": True,
                "description": "Symbol name to fetch data for.",
            },
            {
                "name": "timeframe",
                "in": "query",
                "type": "string",
                "required": False,
                "default": "M1",
                "description": "Timeframe for the data (e.g., M1, M5, H1).",
            },
            {
                "name": "num_bars",
                "in": "query",
                "type": "integer",
                "required": False,
                "default": 100,
                "description": "Number of bars to fetch.",
            },
        ],
        "responses": {
            200: {
                "description": "Data fetched successfully.",
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/PriceBar"},
                },
            },
            400: {"description": "Invalid request parameters."},
            404: {"description": "Failed to get rates data."},
            500: {"description": "Internal server error."},
        },
    }
)
def fetch_data_pos_endpoint():
    """
    Fetch Data from Position
    ---
    description: Retrieve historical price data for a given symbol starting from a specific position.
    """
    try:
        return jsonify(fetch_data_pos(
            request.args.get("symbol"),
            request.args.get("timeframe", "M1"),
            request.args.get("num_bars", 100),
        ))

    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 404:
            return not_found_response(error.details.get("resource", "rates data"), request.args.get("symbol"))
        return internal_error_response("fetch_data_pos", error)

    except Exception as e:
        return internal_error_response("fetch_data_pos", e)


@data_bp.route("/fetch_data_range", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Data"],
        "parameters": [
            {
                "name": "symbol",
                "in": "query",
                "type": "string",
                "required": True,
                "description": "Symbol name to fetch data for.",
            },
            {
                "name": "timeframe",
                "in": "query",
                "type": "string",
                "required": False,
                "default": "M1",
                "description": "Timeframe for the data (e.g., M1, M5, H1).",
            },
            {
                "name": "start",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "Start datetime in ISO format.",
            },
            {
                "name": "end",
                "in": "query",
                "type": "string",
                "required": True,
                "format": "date-time",
                "description": "End datetime in ISO format.",
            },
        ],
        "responses": {
            200: {
                "description": "Data fetched successfully.",
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/PriceBar"},
                },
            },
            400: {"description": "Invalid request parameters."},
            404: {"description": "Failed to get rates data."},
            500: {"description": "Internal server error."},
        },
    }
)
def fetch_data_range_endpoint():
    """
    Fetch Data within a Date Range
    ---
    description: Retrieve historical price data for a given symbol within a specified date range.
    """
    try:
        return jsonify(fetch_data_range(
            request.args.get("symbol"),
            request.args.get("start"),
            request.args.get("end"),
            request.args.get("timeframe", "M1"),
        ))

    except ServiceError as error:
        if error.status == 400:
            return validation_error_response(error.message)
        if error.status == 404:
            return not_found_response(error.details.get("resource", "rates data"), request.args.get("symbol"))
        return internal_error_response("fetch_data_range", error)

    except Exception as e:
        return internal_error_response("fetch_data_range", e)
