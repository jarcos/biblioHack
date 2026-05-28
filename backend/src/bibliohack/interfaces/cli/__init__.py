"""CLI interface — typer-based entry points.

`bibliohack ...` resolves to the `cli` typer App in `app.py`. Each bounded
context adds its own subcommand group via `cli.add_typer(...)`.
"""
