import json
import logging
import os
from datetime import datetime, timezone

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


APPLICATION_NAME = os.getenv(
    "APPLICATION_NAME",
    "customer-analytics"
)

TABLE_NAME = os.getenv(
    "TABLE_NAME",
    "customer-analytics-data"
)


dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Customer Analytics background worker.

    Trigger:
        Amazon EventBridge

    Current responsibility:
        Process S3 upload events and record them in DynamoDB.
    """

    request_id = context.aws_request_id

    logger.info(
        json.dumps({
            "event": "worker_invoked",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    )

    logger.info(
        json.dumps({
            "event": "received_event",
            "event_detail_type": event.get("detail-type"),
            "source": event.get("source"),
            "request_id": request_id
        })
    )

    detail = event.get("detail", {})

    bucket_name = detail.get("bucket", {}).get("name")
    object_key = detail.get("object", {}).get("key")

    if not bucket_name or not object_key:
        logger.warning(
            json.dumps({
                "event": "invalid_event",
                "message": "S3 bucket or object key missing",
                "request_id": request_id
            })
        )

        return {
            "statusCode": 400,
            "body": json.dumps({
                "status": "ignored",
                "reason": "Invalid S3 event"
            })
        }

    logger.info(
        json.dumps({
            "event": "s3_upload_detected",
            "application": APPLICATION_NAME,
            "bucket": bucket_name,
            "object_key": object_key,
            "request_id": request_id
        })
    )

    record_id = f"s3:{bucket_name}/{object_key}"

    table.put_item(
        Item={
            "customer_id": record_id,
            "application": APPLICATION_NAME,
            "event_type": "S3_UPLOAD",
            "bucket": bucket_name,
            "object_key": object_key,
            "processed_at": datetime.now(timezone.utc).isoformat()
        }
    )

    logger.info(
        json.dumps({
            "event": "upload_processed",
            "application": APPLICATION_NAME,
            "bucket": bucket_name,
            "object_key": object_key,
            "request_id": request_id
        })
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "processed",
            "bucket": bucket_name,
            "object_key": object_key
        })
    }
