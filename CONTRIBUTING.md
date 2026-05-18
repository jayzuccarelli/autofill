# Contributing to autofill

Thanks for your interest! autofill is a small project with a single implementation file ([`autofill/agent.py`](autofill/agent.py)) and a clear scope: take a profile, hand it to a browser-use agent, fill a form. Bug reports, fixes, and tightly scoped features are all welcome.

## Filing an issue

Please use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) — we need OS, Python version, LLM provider, and (if possible) the form URL to reproduce. For feature ideas, open a regular issue describing the use case before writing code, so we can discuss scope.

## Dev setup

```bash
git clone https://github.com/jayzuccarelli/autofill.git
cd autofill
uv sync --extra dev
cp knowledge/profile.example.md knowledge/profile.md   # then edit
```

Add an API key to `.env` (one of `BROWSER_USE_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`) and run `uv run autofill <url>`.

## Before you open a PR

```bash
uv run ruff check .
uv run pytest tests/
```

Both must pass — CI runs the same on Python 3.11 and 3.12. New behavior should come with at least a smoke test in [`tests/test_smoke.py`](tests/test_smoke.py).

## Conventions

- Read [AGENTS.md](AGENTS.md) first — architecture, ingest/retrieve flow, and key files are documented there.
- Match the existing style in `agent.py`; avoid unrelated refactors in a behavioral change.
- The agent must **never** click Submit/Apply/Send. That guarantee is load-bearing.
- User data stays gitignored: `knowledge/*` (except `.gitkeep` and `profile.example.md`), `.env`, and `.autofill_install_id`.

## License

By contributing, you agree your contribution is licensed under the [MIT License](LICENSE).
