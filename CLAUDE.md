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
- **Standards** (full text in `AGENTS.md` → *Engineering standards*): TDD —
  test first, always; DDD — dependencies point inward, `domain` imports nothing
  from the framework; SOLID, all five; coverage is a **ratchet** at
  `fail_under = 82` and only goes up. `pytest` can fail with every test green
  if coverage drops — that's a red.
- **Subagents** (`.claude/agents/`): `verificador` runs `make check` and gives a
  VERDE/ROJO/INESTABLE verdict — run it before every commit. `arquitecto`
  reviews hexagonal boundaries; it only reads.
