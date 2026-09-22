import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3


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


SUPPORTED_OPERATIONS = [
    "investigate_logs",
    "get_alarms",
    "get_metrics"
]


lambda_client = boto3.client("lambda")
logs_client = boto3.client("logs")
cloudwatch_client = boto3.client("cloudwatch")


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def get_application_registry(application_id):
    response = lambda_client.invoke(
        FunctionName=REGISTRY_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "operation": "get_application",
            "application_id": application_id
        }).encode("utf-8")
    )

    payload = response["Payload"].read()
    registry_response = json.loads(payload.decode("utf-8"))

    status_code = registry_response.get("statusCode")

    if status_code != 200:
        raise RuntimeError(
            "Registry API returned status "
            f"{status_code}: "
            f"{registry_response.get('body')}"
        )

    body = registry_response.get("body", "{}")
    return json.loads(body)


def get_lambda_resources(registry):
    resources = registry.get("resources", [])
    return [
        resource
        for resource in resources
        if resource.get("service") == "lambda"
    ]


def get_recent_logs(log_group_name, minutes=15, limit=50):
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=minutes)

    events = []
    next_token = None

    while True:
        request = {
            "logGroupName": log_group_name,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": 10000
        }

        if next_token:
            request["nextToken"] = next_token

        response = logs_client.filter_log_events(**request)

        for event in response.get("events", []):
            events.append({
                "timestamp": event.get("timestamp"),
                "message": event.get("message"),
                "log_stream": event.get("logStreamName")
            })

        new_next_token = response.get("nextToken")

        if not new_next_token or new_next_token == next_token:
            break

        next_token = new_next_token

    events.sort(key=lambda event: event.get("timestamp", 0))
    return events[-limit:]


def get_application_alarms(lambda_resources):
    response = cloudwatch_client.describe_alarms()

    lambda_names = {
        resource.get("resource_id")
        for resource in lambda_resources
        if resource.get("resource_id")
    }

    alarms = []

    for alarm in response.get("MetricAlarms", []):
        dimensions = alarm.get("Dimensions", [])

        belongs_to_application = any(
            dimension.get("Name") == "FunctionName"
            and dimension.get("Value") in lambda_names
            for dimension in dimensions
        )

        if not belongs_to_application:
            continue

        alarms.append({
            "alarm_name": alarm.get("AlarmName"),
            "state": alarm.get("StateValue"),
            "state_reason": alarm.get("StateReason"),
            "metric_name": alarm.get("MetricName"),
            "namespace": alarm.get("Namespace"),
            "dimensions": dimensions,
            "threshold": alarm.get("Threshold"),
            "comparison_operator": alarm.get("ComparisonOperator"),
            "evaluation_periods": alarm.get("EvaluationPeriods"),
            "period": alarm.get("Period")
        })

    return alarms


def get_lambda_metrics(function_name, minutes=15):
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=minutes)

    metrics = {}

    metric_definitions = {
        "Invocations": "Sum",
        "Errors": "Sum",
        "Throttles": "Sum",
        "Duration": "Average"
    }

    for metric_name, statistic in metric_definitions.items():
        try:
            response = cloudwatch_client.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName=metric_name,
                Dimensions=[{
                    "Name": "FunctionName",
                    "Value": function_name
                }],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=[statistic]
            )

            datapoints = response.get("Datapoints", [])
            values = [
                datapoint.get(statistic)
                for datapoint in datapoints
                if datapoint.get(statistic) is not None
            ]

            if not values:
                metrics[metric_name] = {
                    "status": "no_data",
                    "statistic": statistic,
                    "value": None,
                    "datapoints": 0
                }
                continue

            if statistic == "Sum":
                value = sum(values)
            else:
                value = sum(values) / len(values)

            metrics[metric_name] = {
                "status": "available",
                "statistic": statistic,
                "value": value,
                "datapoints": len(values)
            }

        except Exception as error:
            logger.exception("Failed to retrieve Lambda metric")
            metrics[metric_name] = {
                "status": "error",
                "statistic": statistic,
                "value": None,
                "datapoints": 0,
                "error": str(error)
            }

    return metrics


def build_log_findings(log_groups):
    findings = []

    for function_name, result in log_groups.items():
        events = result.get("events", [])
        event_count = result.get("event_count", 0)

        if result.get("error"):
            findings.append({
                "finding_id": f"logs-{function_name}-error",
                "severity": "error",
                "resource_id": function_name,
                "service": "lambda",
                "category": "log_collection",
                "summary": "CloudWatch logs could not be collected",
                "evidence_ref": "evidence.log_groups"
            })
            continue

        findings.append({
            "finding_id": f"logs-{function_name}-events",
            "severity": "info",
            "resource_id": function_name,
            "service": "lambda",
            "category": "log_activity",
            "summary": f"{event_count} CloudWatch log events collected",
            "evidence_ref": "evidence.log_groups"
        })

        error_events = []

        for event in events:
            message = event.get("message", "")

            if (
                "ERROR" in message
                or "Error" in message
                or "Exception" in message
                or "Traceback" in message
            ):
                error_events.append(event)

        if error_events:
            findings.append({
                "finding_id": f"logs-{function_name}-errors",
                "severity": "error",
                "resource_id": function_name,
                "service": "lambda",
                "category": "application_errors",
                "summary": (
                    f"{len(error_events)} error-like log events were observed"
                ),
                "evidence_ref": "evidence.log_groups"
            })

    return findings


def build_alarm_findings(alarms):
    findings = []

    for alarm in alarms:
        alarm_name = alarm.get("alarm_name")
        state = alarm.get("state")

        resource_id = None

        for dimension in alarm.get("dimensions", []):
            if dimension.get("Name") == "FunctionName":
                resource_id = dimension.get("Value")

        if state == "ALARM":
            severity = "critical"
            summary = "CloudWatch alarm is in ALARM state"
        elif state == "INSUFFICIENT_DATA":
            severity = "warning"
            summary = "CloudWatch alarm has insufficient data"
        else:
            severity = "info"
            summary = "CloudWatch alarm is in OK state"

        findings.append({
            "finding_id": f"alarm-{alarm_name}",
            "severity": severity,
            "resource_id": resource_id,
            "service": "cloudwatch",
            "category": "alarm_state",
            "summary": summary,
            "evidence_ref": "evidence.alarms"
        })

    return findings


def build_metric_findings(functions):
    findings = []

    for function_name, function_data in functions.items():
        metrics = function_data.get("metrics", {})
        errors = metrics.get("Errors", {})
        throttles = metrics.get("Throttles", {})
        invocations = metrics.get("Invocations", {})

        error_status = errors.get("status")
        error_value = errors.get("value")

        if error_status == "available":
            if error_value is not None and error_value > 0:
                findings.append({
                    "finding_id": f"metrics-{function_name}-errors",
                    "severity": "error",
                    "resource_id": function_name,
                    "service": "lambda",
                    "category": "lambda_errors",
                    "summary": f"Lambda reported {error_value} errors",
                    "evidence_ref": "evidence.functions"
                })
            else:
                findings.append({
                    "finding_id": f"metrics-{function_name}-no-errors",
                    "severity": "info",
                    "resource_id": function_name,
                    "service": "lambda",
                    "category": "lambda_errors",
                    "summary": "Lambda reported 0 errors in the collected period",
                    "evidence_ref": "evidence.functions"
                })

        elif error_status == "no_data":
            findings.append({
                "finding_id": f"metrics-{function_name}-errors-no-data",
                "severity": "info",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_errors_telemetry",
                "summary": (
                    "No CloudWatch datapoints were returned for Lambda Errors; "
                    "error activity cannot be inferred"
                ),
                "evidence_ref": "evidence.functions"
            })

        elif error_status == "error":
            findings.append({
                "finding_id": f"metrics-{function_name}-errors-collection-error",
                "severity": "warning",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_errors_telemetry",
                "summary": "Lambda Errors telemetry could not be collected",
                "evidence_ref": "evidence.functions"
            })

        throttle_status = throttles.get("status")
        throttle_value = throttles.get("value")

        if throttle_status == "available":
            if throttle_value is not None and throttle_value > 0:
                findings.append({
                    "finding_id": f"metrics-{function_name}-throttles",
                    "severity": "warning",
                    "resource_id": function_name,
                    "service": "lambda",
                    "category": "lambda_throttles",
                    "summary": f"Lambda reported {throttle_value} throttles",
                    "evidence_ref": "evidence.functions"
                })
            else:
                findings.append({
                    "finding_id": f"metrics-{function_name}-no-throttles",
                    "severity": "info",
                    "resource_id": function_name,
                    "service": "lambda",
                    "category": "lambda_throttles",
                    "summary": "Lambda reported 0 throttles in the collected period",
                    "evidence_ref": "evidence.functions"
                })

        elif throttle_status == "no_data":
            findings.append({
                "finding_id": f"metrics-{function_name}-throttles-no-data",
                "severity": "info",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_throttles_telemetry",
                "summary": (
                    "No CloudWatch datapoints were returned for Lambda Throttles; "
                    "throttle activity cannot be inferred"
                ),
                "evidence_ref": "evidence.functions"
            })

        elif throttle_status == "error":
            findings.append({
                "finding_id": f"metrics-{function_name}-throttles-collection-error",
                "severity": "warning",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_throttles_telemetry",
                "summary": "Lambda Throttles telemetry could not be collected",
                "evidence_ref": "evidence.functions"
            })

        invocation_status = invocations.get("status")
        invocation_value = invocations.get("value")

        if invocation_status == "available":
            findings.append({
                "finding_id": f"metrics-{function_name}-invocations",
                "severity": "info",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_invocations",
                "summary": f"Lambda reported {invocation_value} invocations",
                "evidence_ref": "evidence.functions"
            })

        elif invocation_status == "no_data":
            findings.append({
                "finding_id": f"metrics-{function_name}-invocations-no-data",
                "severity": "info",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_invocations_telemetry",
                "summary": (
                    "No CloudWatch datapoints were returned for Lambda Invocations; "
                    "invocation activity cannot be inferred"
                ),
                "evidence_ref": "evidence.functions"
            })

        elif invocation_status == "error":
            findings.append({
                "finding_id": f"metrics-{function_name}-invocations-collection-error",
                "severity": "warning",
                "resource_id": function_name,
                "service": "lambda",
                "category": "lambda_invocations_telemetry",
                "summary": "Lambda Invocations telemetry could not be collected",
                "evidence_ref": "evidence.functions"
            })

    return findings


def lambda_handler(event, context):
    request_id = context.aws_request_id

    operation = event.get("operation")
    application_id = event.get("application_id", APPLICATION_ID)

    logger.info(json.dumps({
        "event": "observability_request_received",
        "request_id": request_id,
        "application_id": application_id,
        "operation": operation
    }))

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
                "supported_operations": SUPPORTED_OPERATIONS,
                "request_id": request_id
            })
        }

    try:
        registry = get_application_registry(application_id)
    except Exception as error:
        logger.exception("Failed to retrieve application registry")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to retrieve application registry",
                "details": str(error),
                "request_id": request_id
            })
        }

    lambda_resources = get_lambda_resources(registry)
    collected_at = utc_timestamp()
    findings = []
    evidence = {}

    if operation == "investigate_logs":
        minutes = event.get("minutes", 15)
        log_groups = {}

        for resource in lambda_resources:
            function_name = resource.get("resource_id")

            if not function_name:
                continue

            log_group = f"/aws/lambda/{function_name}"

            try:
                events = get_recent_logs(log_group, minutes)
                log_groups[function_name] = {
                    "log_group": log_group,
                    "event_count": len(events),
                    "events": events
                }
            except logs_client.exceptions.ResourceNotFoundException:
                log_groups[function_name] = {
                    "log_group": log_group,
                    "event_count": 0,
                    "events": [],
                    "error": "Log group not found"
                }
            except Exception as error:
                logger.exception("Failed to read logs")
                log_groups[function_name] = {
                    "log_group": log_group,
                    "event_count": 0,
                    "events": [],
                    "error": str(error)
                }

        evidence = {
            "log_groups": log_groups,
            "lookback_minutes": minutes
        }

        findings = build_log_findings(log_groups)

    elif operation == "get_alarms":
        try:
            alarms = get_application_alarms(lambda_resources)

            summary = {
                "total": len(alarms),
                "in_alarm": sum(
                    1 for alarm in alarms
                    if alarm.get("state") == "ALARM"
                ),
                "ok": sum(
                    1 for alarm in alarms
                    if alarm.get("state") == "OK"
                ),
                "insufficient_data": sum(
                    1 for alarm in alarms
                    if alarm.get("state") == "INSUFFICIENT_DATA"
                )
            }

            evidence = {
                "summary": summary,
                "alarms": alarms
            }

            findings = build_alarm_findings(alarms)

        except Exception as error:
            logger.exception("Failed to retrieve alarms")
            return {
                "statusCode": 500,
                "body": json.dumps({
                    "error": "Failed to retrieve CloudWatch alarms",
                    "details": str(error),
                    "request_id": request_id
                })
            }

    elif operation == "get_metrics":
        minutes = event.get("minutes", 15)
        functions = {}

        for resource in lambda_resources:
            function_name = resource.get("resource_id")

            if not function_name:
                continue

            functions[function_name] = {
                "function_name": function_name,
                "role": resource.get("role"),
                "metrics": get_lambda_metrics(function_name, minutes)
            }

        evidence = {
            "lookback_minutes": minutes,
            "functions": functions
        }

        findings = build_metric_findings(functions)

    response_body = {
        "application_id": application_id,
        "agent": "observability-agent",
        "investigation_type": operation,
        "collected_at": collected_at,
        "resources_discovered": lambda_resources,
        "findings": findings,
        "evidence": evidence
    }

    logger.info(json.dumps({
        "event": "observability_investigation_completed",
        "application_id": application_id,
        "operation": operation,
        "finding_count": len(findings),
        "resource_count": len(lambda_resources),
        "request_id": request_id
    }))

    return {
        "statusCode": 200,
        "body": json.dumps(response_body, default=str)
    }
