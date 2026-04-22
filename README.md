<p align="center">
  <img src=".github/assets/phil.svg" alt="Phil, the autofill octopus" width="220">
</p>

<h1 align="center">autofill</h1>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python ≥3.11"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
</p>

<p align="center">
  AI-powered form autofill: describe yourself once, then point it at any web form and it fills every field for you. You review and submit manually.<br>
  Meet <strong>Phil</strong> — eight hands on the keyboard so you don't have to use any.
</p>

Built on [browser-use](https://github.com/browser-use/browser-use).

---

## LLM Quickstart

For Cursor, Claude Code, Copilot, etc.: start with [`AGENTS.md`](AGENTS.md). Claude Code also loads [`CLAUDE.md`](CLAUDE.md).

---

## Human Quickstart

### Install

Open a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
```

Requires Python 3.11+ and a supported OS (macOS or Linux). Windows is untested.

### Setup

```bash
autofill
```

The first time you run it, autofill walks you through:
1. **Profile** — asks your name, date of birth, email, phone, location, socials, and a short summary; saves to `knowledge/profile.md`.
2. **API key** — lets you pick a provider (Browser Use, OpenAI, or Anthropic), then paste your key; saves to `.env`.
3. **Extra files** — optionally add resumes, cover letters, etc. to `knowledge/`.
4. **Builds the database** — indexes everything under `knowledge/` so it's ready.

#### Providers

| Provider | Key env var | Notes |
|---|---|---|
| Browser Use | `BROWSER_USE_API_KEY` | Default — cheapest, no extra config |
| OpenAI | `OPENAI_API_KEY` | Uses `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | Uses `claude-sonnet-4-20250514` |

### Fill a form

```bash
autofill https://jobs.example.com/apply
```

The agent opens a browser, fills the form, and leaves it open for you to review and submit.

```bash
autofill --provider anthropic https://jobs.example.com/apply  # override provider
```

### Uninstall

```bash
autofill uninstall
```

---

## Notes

- The agent will **not** click Submit — you always review first
- Learns from your corrections — edits you make before submitting are remembered for next time
- Run `autofill` again any time to re-run setup if something is missing
- Edit `knowledge/profile.md` or add files to `knowledge/` to update your info; the database re-indexes on each run
- Any `.pdf`, `.doc`, or `.docx` in `knowledge/` is offered to the agent for file-upload fields; it picks which file matches which upload based on form labels

## Privacy & telemetry

Your profile and documents never leave your machine — autofill reads them locally and passes them directly to the LLM you configured.

autofill collects **anonymous** usage events (tool version, OS, LLM provider, whether a run completed) to help prioritise development. No personal data, no form content, no URLs. To opt out:

```bash
echo "AUTOFILL_TELEMETRY=0" >> .env
```
