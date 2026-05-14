"""`us` console script.

Thin wrapper over the SDK. Every subcommand should be implementable in a few
lines that import the matching SDK module, do one thing, and emit either a
human-friendly line or a JSON document on `--json`.

Subcommand groups are populated in later phases:

* Phase 1 — `us stack {up,down,status}`, `us doctor`
* Phase 2 — `us act {click,move,type,key}`, `us scene capture`
* Phase 3 — `us game {launch,kill,is-running,status,scaffold,list}`
* Phase 4 — `us scene {wait-for,wait-quiescent,diff}`, `us ref {record,list,show}`
* Phase 5 — `us run <path>`
"""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


@app.callback()
def _root(
    json: bool = typer.Option(False, "--json", help="Emit machine-readable output."),
    ctx: typer.Context = None,  # type: ignore[assignment]
) -> None:
    """understudy CLI."""
    if ctx is not None:
        ctx.obj = {"json": json}


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
