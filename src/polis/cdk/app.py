"""CDK app entry point for the polis stack.

Usage: npx cdk deploy --app "python -m polis.cdk.app" -c org_id=<org_id>
"""

from __future__ import annotations

import aws_cdk as cdk

from polis import naming
from polis.aws import DEFAULT_REGION, POLIS_ACCOUNT_ID
from polis.cdk.stacks.core import PolisStack
from polis.cdk.stacks.secrets import SecretsStack
from polis.config import PolisConfig, deploy_config

ORG_ID = deploy_config("org_id", "o-n7g18rzou1")


def build_app(config: PolisConfig | None = None, org_id: str = "") -> cdk.App:
    """Build the CDK app with the polis stacks."""
    config = config or PolisConfig()
    app = cdk.App()

    org_id = org_id or app.node.try_get_context("org_id") or ORG_ID
    env = cdk.Environment(account=POLIS_ACCOUNT_ID, region=DEFAULT_REGION)

    PolisStack(app, naming.polis_stack_name(), config=config, org_id=org_id, env=env)
    SecretsStack(app, naming.secrets_stack_name(), org_id=org_id, env=env)

    return app


if __name__ == "__main__":
    app = build_app()
    app.synth()
