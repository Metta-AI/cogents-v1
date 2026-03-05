from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import webbrowser
from pathlib import Path

import click

_COGENT_DIR = Path.home() / ".cogents"
_FRONTEND_DIR = Path(__file__).parent.parent.parent / "dashboard" / "frontend"


def _key_file(name: str) -> Path:
    safe = name.replace(".", "-")
    d = _COGENT_DIR / safe
    d.mkdir(parents=True, exist_ok=True)
    return d / "dashboard-key"


@click.group()
def dashboard():
    """Dashboard commands."""
    pass


@dashboard.command()
@click.argument("name")
@click.option("--port", default=8100, help="Backend port")
@click.option("--frontend-port", default=5174, help="Frontend port")
@click.option("--no-browser", is_flag=True, help="Don't open browser")
def serve(name: str, port: int, frontend_port: int, no_browser: bool):
    """Start the dashboard dev server."""
    env = {
        **os.environ,
        "DASHBOARD_COGENT_NAME": name,
        "DASHBOARD_PORT": str(port),
    }

    # Start FastAPI backend
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--host", "0.0.0.0", "--port", str(port)],
        env=env,
    )

    # Start Next.js frontend (if directory exists)
    frontend = None
    if _FRONTEND_DIR.exists():
        frontend = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(_FRONTEND_DIR),
            env={**env, "PORT": str(frontend_port)},
        )

    if not no_browser:
        url = f"http://localhost:{frontend_port}" if frontend else f"http://localhost:{port}"
        webbrowser.open(url)

    click.echo(f"Dashboard running: backend={port}, frontend={frontend_port}")
    click.echo("Press Ctrl+C to stop")

    def shutdown(sig, frame):
        backend.terminate()
        if frontend:
            frontend.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    backend.wait()


@dashboard.command()
@click.argument("name")
def login(name: str):
    """Generate and store an API key locally."""
    key = secrets.token_urlsafe(32)
    kf = _key_file(name)
    kf.write_text(key)
    click.echo(f"API key saved to {kf}")
    click.echo(f"Key: {key}")


@dashboard.command()
@click.argument("name")
def logout(name: str):
    """Remove local API key."""
    kf = _key_file(name)
    if kf.exists():
        kf.unlink()
        click.echo("API key removed")
    else:
        click.echo("No key found")


@dashboard.command()
@click.argument("name")
def keys(name: str):
    """Show local API key."""
    kf = _key_file(name)
    if kf.exists():
        click.echo(f"Key: {kf.read_text().strip()}")
    else:
        click.echo("No key found. Run: cogent dashboard login <name>")
