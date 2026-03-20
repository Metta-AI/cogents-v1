"""CLI for managing cogtainers (create, destroy, list, status)."""

from __future__ import annotations

import os
from pathlib import Path

import click
import yaml

from cogtainer.config import (
    CogtainerEntry,
    CogtainersConfig,
    LLMConfig,
    load_config,
)


def _config_path() -> Path:
    """Return the config file path from env or default."""
    env = os.environ.get("COGOS_CONFIG_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cogos" / "cogtainers.yml"


def _load() -> CogtainersConfig:
    """Load the cogtainers config."""
    return load_config(_config_path())


def _save_config(cfg: CogtainersConfig) -> None:
    """Write CogtainersConfig to YAML."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(cfg.model_dump(exclude_none=True), f, default_flow_style=False)


@click.group()
def cli() -> None:
    """Manage cogtainers."""


@cli.command()
@click.argument("name")
@click.option("--type", "ctype", required=True, type=click.Choice(["aws", "local", "docker"]))
@click.option("--llm-provider", default=None)
@click.option("--llm-model", default=None)
@click.option("--llm-api-key-env", default=None)
@click.option("--region", default=None)
@click.option("--data-dir", default=None)
@click.option("--domain", default=None)
def create(
    name: str,
    ctype: str,
    llm_provider: str | None,
    llm_model: str | None,
    llm_api_key_env: str | None,
    region: str | None,
    data_dir: str | None,
    domain: str | None,
) -> None:
    """Create a new cogtainer."""
    cfg = _load()

    if name in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' already exists.")
        raise SystemExit(1)

    llm = None
    if llm_provider:
        llm = LLMConfig(
            provider=llm_provider,
            model=llm_model or "",
            api_key_env=llm_api_key_env or "",
        )

    entry = CogtainerEntry(
        type=ctype,
        region=region,
        domain=domain,
        data_dir=data_dir,
        llm=llm,
    )
    cfg.cogtainers[name] = entry

    # Set as default if it's the only cogtainer
    if len(cfg.cogtainers) == 1:
        cfg.defaults.cogtainer = name

    # Create data dir for local/docker
    if ctype in ("local", "docker") and data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    _save_config(cfg)
    click.echo(f"Created cogtainer '{name}' (type={ctype}).")


@cli.command()
@click.argument("name")
def destroy(name: str) -> None:
    """Destroy a cogtainer (remove from config)."""
    cfg = _load()

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    if not click.confirm(f"Destroy cogtainer '{name}'?"):
        click.echo("Aborted.")
        return

    del cfg.cogtainers[name]

    if cfg.defaults.cogtainer == name:
        cfg.defaults.cogtainer = None

    _save_config(cfg)
    click.echo(f"Destroyed cogtainer '{name}'.")


@cli.command("list")
def list_cmd() -> None:
    """List all cogtainers."""
    cfg = _load()

    if not cfg.cogtainers:
        click.echo("No cogtainers configured.")
        return

    for name, entry in sorted(cfg.cogtainers.items()):
        default = " (default)" if cfg.defaults.cogtainer == name else ""
        provider = entry.llm.provider if entry.llm else "-"
        click.echo(f"  {name}  type={entry.type}  llm={provider}{default}")


@cli.command()
@click.argument("name", required=False)
def status(name: str | None) -> None:
    """Show details for a cogtainer."""
    cfg = _load()

    if name is None:
        from cogtainer.config import resolve_cogtainer_name

        name = resolve_cogtainer_name(cfg)

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    entry = cfg.cogtainers[name]
    click.echo(f"Cogtainer: {name}")
    click.echo(f"  type: {entry.type}")
    if entry.region:
        click.echo(f"  region: {entry.region}")
    if entry.data_dir:
        click.echo(f"  data_dir: {entry.data_dir}")
    if entry.domain:
        click.echo(f"  domain: {entry.domain}")
    if entry.llm:
        click.echo(f"  llm.provider: {entry.llm.provider}")
        click.echo(f"  llm.model: {entry.llm.model}")


@cli.command("compose")
@click.argument("name")
@click.option("--cogent", "cogent_names", multiple=True, help="Cogent names (repeatable)")
@click.option("--output", "output_path", default=None, help="Output path (default: data_dir/docker-compose.yml)")
def compose(name: str, cogent_names: tuple[str, ...], output_path: str | None) -> None:
    """Generate docker-compose.yml for a docker cogtainer."""
    cfg = _load()

    if name not in cfg.cogtainers:
        click.echo(f"Cogtainer '{name}' not found.")
        raise SystemExit(1)

    entry = cfg.cogtainers[name]
    if entry.type != "docker":
        click.echo(f"Cogtainer '{name}' is type '{entry.type}', not 'docker'.")
        raise SystemExit(1)

    if not cogent_names:
        click.echo("Specify at least one --cogent name.")
        raise SystemExit(1)

    from cogtainer.docker_compose import generate_compose

    content = generate_compose(entry, name, list(cogent_names))

    if output_path:
        out = Path(output_path)
    elif entry.data_dir:
        out = Path(entry.data_dir) / "docker-compose.yml"
    else:
        out = Path("docker-compose.yml")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    click.echo(f"Wrote {out}")


if __name__ == "__main__":
    cli()
