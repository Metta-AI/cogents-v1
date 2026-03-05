import click

from cli.dashboard import dashboard


@click.group()
def main():
    """Cogent CLI."""
    pass


main.add_command(dashboard)

if __name__ == "__main__":
    main()
