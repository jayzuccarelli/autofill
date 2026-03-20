# AGENTS.md — autofill

Quick reference for LLMs and AI coding assistants working in this repo.

## What this project is

`autofill` is a Python CLI tool that uses the `browser-use` library to drive a real browser and fill out web forms on behalf of an end user. The user runs onboarding once, drops their documents into `knowledge/`, and the agent retrieves relevant context at runtime to fill each form. The agent never clicks Submit.

## Repo layout

```
autofill/
├── autofill/
│   ├── __init__.py
│   ├── agent.py          # entry point — builds TASK from knowledge, runs browser-use
│   ├── knowledge.py      # RAG module: ingest, embed, index, retrieve
│   └── onboarding.py     # interactive CLI to create knowledge/profile.md
├── knowledge/            # user's personal files — all git-ignored
│   ├── .gitkeep
│   ├── profile.md        # created by onboarding
│   └── *.pdf / *.docx / *.txt / *.md   # drop in resume, cover letter, etc.
├── evals/                # reserved for eval scripts
├── tests/                # pytest tests
├── pyproject.toml
├── CLAUDE.md             # end-user instructions
└── AGENTS.md             # this file
```

## Core flow

1. **Onboarding** (`autofill/onboarding.py`): user answers prompts → `knowledge/profile.md` written
2. **Indexing** (`autofill/knowledge.py`): all files in `knowledge/` are parsed, chunked (~400 words, 40-word overlap), embedded with `fastembed` (BAAI/bge-small-en-v1.5), and stored in `knowledge/.index.pkl`
3. **Agent** (`autofill/agent.py`): at startup, calls `build_index()` (no-op if index exists), then `retrieve()` with a broad profile query → injects top-10 chunks into the `TASK` prompt → passes to `bu.Agent`
4. `browser-use` drives a real Chromium browser to observe and fill each field
5. The browser stays alive (`keep_alive=True`) until the user presses Enter

## Key modules

### `autofill/knowledge.py`

```python
build_index(force=False)   # parse knowledge/ → chunk → embed → save .index.pkl
retrieve(query, n=10)      # embed query, cosine-rank stored vectors, return top-n as string
```

Run as a script to force a rebuild:
```bash
uv run python -m autofill.knowledge
```

### `autofill/onboarding.py`

Prompts for ~20 profile fields, writes `knowledge/profile.md`.

```bash
uv run python -m autofill.onboarding
```

### `autofill/agent.py`

```python
build_task(url)   # calls build_index() + retrieve(), returns formatted TASK string
```

The `url` variable at the top is the only thing users normally change.

## Key types and imports

```python
import browser_use as bu

llm = bu.ChatBrowserUse()                           # uses BROWSER_USE_API_KEY
profile = bu.BrowserProfile(keep_alive=True, headless=False)
agent = bu.Agent(task=TASK, llm=llm, browser_profile=profile)
await agent.run()
```

## Supported document formats

| Extension | Parser |
|-----------|--------|
| `.pdf`    | `pypdf.PdfReader` |
| `.docx`   | `python-docx` |
| `.md` `.txt` `.csv` etc. | plain `read_text()` |

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
uv run python -m autofill.onboarding       # first time
uv run python -m autofill.knowledge        # build/rebuild index
uv run python autofill/agent.py            # fill a form
```

## Testing and linting

```bash
uv sync --extra dev
uv run pytest
uv run ruff check . --fix && uv run ruff format .
uv run mypy autofill/
```

Never commit real personal data. Use the synthetic Morgan Ashford profile for tests/evals only.
