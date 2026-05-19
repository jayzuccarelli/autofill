# CLAUDE.md

**Claude Code:** read **[AGENTS.md](AGENTS.md)** first — it has architecture, commands, and conventions for this repo.

**TL;DR:** Python ≥3.11, `uv sync` from repo root, put an API key (`BROWSER_USE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`) in `.env` — or set `AUTOFILL_PROVIDER=ollama` to use a local Ollama server (loaded automatically by `autofill`). Add `knowledge/profile.md` from `knowledge/profile.example.md`, then `uv run autofill <url>`. Core code is [`autofill/agent.py`](autofill/agent.py). Human-facing steps: [README.md](README.md).
