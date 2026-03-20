"""CDK stack to create an AWS Organizations account for a cogtainer.

Deployed to the management account. Uses a Lambda-backed custom resource
to call Organizations CreateAccount and poll until completion.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import CfnOutput, CustomResource, Duration
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import custom_resources as cr
from constructs import Construct

HANDLER_CODE = """\
import boto3
import os
import time
import random
import string

ORG_EMAIL_DOMAIN = os.environ["ORG_EMAIL_DOMAIN"]

def handler(event, context):
    props = event["ResourceProperties"]
    account_name = props["AccountName"]

    if event["RequestType"] == "Delete":
        return {"PhysicalResourceId": event.get("PhysicalResourceId", "none")}

    org = boto3.client("organizations")

    # Check for existing account
    paginator = org.get_paginator("list_accounts")
    for page in paginator.paginate():
        for acct in page["Accounts"]:
            if acct["Name"] == account_name and acct["Status"] == "ACTIVE":
                return {
                    "PhysicalResourceId": acct["Id"],
                    "Data": {"AccountId": acct["Id"]},
                }

    # Create new account
    tag = "".join(random.choices(string.hexdigits[:16], k=6))
    email = f"{account_name}+{tag}@{ORG_EMAIL_DOMAIN}"

    resp = org.create_account(Email=email, AccountName=account_name)
    request_id = resp["CreateAccountStatus"]["Id"]

    while True:
        status = org.describe_create_account_status(
            CreateAccountRequestId=request_id,
        )["CreateAccountStatus"]
        state = status["State"]
        if state == "SUCCEEDED":
            account_id = status["AccountId"]
            return {
                "PhysicalResourceId": account_id,
                "Data": {"AccountId": account_id},
            }
        if state == "FAILED":
            reason = status.get("FailureReason", "unknown")
            if reason == "EMAIL_ALREADY_EXISTS":
                tag = "".join(random.choices(string.hexdigits[:16], k=6))
                email = f"{account_name}+{tag}@{ORG_EMAIL_DOMAIN}"
                resp = org.create_account(Email=email, AccountName=account_name)
                request_id = resp["CreateAccountStatus"]["Id"]
                continue
            raise RuntimeError(f"Account creation failed: {reason}")
        time.sleep(5)
"""


class AccountStack(cdk.Stack):
    """Creates an AWS Organizations account for a cogtainer."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cogtainer_name: str,
        email_domain: str = "softmax.com",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account_name = f"cogtainer-{cogtainer_name}"

        handler = _lambda.Function(
            self,
            "AccountCreator",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.Code.from_inline(HANDLER_CODE),
            timeout=Duration.minutes(10),
            environment={"ORG_EMAIL_DOMAIN": email_domain},
        )

        handler.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "organizations:CreateAccount",
                    "organizations:DescribeCreateAccountStatus",
                    "organizations:ListAccounts",
                ],
                resources=["*"],
            )
        )

        provider = cr.Provider(self, "Provider", on_event_handler=handler)

        account_resource = CustomResource(
            self,
            "Account",
            service_token=provider.service_token,
            properties={"AccountName": account_name},
        )

        self.account_id = account_resource.get_att_string("AccountId")

        CfnOutput(self, "AccountId", value=self.account_id)
        CfnOutput(self, "AccountName", value=account_name)
