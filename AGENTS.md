# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

**autofill** is a Python-based AI agent that uses `browser-use` to autonomously fill web forms via Chrome DevTools Protocol (CDP). The single entry point is `autofill/agent.py`.

### Dev tools and commands

- **Package manager:** `uv` (lockfile: `uv.lock`). Install deps: `uv sync --extra dev`
- **Lint:** `uv run ruff check .` (pre-existing lint issues in `agent.py` are in the upstream code — all in the `TASK` f-string and comments, not introduced by setup)
- **Type check:** `uv run mypy autofill/` (1 pre-existing `var-annotated` warning in upstream code)
- **Tests:** `uv run pytest tests/ -v` (no tests exist yet; directory is empty)
- **Run agent:** `uv run python -m autofill.agent`

### Required secrets

- `BROWSER_USE_API_KEY` — required at runtime for the Browser Use Cloud LLM API. Get one at https://cloud.browser-use.com/new-api-key. Without this key the agent will fail immediately with a `ValueError`.

### Runtime notes

- The agent runs Chrome via CDP with `headless=False` by default. In a headless Cloud VM, Xvfb or a display server must be available, or the `BrowserProfile` must be changed to `headless=True`.
- Google Chrome is pre-installed in the Cloud VM image.
- The `uv` binary is installed at `~/.local/bin/uv`; the PATH is set up during environment provisioning.
