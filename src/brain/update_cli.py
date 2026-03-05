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
    Default (no subcommand): update Lambda code + Discord bridge service.
    """
    pass


def _get_aws(profile: str):
    """Lazy import AwsContext — fails clearly if body.aws not yet ported."""
    from body.aws import AwsContext

    return AwsContext(profile=profile)


@update.command("all")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for Discord bridge stability")
@click.pass_context
def update_all(ctx: click.Context, profile: str, skip_health: bool):
    """Update Lambda + Discord + DB migrations + mind content (default)."""
    ctx.invoke(update_lambda, profile=profile)
    ctx.invoke(update_discord, profile=profile, skip_health=skip_health)
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


@update.command("discord")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--skip-health", is_flag=True, help="Skip waiting for service stability")
@click.pass_context
def update_discord(ctx: click.Context, profile: str, skip_health: bool):
    """Update Discord bridge service (force new ECS deployment)."""
    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    click.echo(f"Updating Discord bridge for cogent-{name}...")
    outputs = aws.get_stack_outputs(session, name)
    cluster = outputs.get("ClusterArn", "")
    if not cluster:
        click.echo(f"  No ECS cluster found in stack outputs for cogent-{name}")
        return
    bridge_service = f"cogent-{safe_name}-discord-bridge"

    try:
        ecs = session.client("ecs", region_name=aws.region)
        ecs.update_service(
            cluster=cluster,
            service=bridge_service,
            forceNewDeployment=True,
        )
        click.echo(f"  {bridge_service}: {click.style('new deployment triggered', fg='green')}")

        if not skip_health:
            click.echo("  Waiting for bridge service to stabilize...")
            try:
                aws.wait_for_stable(session, cluster, bridge_service)
                click.echo("  Bridge service stabilized.")
            except Exception as e:
                click.echo(f"  Bridge did not stabilize: {e}", err=True)
    except Exception as e:
        click.echo(f"  {bridge_service}: {click.style(str(e), fg='red')}")


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
        click.echo("  This cogent may be in serverless mode. Use 'update discord' or 'update lambda' instead.")
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
@click.option("--force", is_flag=True, help="Force re-run migrations even if already applied")
@click.pass_context
def update_rds(ctx: click.Context, profile: str, force: bool):
    """Run database schema migrations via the migrate Lambda."""
    import json

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)
    safe_name = name.replace(".", "-")

    fn_name = f"cogent-{safe_name}-migrate"
    click.echo(f"Running migrations for cogent-{name} via {fn_name}...")

    lambda_client = session.client("lambda", region_name=aws.region)
    try:
        payload = json.dumps({"force": force})
        resp = lambda_client.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=payload.encode(),
        )
        result = json.loads(resp["Payload"].read())
        status_code = result.get("statusCode", 0)

        if status_code == 200:
            body = json.loads(result.get("body", "{}"))
            click.echo(f"  Status: {click.style(body.get('status', 'ok'), fg='green')}")
            click.echo(f"  Database: {body.get('database', '?')}")
            tables = body.get("tables", [])
            if tables:
                click.echo(f"  Tables: {len(tables)}")
                for t in tables:
                    click.echo(f"    {t}")
        else:
            click.echo(f"  Migration failed: {click.style(result.get('body', 'unknown error'), fg='red')}")
            sys.exit(1)
    except lambda_client.exceptions.ResourceNotFoundException:
        click.echo(f"  {fn_name}: {click.style('not found', fg='red')}")
        click.echo("  Hint: the migrate Lambda may not be deployed in this stack.")
        sys.exit(1)
    except Exception as e:
        click.echo(f"  Error: {click.style(str(e), fg='red')}")
        sys.exit(1)


@update.command("stack")
@click.option("--egg", default="ovo", help="Egg config to use")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def update_stack(ctx: click.Context, egg: str, profile: str, watch: bool):
    """Full CloudFormation stack update (repackage + deploy)."""
    from body.aws import stack_name_for
    from cli.create import _deploy_and_wait, _package_and_upload_lambdas
    from polis.aws import find_polis_account
    from polis.eggs.ovo.config import OvoConfig

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)

    egg_config = OvoConfig()
    image_uri = egg_config.resolve_image_uri()

    click.echo(f"Updating stack for cogent-{name}...")
    click.echo(f"  Image: {image_uri}")

    vpc_id, subnet_ids = aws.discover_vpc_and_subnets(session)
    lambda_s3_bucket, lambda_s3_key = _package_and_upload_lambdas(session, aws.region)
    polis_account_id = find_polis_account(aws)

    from body.cfn.template import build_template

    hosted_zone_id = ""
    domain = ""
    try:
        _cfn = session.client("cloudformation", region_name=aws.region)
        polis_resp = _cfn.describe_stacks(StackName="cogent-polis")
        polis_outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in polis_resp["Stacks"][0].get("Outputs", [])
        }
        hosted_zone_id = polis_outputs.get("HostedZoneId", "")
        domain = polis_outputs.get("Domain", "")
    except Exception:
        pass

    template = build_template(
        name,
        polis_account_id=polis_account_id,
        vpc_id=vpc_id,
        subnet_ids=subnet_ids,
        image_uri=image_uri,
        command=egg_config.brain_command(),
        extra_env=[
            {"Name": "COGENT_POLICY_REPO", "Value": egg_config.policy.repo},
            {"Name": "COGENT_POLICY_BRANCH", "Value": egg_config.policy.branch},
            {"Name": "COGENT_WORKDIR_PATH", "Value": egg_config.workdir_path},
        ],
        egg=egg,
        lambda_s3_bucket=lambda_s3_bucket,
        lambda_s3_key=lambda_s3_key,
        hosted_zone_id=hosted_zone_id,
        domain=domain,
    )

    stack = stack_name_for(name)
    cfn = session.client("cloudformation", region_name=aws.region)
    _deploy_and_wait(cfn, template, stack, watch=watch, name=name)

    click.echo(f"Stack update for cogent-{name} {'completed' if watch else 'submitted'}.")


@update.command("docker")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.pass_context
def update_docker(ctx: click.Context, profile: str):
    """Build and push Docker image to ECR."""
    import base64
    import subprocess
    from pathlib import Path

    from polis.eggs.ovo.config import OvoConfig

    name = get_cogent_name(ctx)
    aws = _get_aws(profile)
    session, _ = aws.get_cogent_session(name)

    egg_config = OvoConfig()
    click.echo(f"Building and pushing Docker image for cogent-{name}...")

    image_uri = egg_config.resolve_image_uri()
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = repo_root / "src" / "polis" / "eggs" / "ovo" / "docker" / "Dockerfile"

    ecr = session.client("ecr", region_name=aws.region)
    token = ecr.get_authorization_token()
    auth = token["authorizationData"][0]
    registry = auth["proxyEndpoint"]

    click.echo(f"  Logging into ECR ({registry})...")
    login = subprocess.run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        input=auth["authorizationToken"],
        capture_output=True,
        text=True,
    )
    if login.returncode != 0:
        decoded = base64.b64decode(auth["authorizationToken"]).decode()
        password = decoded.split(":", 1)[1]
        login = subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", registry],
            input=password,
            capture_output=True,
            text=True,
        )
        if login.returncode != 0:
            raise RuntimeError(f"ECR login failed: {login.stderr}")

    click.echo(f"  Building image: {image_uri}")
    build = subprocess.run(
        ["docker", "build", "-t", image_uri, "-f", str(dockerfile), str(repo_root)],
        capture_output=False,
    )
    if build.returncode != 0:
        raise RuntimeError("Docker build failed")

    click.echo(f"  Pushing image: {image_uri}")
    push = subprocess.run(
        ["docker", "push", image_uri],
        capture_output=False,
    )
    if push.returncode != 0:
        raise RuntimeError("Docker push failed")

    click.echo("  Image built and pushed.")
