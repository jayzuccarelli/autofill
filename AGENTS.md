# AGENTS.md

Instructions for coding agents (Cursor, Copilot, Devin, etc.) working on **autofill**.

## What this repo is

- **autofill** ingests markdown/PDF under `knowledge/`, stores chunks in **Chroma** (`knowledge/.db/`), retrieves top‑k chunks with a fixed query, and passes them into a **[browser-use](https://github.com/browser-use/browser-use)** `Agent` task so a browser fills a form. The user reviews and submits manually (submit is never clicked by design).
- **Single implementation file:** [`autofill/agent.py`](autofill/agent.py) — `ingest`, `retrieve`, `_llm`, `main`, `cli`, `_onboard*`. Entry point: `[project.scripts]` in `pyproject.toml` → `cli()`. Invoke with `uv run autofill '<url>'`.
- **Onboarding:** `cli()` checks for profile content + API key on every run. If missing, interactive prompts walk the user through setup (profile questions, key, optional files, then `ingest()`).
- **Paths are cwd-relative:** `Path("knowledge")` — commands must run from **repository root**.

## Setup

- **Package manager:** [uv](https://docs.astral.sh/uv/). Install deps: `uv sync` (lockfile: [`uv.lock`](uv.lock)).
- **LLM providers:** Browser Use (default), Anthropic, OpenAI, and Ollama (local) are all supported out of the box — the `anthropic`, `openai`, and `ollama` SDKs ship as browser-use transitive deps, so no extras to install.
- **Secrets:** `.env` in repo root (gitignored). `load_dotenv()` runs at start of `cli()`. Needs one of: `BROWSER_USE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `AUTOFILL_PROVIDER=ollama` (no key — talks to a local Ollama server). Onboarding prompts the user to pick a provider. `AUTOFILL_PROVIDER` (also in `.env`) records the choice; `--provider` flag or auto-detection from available keys also works. Ollama is never auto-detected — only the explicit `AUTOFILL_PROVIDER=ollama` activates it. Ollama model override: `AUTOFILL_OLLAMA_MODEL` (defaults to `cfg.ollama_model`); host override: standard `OLLAMA_HOST` (default `http://localhost:11434`).
- **One-shot install for humans:** [`install.sh`](install.sh) + see [README.md](README.md).
- **Observability:** [`autofill/telemetry.py`](autofill/telemetry.py) handles both PostHog (anonymous usage events, **opt-out** via `AUTOFILL_TELEMETRY=0`) and Sentry (crash reports, **opt-in** via `AUTOFILL_SENTRY=1`). Asymmetric defaults are intentional: PostHog events are author-controlled and contain no PII, while Sentry captures stack frames that could incidentally include profile data. `init_sentry()` is called from `cli()` right after `load_dotenv()`.

## Run

```bash
autofill                              # first time: runs onboarding (profile, provider, key, files, DB)
autofill '<form-url>'                 # fill a form (provider auto-detected from API key)
autofill --provider anthropic '<url>' # override provider
```

Dev shortcut: `uv run autofill …` also works.

## Architecture notes

- **Ingest:** Non-hidden files in `knowledge/` only; chunking tries four separators in order (`\n\n`, `\n`, `". "`, `" "`) to find a clean break point within `cfg.chunk_size` chars, with `cfg.chunk_overlap` overlap between consecutive chunks. PDFs via `pdfplumber`.
- **Retrieve:** `retrieve(cfg.retrieval_query, n=cfg.retrieval_n)` — single query, **not** full-document paste. Both the query string and *n* live in the `Config` dataclass at the top of `agent.py`.
- **Empty profile:** If nothing is indexed, `_onboard()` runs interactively. If still empty after onboarding, exits with `SystemExit` (no silent fabrication).
- **browser-use:** `BrowserProfile(keep_alive=True, headless=False, user_data_dir=cfg.browser_profile_dir)`, `bu.Agent(task=..., llm=...)`. The `user_data_dir` (`~/.autofill/browser-profile`) persists logins across runs — its path must not contain "chrome" or browser-use copies it to a temp dir and persistence breaks. Upstream behavior and APIs: [browser-use](https://github.com/browser-use/browser-use).
- **Login walls:** the task prompt tells the agent to stop with a `LOGIN_REQUIRED` sentinel (never type credentials). `main()` detects it via `agent.history.final_result()`, pauses for the user to sign in manually, then rebuilds the agent on the same `browser_session` and re-runs on the same URL — up to two resumes.
- **Chrome cookie seed (optional):** onboarding offers to import existing Chrome logins via `browser_cookie3` (`_import_chrome_cookies`), written to `~/.autofill/seed-cookies.json` in Playwright `storage_state` shape. The next run passes it as `BrowserProfile(storage_state=...)` so browser-use loads the cookies into the persistent profile, then deletes the seed file (one-time). Best-effort: silently no-ops if Chrome/cookies are unreadable, falling back to the manual login flow.

## Dev (optional)

```bash
uv sync --extra dev
uv run ruff check .
uv run ty check
uv run pytest tests/
```

## Conventions

- Match existing style in `agent.py`; avoid unrelated refactors in the same change.
- User data stays gitignored: `knowledge/*` except `.gitkeep` and `profile.example.md`, plus `.env`.

## Claude Code

See [`CLAUDE.md`](CLAUDE.md) for the short pointer used by Claude Code.
