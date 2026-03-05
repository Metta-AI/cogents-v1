"""CDK app entry point for brain infrastructure."""

from __future__ import annotations

import aws_cdk as cdk

from brain.cdk.config import BrainConfig
from brain.cdk.stack import BrainStack


def main() -> None:
    app = cdk.App()
    cogent_name = app.node.try_get_context("cogent_name") or "default"
    region = app.node.try_get_context("region") or "us-east-1"

    config = BrainConfig(cogent_name=cogent_name, region=region)

    BrainStack(
        app,
        f"cogent-{cogent_name.replace('.', '-')}-brain",
        config=config,
        env=cdk.Environment(region=region),
    )

    app.synth()


if __name__ == "__main__":
    main()
