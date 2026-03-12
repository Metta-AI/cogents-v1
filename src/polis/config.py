"""Polis configuration: organization, domain, cogent roster."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CogentMeta(BaseModel):
    description: str = ""
    personality: str | None = None


class ServiceQuotaTarget(BaseModel):
    service_code: str = "bedrock"
    quota_code: str
    quota_name: str
    desired_value: float
    region: str = "us-east-1"


def _default_bedrock_quotas() -> list[ServiceQuotaTarget]:
    """Default Bedrock quota targets for the shared polis account."""
    return [
        ServiceQuotaTarget(
            quota_code="L-59759B4A",
            quota_name="Cross-region model inference tokens per minute for Anthropic Claude Sonnet 4 V1",
            desired_value=1_000_000,
        ),
        ServiceQuotaTarget(
            quota_code="L-559DCC33",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4 V1",
            desired_value=500,
        ),
        ServiceQuotaTarget(
            quota_code="L-CCA5DF70",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Haiku 4.5",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-27989F42",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.5",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-11DFF789",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.6 V1",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-410BCACA",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Opus 4.6 V1 1M Context Length",
            desired_value=1_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-4A6BFAB1",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-A052927A",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.5 V1 1M Context Length",
            desired_value=1_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-00FF3314",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.6",
            desired_value=10_001,
        ),
        ServiceQuotaTarget(
            quota_code="L-47DE5258",
            quota_name="Cross-region model inference requests per minute for Anthropic Claude Sonnet 4.6 1M Context Length",
            desired_value=1_001,
        ),
    ]


class PolisConfig(BaseModel):
    name: str = "softmax-polis"
    organization: str = "Softmax"
    owner: str = "daveey"
    domain: str = "softmax-cogents.com"
    cogents: dict[str, CogentMeta] = {}
    bedrock_quotas: list[ServiceQuotaTarget] = Field(default_factory=_default_bedrock_quotas)

    def template_vars(self, cogent_name: str) -> dict[str, str]:
        """Return template variables for a cogent."""
        cogent = self.cogents.get(cogent_name, CogentMeta())
        return {
            "cogent_name": cogent_name,
            "polis_name": self.name,
            "organization": self.organization,
            "owner": self.owner,
            "description": cogent.description,
            "personality": cogent.personality or "",
        }
