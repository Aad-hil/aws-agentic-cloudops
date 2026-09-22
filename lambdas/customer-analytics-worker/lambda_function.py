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

table = dynamodb.Table(
    TABLE_NAME
)


def utc_timestamp():
    return datetime.now(
        timezone.utc
    ).isoformat()


def create_response(
    status_code,
    body
):
    return {
        "statusCode": status_code,
        "body": json.dumps(body)
    }


def extract_s3_object(event):
    detail = event.get(
        "detail",
        {}
    )

    bucket = detail.get(
        "bucket",
        {}
    )

    obj = detail.get(
        "object",
        {}
    )

    bucket_name = bucket.get(
        "name"
    )

    object_key = obj.get(
        "key"
    )

    return (
        bucket_name,
        object_key
    )


def lambda_handler(
    event,
    context
):
    request_id = context.aws_request_id

    logger.info(
        json.dumps({
            "event": "worker_invoked",
            "application": APPLICATION_NAME,
            "request_id": request_id,
            "timestamp": utc_timestamp()
        })
    )

    logger.info(
        json.dumps({
            "event": "received_event",
            "event_detail_type": event.get(
                "detail-type"
            ),
            "source": event.get(
                "source"
            ),
            "request_id": request_id
        })
    )

    bucket_name, object_key = extract_s3_object(
        event
    )

    if not bucket_name or not object_key:
        logger.warning(
            json.dumps({
                "event": "invalid_event",
                "message": (
                    "S3 bucket or object key missing"
                ),
                "request_id": request_id
            })
        )

        return create_response(
            400,
            {
                "status": "ignored",
                "reason": "Invalid S3 event"
            }
        )

    logger.info(
        json.dumps({
            "event": "s3_upload_detected",
            "application": APPLICATION_NAME,
            "bucket": bucket_name,
            "object_key": object_key,
            "request_id": request_id
        })
    )

    record_id = (
        f"s3:{bucket_name}/{object_key}"
    )

    item = {
        "customer_id": record_id,
        "application": APPLICATION_NAME,
        "event_type": "S3_UPLOAD",
        "bucket": bucket_name,
        "object_key": object_key,
        "processed_at": utc_timestamp()
    }

    try:
        table.put_item(
            Item=item
        )

    except Exception as error:
        logger.exception(
            json.dumps({
                "event": "dynamodb_write_failed",
                "application": APPLICATION_NAME,
                "bucket": bucket_name,
                "object_key": object_key,
                "request_id": request_id
            })
        )

        return create_response(
            500,
            {
                "status": "failed",
                "reason": "DynamoDB write failed",
                "request_id": request_id,
                "error": str(error)
            }
        )

    logger.info(
        json.dumps({
            "event": "upload_processed",
            "application": APPLICATION_NAME,
            "bucket": bucket_name,
            "object_key": object_key,
            "record_id": record_id,
            "request_id": request_id
        })
    )

    return create_response(
        200,
        {
            "status": "processed",
            "application": APPLICATION_NAME,
            "bucket": bucket_name,
            "object_key": object_key,
            "record_id": record_id
        }
    )
