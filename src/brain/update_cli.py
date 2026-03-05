"""cogent brain update — update subcommands for individual components."""

from __future__ import annotations

import sys

import click

from brain.cli import DefaultCommandGroup, get_cogent_name


class UpdateGroup(DefaultCommandGroup):
    """Update group that defaults to 'all'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, default_cmd="all", **kwargs)


@click.group(cls=UpdateGroup)
def update():
    """Update components of a running cogent.

    \b
    Default (no subcommand): update Lambda code + RDS migrations.
    """
    pass


def _get_aws(profile: str):
    """Lazy import AwsContext — fails clearly if body.aws not yet ported."""
    from body.aws import AwsContext

    return AwsContext(profile=profile)


@update.command("all")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_all(ctx: click.Context, profile: str):
    """Update Lambda + DB migrations (default)."""
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_rds, profile=profile, force=False)


@update.command("lambda")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_lambda(ctx: click.Context, profile: str):
    """Update Lambda function code."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating cogent-{name} Lambda functions...")

    from cli.create import _package_and_upload_lambdas

    s3_bucket, s3_key = _package_and_upload_lambdas(session, aws.region)

    lambda_client = session.client("lambda", region_name=aws.region)

    lambda_functions = [
        f"cogent-{safe_name}-orchestrator",
        f"cogent-{safe_name}-reconciler",
        f"cogent-{safe_name}-github-ingestion",
        f"cogent-{safe_name}-api",
        f"cogent-{safe_name}-api-beta",
    ]

    for fn_name in lambda_functions:
        try:
            lambda_client.update_function_code(
                FunctionName=fn_name,
                S3Bucket=s3_bucket,
                S3Key=s3_key,
            )
            click.echo(f"  {fn_name}: {click.style('updated', fg='green')}")
        except lambda_client.exceptions.ResourceNotFoundException:
            click.echo(f"  {fn_name}: {click.style('not found', fg='red')}")
        except Exception as e:
            click.echo(f"  {fn_name}: {click.style(str(e), fg='red')}")

    executor_name = f"cogent-{safe_name}-executor"
    try:
        fn_config = lambda_client.get_function(FunctionName=executor_name)
        image_uri = fn_config["Code"].get("ImageUri", "")
        if image_uri:
            lambda_client.update_function_code(
                FunctionName=executor_name,
                ImageUri=image_uri,
            )
            click.echo(f"  {executor_name}: {click.style('updated (image)', fg='green')}")
        else:
            lambda_client.update_function_code(
                FunctionName=executor_name,
                S3Bucket=s3_bucket,
                S3Key=s3_key,
            )
            click.echo(f"  {executor_name}: {click.style('updated', fg='green')}")
    except lambda_client.exceptions.ResourceNotFoundException:
        click.echo(f"  {executor_name}: {click.style('not found', fg='red')}")
    except Exception as e:
        click.echo(f"  {executor_name}: {click.style(str(e), fg='red')}")

    click.echo(f"  Lambda update for cogent-{name} completed.")


@update.command("ecs")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_ecs(ctx: click.Context, profile: str, skip_health: bool):
    """Force new ECS deployment (new container)."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    ecs_info = aws.get_ecs_info(session, name)
    cluster = ecs_info["cluster_arn"]
    service = ecs_info["service_name"]

    if not cluster or not service:
        click.echo(f"  No ECS service found for cogent-{name}.")
        click.echo("  This cogent may be in serverless mode. Use 'update lambda' instead.")
        return

    click.echo(f"Forcing new ECS deployment for cogent-{name}...")
    click.echo(f"  Cluster: {cluster}")
    click.echo(f"  Service: {service}")

    aws.force_new_deployment(session, cluster, service)

    if not skip_health:
        click.echo("  Waiting for service to stabilize...")
        try:
            aws.wait_for_stable(session, cluster, service)
            click.echo(f"  ECS deployment for cogent-{name} completed.")
        except Exception as e:
            click.echo(f"  Service did not stabilize: {e}", err=True)
            sys.exit(1)
    else:
        click.echo(f"  ECS deployment for cogent-{name} initiated.")


@update.command("rds")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--force", is_flag=True, help="Force re-run migrations")
@click.pass_context
def update_rds(ctx: click.Context, profile: str, force: bool):
    """Run database schema migrations via Data API."""
    name = get_cogent_name(ctx)
    click.echo(f"Running migrations for cogent-{name} via Data API...")
    # For now, placeholder — needs Data API version of apply_schema
    click.echo("  Data API migrations not yet implemented.")
    click.echo("  Use: python -c 'from brain.db.migrations import apply_schema; ...'")


@update.command("stack")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_stack(ctx: click.Context, profile: str):
    """Full CDK stack update."""
    import subprocess

    name = get_cogent_name(ctx)
    safe_name = name.replace(".", "-")
    click.echo(f"Updating CDK stack for cogent-{name}...")
    cmd = [
        "cdk",
        "deploy",
        f"cogent-{safe_name}-brain",
        "-c",
        f"cogent_name={name}",
        "--app",
        "python -m brain.cdk.app",
        "--require-approval",
        "never",
    ]
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        raise click.ClickException("CDK deploy failed")
    click.echo(f"Stack update for cogent-{name} completed.")
