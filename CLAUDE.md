# CLAUDE.md

See [`AGENTS.md`](./AGENTS.md) — the canonical guidance for AI assistants and
contributors working in this repo. (This pointer exists so Claude Code, which
looks for `CLAUDE.md`, finds it.)

Quick reminders, full detail in `AGENTS.md`:

- Full design: `docs/design/architecture.md`.
- **Docs are generated:** edit the Markdown under `docs/`, then run `make docs`;
  never hand-edit `docs/site/*.html`. CI fails on a stale site.
- Ship workflow: commit + push to `main`; CI gates and auto-deploys. Never deploy
  on red. Backend gate: `ruff format --check .`, `ruff check .`, `mypy src`, `pytest`.
- Add an Alembic revision for every schema change.
- Be a good OPAC citizen — never raise crawler request rates casually.
- Don't break the OpenTelemetry instrumentation in `infra/backend.Dockerfile`.
