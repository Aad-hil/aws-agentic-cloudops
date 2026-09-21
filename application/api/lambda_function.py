import json
import logging
import os
from datetime import datetime, timezone


logger = logging.getLogger()
logger.setLevel(logging.INFO)

APPLICATION_NAME = os.getenv(
    "APPLICATION_NAME",
    "customer-analytics"
)


def lambda_handler(event, context):
    """
    Customer Analytics API Lambda.

    Current endpoint:
        GET /health

    This function is intentionally simple for Phase 1.
    Later phases will add application functionality.
    """

    request_id = context.aws_request_id

    logger.info(
        json.dumps({
            "event": "request_received",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    )

    response_body = {
        "status": "healthy",
        "application": APPLICATION_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    logger.info(
        json.dumps({
            "event": "health_check_success",
            "application": APPLICATION_NAME,
            "request_id": request_id
        })
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(response_body)
    }
