# agents.md — autofill

Quick reference for LLMs and AI coding assistants working in this repo.

## What this project is

`autofill` is a Python CLI tool that uses the `browser-use` library to drive a real browser and fill out web forms on behalf of an end user. The user provides their profile, points the tool at a URL, reviews the result, and submits manually. The agent never clicks Submit.

## Repo layout

```
autofill/
├── autofill/
│   ├── __init__.py
│   └── agent.py        # entry point — profile + TASK prompt + browser-use runner
├── knowledge/          # reserved for future profile loading
├── evals/              # reserved for eval scripts
├── tests/              # pytest tests
├── pyproject.toml
├── CLAUDE.md           # instructions for Claude Code (end-user focused)
└── agents.md           # this file
```

## Core flow

1. `agent.py` defines a `TASK` string — a plain-English prompt describing the user's profile and fill rules
2. That prompt is passed to `bu.Agent(task=TASK, llm=bu.ChatBrowserUse(), ...)`
3. `browser-use` drives a real Chromium browser to observe and fill each field
4. The browser stays alive (`keep_alive=True`) until the user presses Enter

## Key types and imports

```python
import browser_use as bu

llm = bu.ChatBrowserUse()                           # uses BROWSER_USE_API_KEY
profile = bu.BrowserProfile(keep_alive=True, headless=False)
agent = bu.Agent(task=TASK, llm=llm, browser_profile=profile)
await agent.run()
```

## How to add or change profile fields

Edit the `TASK` f-string in `autofill/agent.py`. The agent maps form labels loosely, so adding a line like:

```
- GitHub URL: https://github.com/yourhandle
```

is enough — no code changes required beyond the string.

## Constraints the agent enforces (via TASK prompt)

- Never click Submit, Apply, Send, or any finalizing control
- Skip file uploads that require real documents
- When done, call the `done` action and tell the user to review and submit manually

## Environment

| Variable | Purpose |
|----------|---------|
| `BROWSER_USE_API_KEY` | Required. Authenticates with cloud.browser-use.com |

## Running

```bash
uv sync
BROWSER_USE_API_KEY=your_key uv run python autofill/agent.py
```

## Testing and linting (for contributors)

```bash
uv sync --extra dev
uv run pytest
uv run ruff check . --fix && uv run ruff format .
uv run mypy autofill/
```

Use the synthetic Morgan Ashford profile already in `agent.py` for any tests or evals. Never commit real personal data.
