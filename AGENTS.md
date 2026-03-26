# AGENTS.md

Instructions for coding agents (Cursor, Copilot, Devin, etc.) working on **autofill**.

## What this repo is

- **autofill** ingests markdown/PDF under `knowledge/`, stores chunks in **Chroma** (`knowledge/.db/`), retrieves top‑k chunks with a fixed query, and passes them into a **[browser-use](https://github.com/browser-use/browser-use)** `Agent` task so a browser fills a form. The user reviews and submits manually (submit is never clicked by design).
- **Single implementation file:** [`autofill/agent.py`](autofill/agent.py) — `ingest`, `retrieve`, `_llm`, `main`, `cli`, `_onboard*`. Entry: `bin/autofill` wrapper → `cli()`.
- **Onboarding:** `cli()` checks for profile content + API key on every run. If missing, interactive prompts walk the user through setup (profile questions, key, optional files, then `ingest()`).
- **Paths are cwd-relative:** `Path("knowledge")` — commands must run from **repository root**.

## Setup

- **Package manager:** [uv](https://docs.astral.sh/uv/). Install deps: `uv sync` (lockfile: [`uv.lock`](uv.lock)).
- **LLM providers:** Browser Use (default), OpenAI, and Anthropic are all supported out of the box — the `openai` and `anthropic` SDKs ship as browser-use transitive deps, so no extras to install.
- **Secrets:** `.env` in repo root (gitignored). `load_dotenv()` runs at start of `cli()`. Needs one of: `BROWSER_USE_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`. Onboarding prompts the user to pick a provider. `AUTOFILL_PROVIDER` (also in `.env`) records the choice; `--provider` flag or auto-detection from available keys also works.
- **One-shot install for humans:** [`install.sh`](install.sh) + see [README.md](README.md).

## Run

```bash
autofill                              # first time: runs onboarding (profile, provider, key, files, DB)
autofill <form-url>                   # fill a form (provider auto-detected from API key)
autofill --provider anthropic <url>   # override provider
```

Dev shortcut: `uv run autofill …` also works.

## Architecture notes

- **Ingest:** Non-hidden files in `knowledge/` only; chunking = split on blank lines (`\n\n`). PDFs via `pdfplumber`.
- **Retrieve:** `retrieve("contact identity address work experience", n=5)` — single query, **not** full-document paste. Changing `n` or the query changes what reaches the task prompt.
- **Empty profile:** If nothing is indexed, `_onboard()` runs interactively. If still empty after onboarding, exits with `SystemExit` (no silent fabrication).
- **browser-use:** `BrowserProfile(keep_alive=True, headless=False)`, `bu.Agent(task=..., llm=...)`. Upstream behavior and APIs: [browser-use](https://github.com/browser-use/browser-use).

## Dev (optional)

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy autofill/
uv run pytest tests/
```

## Conventions

- Match existing style in `agent.py`; avoid unrelated refactors in the same change.
- User data stays gitignored: `knowledge/*` except `.gitkeep` and `profile.example.md`, plus `.env`.

## Claude Code

See [`CLAUDE.md`](CLAUDE.md) for the short pointer used by Claude Code.

## Cursor Cloud specific instructions

- **uv** must be on PATH. It is installed at `~/.local/bin/uv`; ensure `export PATH="$HOME/.local/bin:$PATH"` is set.
- After pulling, run `uv sync --extra dev` from the repo root to install/update all dependencies.
- All commands (`ruff`, `mypy`, `pytest`, `autofill`) must be run from the **repository root** because paths in `agent.py` are cwd-relative (e.g. `Path("knowledge")`).
- **ChromaDB** runs embedded (in-process); no external database server is needed. First run downloads the ONNX embedding model (~79 MB) to `~/.cache/chroma/`.
- **Google Chrome** is pre-installed. The agent uses `headless=False` by default, so a display (Xvfb or similar) is needed in headless Cloud VMs.
- **Lint/type-check have pre-existing warnings** in upstream code (E501 line-length in ruff, `var-annotated`/`name-defined` in mypy). These are not regressions.
- **No tests exist yet** (`tests/` contains only `.gitkeep`); `pytest` exits with code 5 (no tests collected) — this is expected.
- To exercise core logic without an LLM key: `cp knowledge/profile.example.md knowledge/profile.md`, then `uv run python -c "from autofill.agent import ingest, retrieve; ingest(); print(retrieve('contact identity'))"`. Clean up with `rm -f knowledge/profile.md && rm -rf knowledge/.db`.
- The interactive onboarding (`questionary` prompts) blocks on TTY input. For non-interactive testing, create `knowledge/profile.md` and `.env` manually.
