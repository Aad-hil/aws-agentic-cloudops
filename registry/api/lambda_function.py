import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.getenv(
    "TABLE_NAME",
    "customer-analytics-registry"
)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Application Registry API.

    Current operation:
        get_application

    Example event:
        {
            "operation": "get_application",
            "application_id": "customer-analytics"
        }

    The API is intentionally read-only.
    """

    request_id = context.aws_request_id

    logger.info(
        json.dumps({
            "event": "registry_request_received",
            "request_id": request_id,
            "event_payload": event
        })
    )

    operation = event.get("operation")

    if operation != "get_application":
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unsupported operation",
                "supported_operations": [
                    "get_application"
                ]
            })
        }

    application_id = event.get("application_id")

    if not application_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "application_id is required"
            })
        }

    try:
        response = table.get_item(
            Key={
                "application_id": application_id
            }
        )

    except ClientError:
        logger.exception(
            "Failed to read application registry"
        )

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to read application registry",
                "request_id": request_id
            })
        }

    item = response.get("Item")

    if not item:
        logger.warning(
            json.dumps({
                "event": "application_not_found",
                "application_id": application_id,
                "request_id": request_id
            })
        )

        return {
            "statusCode": 404,
            "body": json.dumps({
                "error": "Application not found",
                "application_id": application_id
            })
        }

    logger.info(
        json.dumps({
            "event": "application_found",
            "application_id": application_id,
            "resource_count": len(item.get("resources", [])),
            "dependency_count": len(item.get("dependencies", [])),
            "request_id": request_id
        })
    )

    return {
        "statusCode": 200,
        "body": json.dumps(item)
    }
}
