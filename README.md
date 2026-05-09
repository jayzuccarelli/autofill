# autofill

[![Python ≥3.11](https://img.shields.io/badge/python-%E2%89%A53.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<img src=".github/assets/phil.svg" alt="Phil, the autofill octopus" width="180" align="left">

AI-powered form autofill: describe yourself once, then point it at any web form and it fills every field for you. You review and submit manually.

Meet **Phil** — eight hands on the keyboard so you don't have to use any.

<br clear="left">


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
| Browser Use | `BROWSER_USE_API_KEY` | Default — managed, no extra setup |
| OpenAI | `OPENAI_API_KEY` | Uses `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | Uses `claude-sonnet-4-6` |

### Fill a form

```bash
autofill "https://jobs.example.com/apply"
```

The agent opens a browser, fills the form, and leaves it open for you to review and submit.

> **Always wrap the URL in quotes.** Bare URLs with `?` or `&` are interpreted by the shell — `&` backgrounds the command and your URL gets truncated. Quoting hands the full URL to autofill verbatim.

```bash
autofill --provider anthropic "https://jobs.example.com/apply?ref=xyz"  # override provider
```

### Uninstall

```bash
autofill uninstall
```

---

## What works best

autofill is designed for forms that don't require sign-in. It's been tested with:

- **Greenhouse** (`*.greenhouse.io`)
- **Lever** (`jobs.lever.co`)
- **Ashby** (`jobs.ashbyhq.com`)
- **Workable** (`apply.workable.com`)
- Generic single-page HTML forms (Google Forms, Typeform, etc.)

### Known limitations

- **Login walls** — autofill opens the URL and starts filling immediately. It won't pause for you to sign in. Sites that require an account before showing the form (Workday, iCIMS, LinkedIn Easy Apply, Indeed) won't work in this version; the agent will detect the login form and stop rather than try to fill it.
- **CAPTCHAs** — Cloudflare challenges, reCAPTCHA, and similar bot checks halt the agent. The browser stays open so you can solve them manually, but the agent won't resume automatically.
- **Very long multi-step apps** — supported up to ~50 LLM steps (configurable in `Config.agent_max_steps`); longer applications may exhaust the budget before reaching the final review screen.

---

## Notes

- The agent will **not** click Submit — you always review first
- Learns from your corrections — edits you make before submitting are remembered for next time
- Run `autofill` again any time to re-run setup if something is missing
- Edit `knowledge/profile.md` or add files to `knowledge/` to update your info; the database re-indexes on each run
- Any `.pdf`, `.doc`, or `.docx` in `knowledge/` is offered to the agent for file-upload fields; it picks which file matches which upload based on form labels
- `knowledge/` and `.env` always live inside the install directory (`~/autofill/` by default), regardless of where you run `autofill` from

## Privacy & telemetry

Your profile and documents stay on your machine — autofill reads them locally and stores corrections locally. Relevant excerpts are sent to the LLM provider you configured (Browser Use, OpenAI, or Anthropic) so it can fill in form fields; that content is subject to your provider's data-handling policy. Passwords, SSNs, and similar sensitive fields are stripped before any corrections are saved.

autofill collects **anonymous** usage events (tool version, OS, LLM provider, whether a run completed) to help prioritize development. No personal data, no form content, no URLs. To opt out, set `AUTOFILL_TELEMETRY=0` in your shell:

```bash
# zsh
echo 'export AUTOFILL_TELEMETRY=0' >> ~/.zshrc
# bash (Linux)
echo 'export AUTOFILL_TELEMETRY=0' >> ~/.bashrc
# bash (macOS)
echo 'export AUTOFILL_TELEMETRY=0' >> ~/.bash_profile
```

Then open a new terminal.

## Contributing

Found a bug or have a feature idea? [Open an issue](https://github.com/jayzuccarelli/autofill/issues) — there are templates for both. PRs welcome; start with [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup and [`AGENTS.md`](AGENTS.md) for architecture. MIT licensed.
