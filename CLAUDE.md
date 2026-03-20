# CLAUDE.md — autofill

AI agent that fills out any form, application, or document on behalf of a user.
Users clone this repo, drop their own profile into `agent.py` (or eventually
`knowledge/`), and run it locally against any form URL.

## Architecture

```
autofill/
├── autofill/
│   ├── __init__.py       # package exports
│   └── agent.py          # TASK prompt + browser-use runner
├── knowledge/            # user profile data (future: load at runtime)
├── evals/                # eval scripts run against live URLs
├── tests/                # pytest unit/integration tests
├── pyproject.toml        # deps, ruff, mypy config
└── CLAUDE.md             # this file
```

**Core flow**: `agent.py` builds a TASK prompt from a profile, passes it to a
`browser-use` Agent with `ChatBrowserUse`, which drives a real browser to fill
every form field. The browser stays open so the user can review before submitting.

**Key dependency**: [`browser-use`](https://github.com/browser-use/browser-use) —
`Agent`, `BrowserProfile`, `ChatBrowserUse`. Requires `BROWSER_USE_API_KEY`.

## Development Commands

```bash
uv sync --extra dev                                    # install
uv run python autofill/agent.py                        # run the agent
uv run pytest                                          # tests
uv run ruff check . --fix && uv run ruff format .      # lint + format
uv run mypy autofill/                                  # type check
```

## Code Style

- Python 3.11+, modern typing: `str | None` not `Optional[str]`
- `async`/`await` throughout — browser-use is fully async
- Line length: 88 (ruff default)
- No magic strings: URLs, field names, and task text as named constants

## Extending the Agent

**New profile field**: add the label + value to the TASK string in `agent.py`,
following the existing format. The agent maps form labels loosely.

**Multiple profiles**: move the profile dict into `knowledge/`, load it at
runtime, and template into TASK.

**New evals**: add a script in `evals/` that runs the agent against a target URL.
Use the synthetic Morgan Ashford profile in evals and tests — never commit a real
person's data to the repo.

## Dev / Test Conventions

- Tests and evals use the synthetic Morgan Ashford profile already in `agent.py`
- Keep real personal data out of committed files — users supply their own profile
  locally and it never gets pushed to this repo
- Always lint and type-check before committing
