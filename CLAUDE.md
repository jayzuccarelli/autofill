# CLAUDE.md — autofill

AI agent that fills out any form, application, or document on behalf of a user.

## Architecture

```
autofill/
├── autofill/
│   ├── __init__.py       # package exports
│   └── agent.py          # core agent: TASK prompt + browser-use runner
├── knowledge/            # user profile data (future: structured profiles)
├── evals/                # evaluation scripts and result snapshots
├── tests/                # pytest test suite
├── pyproject.toml        # project config, deps, tool settings
└── CLAUDE.md             # this file
```

**Core flow**: `agent.py` builds a natural-language TASK prompt from a user profile, hands it to a `browser-use` Agent with a `ChatBrowserUse` LLM, and the agent drives a real browser to detect and fill form fields. The browser is left open for the user to review before submitting.

**Key dependency**: [`browser-use`](https://github.com/browser-use/browser-use) — provides `Agent`, `BrowserProfile`, and `ChatBrowserUse`. Requires `BROWSER_USE_API_KEY`.

## Development Commands

```bash
# install (use uv)
uv sync --extra dev

# run the agent
uv run python autofill/agent.py

# tests
uv run pytest

# lint + format
uv run ruff check . --fix
uv run ruff format .

# type check
uv run mypy autofill/
```

## Code Style

- Python 3.11+, modern typing: `str | None` not `Optional[str]`
- `async`/`await` throughout — browser-use is fully async
- Line length: 88 (ruff default)
- No magic strings: keep URLs, profile fields, and task text as named constants or structured data
- Tests go in `tests/`; evals (live browser runs) go in `evals/`

## Extending the Agent

**To add a new profile field**: update the TASK string in `agent.py` with the new label and value. The agent maps form labels loosely — keep the instruction format consistent with existing entries.

**To support multiple profiles**: move the hardcoded profile dict into `knowledge/`, load it at runtime, and template it into the TASK string.

**To add evals**: add a script in `evals/` that runs the agent against a target URL and asserts expected field values were filled. Do not commit real personal data to `knowledge/` or `evals/`.

## Constraints

- Never click Submit / Apply / Send — the agent must stop short and prompt the user to review
- Never upload real identity documents — skip or use clearly dummy filenames
- Do not commit real personal data; use synthetic profiles (like the Morgan Ashford placeholder)
- Always run lint and type check before committing
