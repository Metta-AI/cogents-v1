"""S3 storage for Claude Code sessions."""

from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk import aws_s3 as s3
from constructs import Construct

from cogtainer.cdk.config import CogtainerConfig
from polis import naming


class StorageConstruct(Construct):
    """S3 bucket for Claude Code sessions and program artifacts."""

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: CogtainerConfig,
    ) -> None:
        super().__init__(scope, id)

        self.bucket = s3.Bucket(
            self,
            "SessionsBucket",
            bucket_name=naming.bucket_name(config.cogent_name),
            removal_policy=RemovalPolicy.RETAIN,
            auto_delete_objects=False,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-sessions",
                    prefix="sessions/",
                    expiration=config.session_expiry_days,
                ),
            ],
        )
