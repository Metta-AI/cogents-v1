"""cogent brain — unified management of cogent infrastructure and containers."""

from __future__ import annotations

import click


class DefaultCommandGroup(click.Group):
    """Group that defaults to a given subcommand when none is provided."""

    def __init__(self, *args, default_cmd: str = "status", **kwargs):
        super().__init__(*args, **kwargs)
        self.default_cmd = default_cmd

    def parse_args(self, ctx, args):
        if not args or (args[0].startswith("-") and args[0] != "--help"):
            args = [self.default_cmd] + list(args)
        return super().parse_args(ctx, args)


def get_cogent_name(ctx: click.Context) -> str:
    """Return the cogent name from the root context."""
    obj = ctx.find_root().obj
    name = obj.get("cogent_id") if obj else None
    if not name:
        raise click.UsageError(
            "No cogent specified. Use: cogent <name> <command> or set COGENT_ID env var."
        )
    return name


@click.group(cls=DefaultCommandGroup, default_cmd="status")
def brain():
    """Manage cogent infrastructure, ECS, and Lambda components."""
    pass


@brain.command("status")
@click.pass_context
def status_cmd(ctx: click.Context):
    """Show infrastructure status for a cogent."""
    name = get_cogent_name(ctx)
    click.echo(f"Status for cogent-{name}: not yet implemented (needs body.aws)")


@brain.command("create")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--watch", "-w", is_flag=True, help="Wait for stack to complete")
@click.pass_context
def create_cmd(ctx: click.Context, profile: str, watch: bool):
    """Deploy a cogent's CloudFormation stack."""
    name = get_cogent_name(ctx)
    click.echo(f"Creating cogent-{name}: not yet implemented (needs body.aws, body.cfn)")


@brain.command("destroy")
@click.option("--profile", default="softmax-org", help="AWS profile")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--watch", "-w", is_flag=True, help="Wait for deletion to complete")
@click.pass_context
def destroy_cmd(ctx: click.Context, profile: str, yes: bool, watch: bool):
    """Destroy a cogent's CloudFormation stack."""
    name = get_cogent_name(ctx)
    if not yes:
        click.confirm(
            f"This will destroy the stack for cogent-{name}. Continue?",
            abort=True,
        )
    click.echo(f"Destroying cogent-{name}: not yet implemented (needs body.aws)")


# Wire in update subcommands
from brain.update_cli import update  # noqa: E402

brain.add_command(update)
