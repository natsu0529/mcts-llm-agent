"""Command-line entry point."""

from typing import Annotated

import typer

from agent_mcts import __version__

app = typer.Typer(
    help="Turn any coding agent into a tree-searching agent.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agent-mcts {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """agent-mcts — MCTS test-time search for coding agents."""


@app.command()
def run(
    task: Annotated[str, typer.Argument(help="The task to search a solution for.")],
) -> None:
    """Search for a solution to TASK with your coding agent."""
    typer.echo("agent-mcts is pre-alpha: `run` is not implemented yet. Follow the repo for v0.1.")
    raise typer.Exit(code=1)
