import logging

from flasgger import swag_from
from flask import Blueprint, g, jsonify
from services.account import get_account_info as get_account_info_service
from services.errors import ServiceError

from decorators import require_mt5_connection
from errors import internal_error_response

account_bp = Blueprint("account", __name__)
logger = logging.getLogger(__name__)


@account_bp.route("/account", methods=["GET"])
@require_mt5_connection
@swag_from(
    {
        "tags": ["Account"],
        "summary": "Get account information",
        "description": "Retrieve current account state including balance, equity, margin, and leverage. This is a point-in-time snapshot - values change as positions and market move.",
        "responses": {
            200: {
                "description": "Account information retrieved successfully.",
                "schema": {"$ref": "#/definitions/AccountInfo"},
            },
            503: {
                "description": "MT5 unavailable or failed to get account info.",
                "schema": {"$ref": "#/definitions/ErrorResponse"},
            },
        },
    }
)
def get_account_info():
    """
    Get Account Information
    ---
    description: Retrieve current account information including balance, equity, margin, and other details.
    """
    try:
        try:
            account_info = get_account_info_service()
        except ServiceError as error:
            request_id = getattr(g, "request_id", None)

            response = {
                "error": "Failed to get account info",
                "error_type": "connection_error",
                **(error.details or {}),
            }

            if request_id:
                response["request_id"] = request_id

            logger.error("Failed to get account info", extra={"request_id": request_id})

            return jsonify(response), 503

        logger.info(
            "Account info retrieved: login=%s",
            account_info.get("login"),
        )

        return jsonify(account_info)

    except Exception as e:
        return internal_error_response("get_account_info", e)
