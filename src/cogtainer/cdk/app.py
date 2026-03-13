"""CDK app entry point for cogtainer infrastructure (deployed in polis account)."""

from __future__ import annotations

import aws_cdk as cdk

from cogtainer.cdk.config import CogtainerConfig, POLIS_ACCOUNT, POLIS_REGION
from cogtainer.cdk.stack import CogtainerStack


def main() -> None:
    app = cdk.App()
    cogent_name = app.node.try_get_context("cogent_name") or "default"
    certificate_arn = app.node.try_get_context("certificate_arn") or ""
    ecr_repo_uri = app.node.try_get_context("ecr_repo_uri") or ""

    config = CogtainerConfig(
        cogent_name=cogent_name,
        ecr_repo_uri=ecr_repo_uri,
    )

    CogtainerStack(
        app,
        f"cogent-{cogent_name.replace('.', '-')}-cogtainer",
        config=config,
        certificate_arn=certificate_arn,
        env=cdk.Environment(account=POLIS_ACCOUNT, region=POLIS_REGION),
    )

    app.synth()


if __name__ == "__main__":
    main()
