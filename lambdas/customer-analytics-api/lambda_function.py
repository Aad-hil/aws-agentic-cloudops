import json
import logging
import os
from datetime import datetime, timezone


# =========================================================
# Logging
# =========================================================

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# =========================================================
# Configuration
# =========================================================

APPLICATION_NAME = os.getenv(
    "APPLICATION_NAME",
    "customer-analytics"
)


# =========================================================
# Helper Functions
# =========================================================

def utc_timestamp():
    """
    Return the current UTC timestamp in ISO-8601 format.
    """

    return datetime.now(
        timezone.utc
    ).isoformat()


def create_response(
    status_code,
    body
):
    """
    Create a standard API response.
    """

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }


# =========================================================
# Lambda Handler
# =========================================================

def lambda_handler(
    event,
    context
):
    """
    Customer Analytics API Lambda.

    Current supported endpoint:

        GET /health

    The Lambda also supports an internal
    CloudOps incident simulation event:

        {
            "simulate_failure": true
        }

    The simulation is used only for testing
    the CloudOps Observability Agent.
    """

    request_id = context.aws_request_id

    logger.info(
        json.dumps({
            "event": "request_received",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "timestamp": utc_timestamp()
        })
    )

    if event.get(
        "simulate_failure"
    ) is True:

        logger.error(
            json.dumps({
                "event": "simulated_application_failure",
                "application": APPLICATION_NAME,
                "request_id": request_id,
                "message": (
                    "Simulated application failure "
                    "for CloudOps POC"
                ),
                "timestamp": utc_timestamp()
            })
        )

        raise RuntimeError(
            "Simulated application failure "
            "for CloudOps POC"
        )

    request_context = event.get(
        "requestContext",
        {}
    )

    http = request_context.get(
        "http",
        {}
    )

    http_method = (
        http.get("method")
        or event.get("httpMethod")
        or "GET"
    )

    path = (
        event.get("rawPath")
        or event.get("path")
        or "/health"
    )

    logger.info(
        json.dumps({
            "event": "request_parsed",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "method": http_method,
            "path": path
        })
    )

    if (
        http_method == "GET"
        and path == "/health"
    ):

        response_body = {
            "status": "healthy",
            "application": APPLICATION_NAME,
            "timestamp": utc_timestamp()
        }

        logger.info(
            json.dumps({
                "event": "health_check_success",
                "application": APPLICATION_NAME,
                "request_id": request_id
            })
        )

        return create_response(
            200,
            response_body
        )

    logger.warning(
        json.dumps({
            "event": "route_not_found",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "method": http_method,
            "path": path
        })
    )

    return create_response(
        404,
        {
            "error": "Route not found",
            "application": APPLICATION_NAME,
            "path": path
        }
    )
