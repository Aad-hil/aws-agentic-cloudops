import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)


APPLICATION_ID = os.getenv(
    "APPLICATION_ID",
    "customer-analytics"
)

REGISTRY_FUNCTION_NAME = os.getenv(
    "REGISTRY_FUNCTION_NAME",
    "customer-analytics-registry-api"
)

LOOKBACK_MINUTES = int(
    os.getenv(
        "LOOKBACK_MINUTES",
        "15"
    )
)


lambda_client = boto3.client(
    "lambda"
)

s3_client = boto3.client(
    "s3"
)

dynamodb_client = boto3.client(
    "dynamodb"
)

events_client = boto3.client(
    "events"
)

cloudwatch_client = boto3.client(
    "cloudwatch"
)


SUPPORTED_OPERATIONS = [
    "investigate_s3",
    "investigate_dynamodb",
    "investigate_eventbridge",
    "investigate_all"
]


def utc_timestamp():
    return datetime.now(
        timezone.utc
    ).isoformat()


def get_application_registry(
    application_id
):
    """
    Retrieve application ownership information
    from the Application Registry.
    """

    response = lambda_client.invoke(
        FunctionName=REGISTRY_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "operation": "get_application",
            "application_id": application_id
        }).encode("utf-8")
    )

    payload = response[
        "Payload"
    ].read()

    registry_response = json.loads(
        payload.decode("utf-8")
    )

    status_code = registry_response.get(
        "statusCode"
    )

    if status_code != 200:
        raise RuntimeError(
            "Registry API returned status "
            f"{status_code}: "
            f"{registry_response.get('body')}"
        )

    body = registry_response.get(
        "body",
        "{}"
    )

    return json.loads(
        body
    )


def get_resources_by_service(
    registry,
    service
):
    """
    Return resources belonging to the
    requested AWS service.
    """

    resources = registry.get(
        "resources",
        []
    )

    return [
        resource
        for resource in resources
        if resource.get("service") == service
    ]


def investigate_s3(
    resources
):
    """
    Investigate registered S3 buckets.

    Read-only operations:
        - ListBucket
        - ListObjectsV2
    """

    evidence = []

    for resource in resources:

        bucket_name = resource.get(
            "resource_id"
        )

        result = {
            "resource_id": bucket_name,
            "role": resource.get("role"),
            "service": "s3"
        }

        try:

            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                MaxKeys=1
            )

            result.update({
                "status": "accessible",
                "http_status": (
                    response.get(
                        "ResponseMetadata",
                        {}
                    )
                    .get(
                        "HTTPStatusCode"
                    )
                )
            })

        except ClientError as error:

            error_code = (
                error.response
                .get("Error", {})
                .get("Code")
            )

            result.update({
                "status": "error",
                "error_code": error_code,
                "error": str(error)
            })

        except Exception as error:

            result.update({
                "status": "error",
                "error": str(error)
            })

        try:

            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                MaxKeys=20
            )

            objects = []

            for obj in response.get(
                "Contents",
                []
            ):

                last_modified = obj.get(
                    "LastModified"
                )

                objects.append({
                    "key": obj.get(
                        "Key"
                    ),
                    "size": obj.get(
                        "Size"
                    ),
                    "last_modified": (
                        last_modified.isoformat()
                        if last_modified
                        else None
                    )
                })

            result[
                "recent_objects"
            ] = objects

            result[
                "object_count_returned"
            ] = len(objects)

        except Exception as error:

            result[
                "object_listing_error"
            ] = str(error)

        evidence.append(
            result
        )

    return evidence


def investigate_dynamodb(
    resources
):
    """
    Investigate registered DynamoDB tables.

    Read-only operations:
        - DescribeTable
        - Scan
    """

    evidence = []

    for resource in resources:

        table_name = resource.get(
            "resource_id"
        )

        result = {
            "resource_id": table_name,
            "role": resource.get("role"),
            "service": "dynamodb"
        }

        try:

            response = (
                dynamodb_client
                .describe_table(
                    TableName=table_name
                )
            )

            table = response.get(
                "Table",
                {}
            )

            creation_time = table.get(
                "CreationDateTime"
            )

            result.update({
                "status": "available",
                "table_status": table.get(
                    "TableStatus"
                ),
                "item_count": table.get(
                    "ItemCount"
                ),
                "table_size_bytes": table.get(
                    "TableSizeBytes"
                ),
                "creation_date_time": (
                    creation_time.isoformat()
                    if creation_time
                    else None
                )
            })

        except ClientError as error:

            error_code = (
                error.response
                .get("Error", {})
                .get("Code")
            )

            result.update({
                "status": "error",
                "error_code": error_code,
                "error": str(error)
            })

            evidence.append(
                result
            )

            continue

        except Exception as error:

            result.update({
                "status": "error",
                "error": str(error)
            })

            evidence.append(
                result
            )

            continue

        try:

            response = (
                dynamodb_client
                .scan(
                    TableName=table_name,
                    Limit=10
                )
            )

            result[
                "sample_item_count"
            ] = len(
                response.get(
                    "Items",
                    []
                )
            )

        except Exception as error:

            result[
                "sample_scan_error"
            ] = str(error)

        evidence.append(
            result
        )

    return evidence


def get_eventbridge_metric(
    rule_name,
    event_bus,
    metric_name,
    start_time,
    end_time
):
    """
    Read an AWS/Events CloudWatch metric for a
    specific EventBridge rule.

    No datapoints are represented as no_data rather
    than zero. Missing telemetry is not treated as
    evidence of zero activity.
    """

    response = cloudwatch_client.get_metric_statistics(
        Namespace="AWS/Events",
        MetricName=metric_name,
        Dimensions=[
            {
                "Name": "RuleName",
                "Value": rule_name
            },
            {
                "Name": "EventBusName",
                "Value": event_bus
            }
        ],
        StartTime=start_time,
        EndTime=end_time,
        Period=300,
        Statistics=["Sum"]
    )

    datapoints = response.get(
        "Datapoints",
        []
    )

    if not datapoints:
        return {
            "status": "no_data",
            "value": None,
            "datapoints": 0,
            "statistic": "Sum"
        }

    value = sum(
        float(
            datapoint.get(
                "Sum",
                0
            )
        )
        for datapoint in datapoints
    )

    return {
        "status": "available",
        "value": value,
        "datapoints": len(
            datapoints
        ),
        "statistic": "Sum"
    }


def validate_eventbridge_pattern(
    event_pattern
):
    """
    Validate the registered EventBridge rule pattern
    against a representative S3 Object Created event.

    This does not publish an event and therefore does not
    trigger the application.
    """

    if not event_pattern:
        return {
            "status": "not_available",
            "matched": None,
            "reason": "Rule has no event pattern"
        }

    try:
        pattern = json.loads(
            event_pattern
        )
    except (TypeError, json.JSONDecodeError) as error:
        return {
            "status": "error",
            "matched": None,
            "reason": (
                "Event pattern is not valid JSON: "
                f"{error}"
            )
        }

    sample_event = {
        "version": "0",
        "id": "cloudops-validation-event",
        "detail-type": "Object Created",
        "source": "aws.s3",
        "account": "000000000000",
        "time": utc_timestamp(),
        "region": "us-east-1",
        "resources": [],
        "detail": {
            "bucket": {
                "name": "customer-analytics-upload-aadhil-poc"
            },
            "object": {
                "key": "cloudops-validation/sample.json",
                "size": 1
            }
        }
    }

    try:

        response = events_client.test_event_pattern(
            EventPattern=json.dumps(
                pattern
            ),
            Event=json.dumps(
                sample_event
            )
        )

        return {
            "status": "validated",
            "matched": response.get(
                "Result"
            ),
            "sample_event": sample_event
        }

    except ClientError as error:

        error_code = (
            error.response
            .get("Error", {})
            .get("Code")
        )

        return {
            "status": "error",
            "matched": None,
            "error_code": error_code,
            "reason": str(error)
        }

    except Exception as error:

        return {
            "status": "error",
            "matched": None,
            "reason": str(error)
        }


def investigate_eventbridge(
    resources
):
    """
    Investigate registered EventBridge rules.

    Read-only operations:
        - DescribeRule
        - ListTargetsByRule
        - CloudWatch AWS/Events metrics
        - TestEventPattern

    Important:
        - No PutEvents call is made.
        - Pattern validation does not prove actual delivery.
        - Missing CloudWatch datapoints are represented as
          no_data, not zero.
    """

    evidence = []

    end_time = datetime.now(
        timezone.utc
    )

    start_time = (
        end_time
        - timedelta(
            minutes=LOOKBACK_MINUTES
        )
    )

    for resource in resources:

        rule_name = resource.get(
            "resource_id"
        )

        result = {
            "resource_id": rule_name,
            "role": resource.get("role"),
            "service": "eventbridge"
        }

        try:

            response = (
                events_client
                .describe_rule(
                    Name=rule_name
                )
            )

            event_bus = response.get(
                "EventBusName",
                "default"
            )

            result.update({
                "status": "found",
                "state": response.get(
                    "State"
                ),
                "event_bus": event_bus,
                "event_pattern": response.get(
                    "EventPattern"
                ),
                "schedule_expression": (
                    response.get(
                        "ScheduleExpression"
                    )
                )
            })

        except ClientError as error:

            error_code = (
                error.response
                .get("Error", {})
                .get("Code")
            )

            result.update({
                "status": "error",
                "error_code": error_code,
                "error": str(error)
            })

            evidence.append(
                result
            )

            continue

        except Exception as error:

            result.update({
                "status": "error",
                "error": str(error)
            })

            evidence.append(
                result
            )

            continue

        try:

            response = (
                events_client
                .list_targets_by_rule(
                    Rule=rule_name,
                    EventBusName=event_bus
                )
            )

            targets = []

            for target in response.get(
                "Targets",
                []
            ):

                targets.append({
                    "id": target.get(
                        "Id"
                    ),
                    "arn": target.get(
                        "Arn"
                    )
                })

            result[
                "targets"
            ] = targets

            result[
                "target_count"
            ] = len(targets)

        except Exception as error:

            result[
                "target_error"
            ] = str(error)

        # CloudWatch EventBridge delivery/matching metrics.
        metrics = {}

        for metric_name in (
            "MatchedEvents",
            "TriggeredRules",
            "Invocations",
            "FailedInvocations"
        ):

            try:

                metrics[
                    metric_name
                ] = get_eventbridge_metric(
                    rule_name,
                    event_bus,
                    metric_name,
                    start_time,
                    end_time
                )

            except ClientError as error:

                error_code = (
                    error.response
                    .get("Error", {})
                    .get("Code")
                )

                metrics[
                    metric_name
                ] = {
                    "status": "error",
                    "error_code": error_code,
                    "error": str(error)
                }

            except Exception as error:

                metrics[
                    metric_name
                ] = {
                    "status": "error",
                    "error": str(error)
                }

        result[
            "metrics"
        ] = {
            "namespace": "AWS/Events",
            "lookback_minutes": LOOKBACK_MINUTES,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "metrics": metrics
        }

        # Validate the pattern without publishing an event.
        result[
            "pattern_validation"
        ] = validate_eventbridge_pattern(
            result.get(
                "event_pattern"
            )
        )

        evidence.append(
            result
        )

    return evidence


def build_findings(
    s3_evidence,
    dynamodb_evidence,
    eventbridge_evidence
):
    """
    Convert raw specialist evidence into
    normalized factual findings.

    The Storage Agent reports observations.
    It does not determine root cause.
    """

    findings = []

    for item in s3_evidence:

        resource_id = item.get(
            "resource_id"
        )

        if item.get(
            "status"
        ) == "accessible":

            findings.append({
                "finding_id": (
                    f"s3-{resource_id}-accessible"
                ),
                "severity": "info",
                "resource_id": resource_id,
                "service": "s3",
                "category": (
                    "bucket_accessibility"
                ),
                "summary": (
                    "S3 bucket is accessible"
                ),
                "evidence_ref": (
                    "evidence.s3"
                )
            })

        else:

            findings.append({
                "finding_id": (
                    f"s3-{resource_id}-error"
                ),
                "severity": "error",
                "resource_id": resource_id,
                "service": "s3",
                "category": (
                    "bucket_accessibility"
                ),
                "summary": (
                    "S3 bucket access "
                    "returned an error"
                ),
                "evidence_ref": (
                    "evidence.s3"
                )
            })

    for item in dynamodb_evidence:

        resource_id = item.get(
            "resource_id"
        )

        table_status = item.get(
            "table_status"
        )

        if table_status == "ACTIVE":

            findings.append({
                "finding_id": (
                    f"dynamodb-{resource_id}-active"
                ),
                "severity": "info",
                "resource_id": resource_id,
                "service": "dynamodb",
                "category": "table_status",
                "summary": (
                    "DynamoDB table status "
                    "is ACTIVE"
                ),
                "evidence_ref": (
                    "evidence.dynamodb"
                )
            })

        else:

            findings.append({
                "finding_id": (
                    f"dynamodb-{resource_id}-status"
                ),
                "severity": "warning",
                "resource_id": resource_id,
                "service": "dynamodb",
                "category": "table_status",
                "summary": (
                    "DynamoDB table is not "
                    "reported as ACTIVE"
                ),
                "evidence_ref": (
                    "evidence.dynamodb"
                )
            })

    for item in eventbridge_evidence:

        resource_id = item.get(
            "resource_id"
        )

        state = item.get(
            "state"
        )

        if state == "ENABLED":

            findings.append({
                "finding_id": (
                    f"eventbridge-{resource_id}-enabled"
                ),
                "severity": "info",
                "resource_id": resource_id,
                "service": "eventbridge",
                "category": "rule_state",
                "summary": (
                    "EventBridge rule is ENABLED"
                ),
                "evidence_ref": (
                    "evidence.eventbridge"
                )
            })

        else:

            findings.append({
                "finding_id": (
                    f"eventbridge-{resource_id}-state"
                ),
                "severity": "warning",
                "resource_id": resource_id,
                "service": "eventbridge",
                "category": "rule_state",
                "summary": (
                    "EventBridge rule is not ENABLED"
                ),
                "evidence_ref": (
                    "evidence.eventbridge"
                )
            })

        metrics = (
            item.get(
                "metrics",
                {}
            )
            .get(
                "metrics",
                {}
            )
        )

        metric_definitions = [
            (
                "MatchedEvents",
                "event_matching",
                "EventBridge reported matched events"
            ),
            (
                "TriggeredRules",
                "rule_triggering",
                "EventBridge reported triggered rules"
            ),
            (
                "Invocations",
                "target_invocations",
                "EventBridge reported target invocations"
            ),
            (
                "FailedInvocations",
                "failed_invocations",
                "EventBridge reported failed target invocations"
            )
        ]

        for (
            metric_name,
            category,
            summary_prefix
        ) in metric_definitions:

            metric = metrics.get(
                metric_name,
                {}
            )

            status = metric.get(
                "status"
            )

            if status == "available":

                value = metric.get(
                    "value"
                )

                severity = "warning"

                if metric_name == "FailedInvocations":
                    severity = (
                        "error"
                        if value and value > 0
                        else "info"
                    )
                else:
                    severity = "info"

                findings.append({
                    "finding_id": (
                        f"eventbridge-{resource_id}-"
                        f"{metric_name.lower()}"
                    ),
                    "severity": severity,
                    "resource_id": resource_id,
                    "service": "eventbridge",
                    "category": category,
                    "summary": (
                        f"{summary_prefix}: "
                        f"{value}"
                    ),
                    "evidence_ref": (
                        "evidence.eventbridge"
                    )
                })

            elif status == "no_data":

                findings.append({
                    "finding_id": (
                        f"eventbridge-{resource_id}-"
                        f"{metric_name.lower()}-no-data"
                    ),
                    "severity": "info",
                    "resource_id": resource_id,
                    "service": "eventbridge",
                    "category": (
                        f"{category}_telemetry"
                    ),
                    "summary": (
                        "No CloudWatch datapoints "
                        f"were returned for {metric_name}; "
                        "activity cannot be inferred"
                    ),
                    "evidence_ref": (
                        "evidence.eventbridge"
                    )
                })

            elif status == "error":

                findings.append({
                    "finding_id": (
                        f"eventbridge-{resource_id}-"
                        f"{metric_name.lower()}-error"
                    ),
                    "severity": "warning",
                    "resource_id": resource_id,
                    "service": "eventbridge",
                    "category": (
                        f"{category}_telemetry"
                    ),
                    "summary": (
                        f"Unable to collect "
                        f"{metric_name} telemetry"
                    ),
                    "evidence_ref": (
                        "evidence.eventbridge"
                    )
                })

        pattern_validation = item.get(
            "pattern_validation",
            {}
        )

        if pattern_validation.get(
            "status"
        ) == "validated":

            matched = pattern_validation.get(
                "matched"
            )

            findings.append({
                "finding_id": (
                    f"eventbridge-{resource_id}-"
                    "pattern-validation"
                ),
                "severity": "info",
                "resource_id": resource_id,
                "service": "eventbridge",
                "category": "pattern_validation",
                "summary": (
                    "Registered EventBridge event "
                    "pattern was successfully evaluated "
                    f"against the representative S3 event "
                    f"(matched={matched})"
                ),
                "evidence_ref": (
                    "evidence.eventbridge"
                )
            )

        elif pattern_validation.get(
            "status"
        ) == "error":

            findings.append({
                "finding_id": (
                    f"eventbridge-{resource_id}-"
                    "pattern-validation-error"
                ),
                "severity": "warning",
                "resource_id": resource_id,
                "service": "eventbridge",
                "category": "pattern_validation",
                "summary": (
                    "EventBridge event pattern "
                    "validation returned an error"
                ),
                "evidence_ref": (
                    "evidence.eventbridge"
                )
            })

    return findings


def lambda_handler(
    event,
    context
):
    """
    Storage/Service Specialist Agent.

    Supported operations:

        investigate_s3
        investigate_dynamodb
        investigate_eventbridge
        investigate_all

    All successful investigations return the
    Common Evidence Contract.
    """

    request_id = context.aws_request_id

    operation = event.get(
        "operation"
    )

    application_id = event.get(
        "application_id",
        APPLICATION_ID
    )

    logger.info(
        json.dumps({
            "event": (
                "storage_agent_request_received"
            ),
            "application_id": application_id,
            "operation": operation,
            "request_id": request_id
        })
    )

    if application_id != APPLICATION_ID:

        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unknown application",
                "application_id": application_id,
                "request_id": request_id
            })
        }

    if operation not in SUPPORTED_OPERATIONS:

        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "Unsupported operation",
                "supported_operations": (
                    SUPPORTED_OPERATIONS
                ),
                "request_id": request_id
            })
        }

    try:

        registry = get_application_registry(
            application_id
        )

    except Exception as error:

        logger.exception(
            "Failed to retrieve application registry"
        )

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": (
                    "Failed to retrieve "
                    "application registry"
                ),
                "details": str(error),
                "request_id": request_id
            })
        }

    s3_resources = get_resources_by_service(
        registry,
        "s3"
    )

    dynamodb_resources = get_resources_by_service(
        registry,
        "dynamodb"
    )

    eventbridge_resources = (
        get_resources_by_service(
            registry,
            "eventbridge"
        )
    )

    collected_at = utc_timestamp()

    raw_evidence = {
        "s3": [],
        "dynamodb": [],
        "eventbridge": []
    }

    if operation in (
        "investigate_s3",
        "investigate_all"
    ):

        raw_evidence[
            "s3"
        ] = investigate_s3(
            s3_resources
        )

    if operation in (
        "investigate_dynamodb",
        "investigate_all"
    ):

        raw_evidence[
            "dynamodb"
        ] = investigate_dynamodb(
            dynamodb_resources
        )

    if operation in (
        "investigate_eventbridge",
        "investigate_all"
    ):

        raw_evidence[
            "eventbridge"
        ] = investigate_eventbridge(
            eventbridge_resources
        )

    findings = build_findings(
        raw_evidence["s3"],
        raw_evidence["dynamodb"],
        raw_evidence["eventbridge"]
    )

    resources_discovered = (
        s3_resources
        + dynamodb_resources
        + eventbridge_resources
    )

    response_body = {
        "application_id": application_id,
        "agent": "storage-agent",
        "investigation_type": (
            "storage_investigation"
        ),
        "collected_at": collected_at,
        "resources_discovered": (
            resources_discovered
        ),
        "findings": findings,
        "evidence": raw_evidence
    }

    logger.info(
        json.dumps({
            "event": (
                "storage_investigation_completed"
            ),
            "application_id": application_id,
            "operation": operation,
            "finding_count": len(
                findings
            ),
            "resource_count": len(
                resources_discovered
            ),
            "request_id": request_id
        })
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            response_body,
            default=str
        )
    }
