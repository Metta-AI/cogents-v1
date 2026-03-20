"""CDK stack configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

from polis.aws import DEFAULT_REGION as POLIS_REGION
from polis.aws import POLIS_ACCOUNT_ID as POLIS_ACCOUNT
from polis.config import deploy_config


@dataclass
class CogtainerConfig:
    """Configuration for the Cogtainer CDK stack."""

    cogent_name: str
    domain: str = field(default_factory=lambda: deploy_config("domain", "softmax-cogents.com"))
    region: str = POLIS_REGION
    account: str = POLIS_ACCOUNT
    shared_db_cluster_arn: str = ""
    shared_db_secret_arn: str = ""
    executor_memory_mb: int = 2048
    executor_timeout_s: int = 900
    orchestrator_memory_mb: int = 512
    orchestrator_timeout_s: int = 60
    ecs_cpu: int = 2048
    ecs_memory: int = 4096
    ecs_timeout_s: int = 3600
    ecr_repo_uri: str = ""
    llm_provider: str = "bedrock"
