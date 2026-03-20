# CLAUDE.md

**Claude Code:** read **[AGENTS.md](AGENTS.md)** first — it has architecture, commands, and conventions for this repo.

**TL;DR:** Python ≥3.11, `uv sync` from repo root, put `BROWSER_USE_API_KEY` in `.env` (loaded automatically by `autofill`), add `knowledge/profile.md` from `knowledge/profile.example.md`, then `uv run autofill <url>`. Core code is [`autofill/agent.py`](autofill/agent.py). Human-facing steps: [README.md](README.md).
