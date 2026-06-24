# CLAUDE.md

**Claude Code:** read **[AGENTS.md](AGENTS.md)** first — it has architecture, commands, and conventions for this repo.

**TL;DR:** Python ≥3.11, `uv sync` from repo root, put an API key (`BROWSER_USE_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY`) in `.env` — or set `AUTOFILL_PROVIDER=ollama` to use a local Ollama server (loaded automatically by `autofill`). Add `knowledge/profile.md` from `knowledge/profile.example.md`, then `uv run autofill '<url>'`. Core code is [`autofill/agent.py`](autofill/agent.py). Human-facing steps: [README.md](README.md).

## Issue tracking (Linear)

Work for this repo is tracked in Linear — team **JAY**, project **autofill**.

- **Keep Linear tidy as you work, without being asked.** When Jay asks you to fix/build something, first check it has an issue in this project (`list_issues`, team JAY, project `autofill`) — if not, create one. When he says "remember to do X later," file it. Mark issues In Progress when you start; make sure they end up Done when finished.
- Found a bug, TODO, or follow-up? File it as a Linear issue in this project instead of leaving a stray code comment or a separate list.
- Linear generates a branch name per issue (`jayzuccarelli/jay-NN-...`); work on that branch.
- Put `Fixes JAY-NN` in the PR description or a commit message — merging then auto-closes the issue.
- Don't keep a parallel todo list; Linear is the source of truth.
