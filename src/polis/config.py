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
