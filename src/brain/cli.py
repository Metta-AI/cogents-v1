"""cogent brain — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click

from cli import DefaultCommandGroup, get_cogent_name  # noqa: F401


CDK_PROFILE = "softmax-org"


@click.group(cls=DefaultCommandGroup, default_cmd="status")
def brain():
    """Manage cogent infrastructure, ECS, and Lambda components."""
    pass


@brain.command("status")
@click.pass_context
def status_cmd(ctx: click.Context):
    """Show infrastructure status for a cogent."""
    name = get_cogent_name(ctx)
    click.echo(f"Status for cogent-{name}: use 'polis status' for full status")


@brain.command("create")
@click.option("--profile", default=CDK_PROFILE, help="AWS profile for polis account")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def create_cmd(ctx: click.Context, profile: str, watch: bool):
    """Deploy a cogent's brain infrastructure in the polis account."""
    import os
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")

    # Look up certificate ARN from polis account
    from polis.aws import get_polis_session, set_profile
    set_profile(profile)
    polis_session, _ = get_polis_session()
    cert_arn = _find_certificate(polis_session, f"{safe_name}.softmax-cogents.com")

    click.echo(f"Deploying brain for cogent-{name} in polis account...")
    if cert_arn:
        click.echo(f"  Certificate: {cert_arn}")

    cmd = [
        "cdk", "deploy", f"cogent-{safe_name}-brain",
        "-c", f"cogent_name={name}",
        "-c", f"certificate_arn={cert_arn}",
        "--app", "python -m brain.cdk.app",
        "--require-approval", "never",
    ]
    if not watch:
        cmd.append("--no-rollback")

    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Brain infrastructure for cogent-{name} deployed in polis account.")

    # Re-assume role after CDK deploy (original session may have expired)
    polis_session, _ = get_polis_session()
    polis_creds = polis_session.get_credentials().get_frozen_credentials()
    cf = polis_session.client("cloudformation", region_name="us-east-1")
    try:
        resp = cf.describe_stacks(StackName=f"cogent-{safe_name}-brain")
        outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
        if "ClusterArn" in outputs:
            os.environ["DB_CLUSTER_ARN"] = outputs["ClusterArn"]
        if "SecretArn" in outputs:
            os.environ["DB_SECRET_ARN"] = outputs["SecretArn"]
        else:
            resources = cf.list_stack_resources(StackName=f"cogent-{safe_name}-brain")
            for r in resources.get("StackResourceSummaries", []):
                if "Secret" in r["LogicalResourceId"] and "Attachment" not in r["LogicalResourceId"]:
                    if r["PhysicalResourceId"].startswith("arn:aws:secretsmanager:"):
                        os.environ["DB_SECRET_ARN"] = r["PhysicalResourceId"]
                        break
        # Set AWS credentials so apply_schema() can access RDS Data API in polis account
        os.environ["AWS_ACCESS_KEY_ID"] = polis_creds.access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = polis_creds.secret_key
        if polis_creds.token:
            os.environ["AWS_SESSION_TOKEN"] = polis_creds.token
    except Exception as e:
        click.echo(f"Warning: could not read stack outputs: {e}")

    # Apply memory schema
    click.echo("Applying memory schema...")
    ctx.invoke(_memory_create)

    # Update Route53 DNS to point at the dashboard ALB
    # Use OrganizationAccountAccessRole which has full admin (cogent-polis-admin lacks ELB perms)
    if cert_arn:
        click.echo("Updating DNS...")
        try:
            from polis.aws import _assume_role, get_org_session, POLIS_ACCOUNT_ID
            dns_session = _assume_role(
                get_org_session(), POLIS_ACCOUNT_ID, "OrganizationAccountAccessRole",
            )
            _update_dashboard_dns(dns_session, safe_name, "softmax-cogents.com")
        except Exception as e:
            click.echo(f"Warning: DNS update failed: {e}")


HOSTED_ZONE_ID = "Z059653727QDSCT3DI6DS"


def _update_dashboard_dns(session, safe_name: str, domain: str):
    """Update Route53 A-record to alias the dashboard ALB."""
    cfn = session.client("cloudformation", region_name="us-east-1")
    resp = cfn.describe_stacks(StackName=f"cogent-{safe_name}-brain")
    outputs = {o["OutputKey"]: o["OutputValue"] for o in resp["Stacks"][0].get("Outputs", [])}
    alb_dns = outputs.get("AlbDns", "")
    if not alb_dns:
        click.echo("  No AlbDns output found, skipping DNS update")
        return

    elbv2_client = session.client("elbv2", region_name="us-east-1")
    lbs = elbv2_client.describe_load_balancers()["LoadBalancers"]
    alb_zone_id = ""
    for lb in lbs:
        if lb["DNSName"] == alb_dns:
            alb_zone_id = lb["CanonicalHostedZoneId"]
            break
    if not alb_zone_id:
        click.echo(f"  Could not find ALB zone ID for {alb_dns}")
        return

    r53 = session.client("route53")
    r53.change_resource_record_sets(
        HostedZoneId=HOSTED_ZONE_ID,
        ChangeBatch={
            "Comment": f"Dashboard ALB for {safe_name}",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": f"{safe_name}.{domain}",
                        "Type": "A",
                        "AliasTarget": {
                            "HostedZoneId": alb_zone_id,
                            "DNSName": f"dualstack.{alb_dns}",
                            "EvaluateTargetHealth": True,
                        },
                    },
                }
            ],
        },
    )
    click.echo(f"  DNS updated: {safe_name}.{domain} -> {alb_dns}")


def _find_certificate(session, domain: str) -> str:
    """Find an ACM certificate ARN for the given domain."""
    acm = session.client("acm")
    paginator = acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["ISSUED", "PENDING_VALIDATION"]):
        for cert in page["CertificateSummaryList"]:
            if cert["DomainName"] == domain:
                return cert["CertificateArn"]
    return ""


@brain.command("destroy")
@click.option("--profile", default=CDK_PROFILE, help="AWS profile for polis account")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def destroy_cmd(ctx: click.Context, profile: str, yes: bool):
    """Destroy a cogent's brain infrastructure."""
    import os
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    if not yes:
        click.confirm(f"This will destroy the stack for cogent-{name}. Continue?", abort=True)
    cmd = [
        "cdk", "destroy", f"cogent-{safe_name}-brain",
        "-c", f"cogent_name={name}",
        "--app", "python -m brain.cdk.app",
        "--force",
    ]
    env = {**os.environ, "AWS_PROFILE": profile}
    result = subprocess.run(cmd, capture_output=False, env=env)
    if result.returncode != 0:
        raise click.ClickException("CDK destroy failed")
    click.echo(f"Brain infrastructure for cogent-{name} destroyed.")


# Wire in update subcommands
from brain.update_cli import update  # noqa: E402

brain.add_command(update)

# Memory create command (invoked by brain create)
from memory.cli import create_cmd as _memory_create  # noqa: E402
