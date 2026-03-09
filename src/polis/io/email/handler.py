"""Email ingest Lambda — receives parsed emails from Cloudflare Email Worker.

Deployed once in polis. Resolves the target cogent's DB from CloudFormation
stack outputs, then inserts the event via RDS Data API.
"""

import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

INGEST_SECRET = os.environ.get("EMAIL_INGEST_SECRET", "")

_cfn = boto3.client("cloudformation")
_rds = boto3.client("rds-data")

# Cache: cogent_name -> (cluster_arn, secret_arn, db_name)
_db_cache: dict[str, tuple[str, str, str]] = {}


def _resolve_db(cogent_name: str) -> tuple[str, str, str]:
    """Resolve a cogent's DB connection from its CloudFormation stack outputs."""
    if cogent_name in _db_cache:
        return _db_cache[cogent_name]

    stack_name = f"cogent-{cogent_name}"
    resp = _cfn.describe_stacks(StackName=stack_name)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}

    cluster_arn = outputs["ClusterArn"]
    secret_arn = outputs["SecretArn"]
    db_name = "cogent"

    _db_cache[cogent_name] = (cluster_arn, secret_arn, db_name)
    return cluster_arn, secret_arn, db_name


def _insert_event(cogent_name: str, event_type: str, source: str, payload: dict) -> str:
    """Insert an event into the cogent's cogos_event table via Data API."""
    cluster_arn, secret_arn, db_name = _resolve_db(cogent_name)
    event_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    _rds.execute_statement(
        resourceArn=cluster_arn,
        secretArn=secret_arn,
        database=db_name,
        sql="""
            INSERT INTO cogos_event (id, event_type, source, payload, status, created_at)
            VALUES (:id, :event_type, :source, :payload::jsonb, 'proposed', :created_at)
        """,
        parameters=[
            {"name": "id", "value": {"stringValue": event_id}},
            {"name": "event_type", "value": {"stringValue": event_type}},
            {"name": "source", "value": {"stringValue": source}},
            {"name": "payload", "value": {"stringValue": json.dumps(payload)}},
            {"name": "created_at", "value": {"stringValue": now}},
        ],
    )
    return event_id


def handler(event, context):
    """Lambda handler — expects API Gateway / Function URL proxy event."""
    # Extract bearer token
    headers = event.get("headers", {})
    auth = headers.get("authorization", headers.get("Authorization", ""))
    token = auth.removeprefix("Bearer ").strip()

    if not INGEST_SECRET or not hmac.compare_digest(token, INGEST_SECRET):
        return {"statusCode": 401, "body": json.dumps({"detail": "Invalid ingest token"})}

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"detail": "Invalid JSON"})}

    payload = body.get("payload", {})
    cogent_name = payload.get("cogent")
    if not cogent_name:
        return {"statusCode": 400, "body": json.dumps({"detail": "Missing cogent in payload"})}

    event_type = body.get("event_type", "email:received")
    source = body.get("source", "cloudflare-email-worker")

    try:
        event_id = _insert_event(cogent_name, event_type, source, payload)
    except Exception:
        logger.exception("Failed to insert event for cogent=%s", cogent_name)
        return {"statusCode": 500, "body": json.dumps({"detail": "Failed to insert event"})}

    logger.info(
        "Ingested email event %s cogent=%s from=%s subject=%s",
        event_id, cogent_name, payload.get("from"), payload.get("subject"),
    )
    return {"statusCode": 200, "body": json.dumps({"event_id": event_id})}
