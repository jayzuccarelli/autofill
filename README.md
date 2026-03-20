# autofill
An AI agent that knows you and fills out any form, application, or document on your behalf.

## Install

**One line** (needs [git](https://git-scm.com/) and a network connection):

```bash
curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
```

That installs [uv](https://docs.astral.sh/uv/) if needed, clones into `~/autofill`, installs dependencies from the lockfile, optionally asks for your Browser Use API key and saves it to `.env`, then tells you the next commands.

Already have the repo? From the repo root:

```bash
./install.sh
```

Fork or different clone path? Set `REPO_URL` or `INSTALL_DIR` in the environment before running the `curl` command (see `install.sh`).

**Why not literally like Claude Code?** Claude ships a **native installer** for a single binary. This project is **Python + a real browser**; the closest seamless option without building per-OS binaries is **one script** that owns uv + deps + clone. Same *shape* as `curl | bash`, not the same *weight* as a vendor-hosted binary.

## How it works
1. You describe yourself in `knowledge/profile.md`
2. At startup, your profile is indexed into a local vector database
3. The agent retrieves relevant chunks and fills the form
4. The browser stays open for you to review and submit manually

## After install
1. Copy and edit your profile: `cp knowledge/profile.example.md knowledge/profile.md`
2. **API key:** If you already pasted it during install, **nothing else to do** — it was saved to `.env` and autofill reads that file automatically when you run it. If you skipped that step, add the key to a `.env` file in the project folder or set `BROWSER_USE_API_KEY` in your environment ([get a key](https://cloud.browser-use.com/new-api-key)).
3. From the repo directory: `uv run autofill <url>`

Other providers (optional):

```bash
uv sync --extra anthropic
export ANTHROPIC_API_KEY=…
uv run autofill --provider anthropic <url>
```

## Notes
- Run from the **repository root** so `knowledge/` is found
- The agent will **not** click Submit — you review and submit manually
- File uploads requiring real documents are skipped
- Profile data lives under `knowledge/` locally (see `.gitignore`)
