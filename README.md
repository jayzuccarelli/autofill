# autofill

AI-powered form autofill: local profile + RAG + [browser-use](https://github.com/browser-use/browser-use) to fill web forms; you review and submit manually.

Built on the same stack as [Browser Use](https://github.com/browser-use/browser-use) (Python ≥3.11, `Agent` + `ChatBrowserUse` by default).

---

## LLM Quickstart

For Cursor, Claude Code, Copilot, etc.:

1. **Core code:** [`autofill/agent.py`](autofill/agent.py) — `ingest()` / `retrieve()` (Chroma), `main()` task prompt, `cli()` + `load_dotenv()`.
2. **Deps / env:** [`pyproject.toml`](pyproject.toml), [`uv.lock`](uv.lock) — from repo root run `uv sync`.
3. **User profile:** [`knowledge/profile.example.md`](knowledge/profile.example.md) → users copy to `knowledge/profile.md` (gitignored). Chunks are split on blank lines; retrieval is one semantic query + top‑k chunks concatenated into the task string.
4. **Secrets:** `.env` at repo root (gitignored), e.g. `BROWSER_USE_API_KEY` — see [Browser Use Cloud](https://cloud.browser-use.com/new-api-key). Optional: `uv sync --extra anthropic|openai` + matching env vars and `--provider`.
5. **Run:** `uv run autofill <url>` from **repository root** so `knowledge/` resolves.

Upstream agent behavior, models, and cloud docs: [browser-use on GitHub](https://github.com/browser-use/browser-use).

---

## Human Quickstart

**1. Install** (needs [git](https://git-scm.com/)):

```bash
curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
```

That installs [uv](https://docs.astral.sh/uv/) if needed, clones to `~/autofill`, runs `uv sync`, and can prompt for your Browser Use API key (saved to `.env`). Already cloned? From repo root: `./install.sh`.

Fork / custom clone location: set `REPO_URL` or `INSTALL_DIR` before the `curl` command (see [`install.sh`](install.sh)).

**2. Profile**

```bash
cp knowledge/profile.example.md knowledge/profile.md
```

Edit `knowledge/profile.md` with real info (gitignored).

**3. API key**

If you pasted during install, you’re done — autofill loads `.env` on startup. Otherwise put `BROWSER_USE_API_KEY` in `.env` or your environment ([get a key](https://cloud.browser-use.com/new-api-key)).

**4. Run**

```bash
cd ~/autofill   # or your clone path
uv run autofill <url>
```

Optional other providers:

```bash
uv sync --extra anthropic
export ANTHROPIC_API_KEY=…
uv run autofill --provider anthropic <url>
```

---

## How it works

1. You describe yourself in `knowledge/profile.md`
2. On startup, files under `knowledge/` are indexed into a local vector DB (`knowledge/.db/`)
3. The agent gets retrieved chunks in its task, opens the form, and fills fields
4. Submit is never clicked automatically — you review in the browser

---

## Notes

- Run commands from the **repository root** so `knowledge/` is found
- File uploads that need real documents are skipped
- Personal data stays under `knowledge/` and `.env` (see [`.gitignore`](.gitignore))
