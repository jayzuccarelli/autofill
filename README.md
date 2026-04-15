# autofill

[![Python ≥3.11](https://img.shields.io/badge/python-%E2%89%A53.11-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

AI-powered form autofill: describe yourself once, then point it at any web form and it fills every field for you. You review and submit manually.

<!-- Add a demo GIF here: record your screen filling a job application and drop it in as ![Demo](demo.gif) -->

Built on [browser-use](https://github.com/browser-use/browser-use).

---

## Why

Every job application asks the same questions. Every registration form wants the same details. You fill them out by hand, over and over, copying from a résumé or your memory.

autofill reads a profile you write once, opens a real browser, and fills every field it can find — name, email, work history, education, socials, whatever the form asks for. When it's done, the browser stays open so you can review everything and hit Submit yourself.

---

## Features

- **One-time setup** — answer a few prompts once, or drop in your résumé/CV as a PDF
- **Works on any web form** — job applications, registrations, surveys, anything
- **Learns from corrections** — edits you make before submitting are remembered for next time
- **File uploads** — attaches your résumé or cover letter when forms ask for documents
- **Multiple LLM providers** — Browser Use (cheapest), OpenAI, or Anthropic
- **Never auto-submits** — you always review before anything is sent
- **Your data stays local** — profile and documents live on your machine, never uploaded to autofill servers

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/jayzuccarelli/autofill/main/install.sh | bash
```

Requires Python 3.11+ and a supported OS (macOS or Linux). Windows is untested.

---

## Setup

```bash
autofill
```

First run walks you through:

1. **Profile** — name, email, phone, location, socials, and a short bio
2. **API key** — pick a provider and paste your key (saved to `.env`, never leaves your machine)
3. **Extra files** — optionally drop in a résumé, cover letter, etc. from `knowledge/`
4. **Index** — builds a local database of your profile content

You can re-run `autofill` at any time to update your setup.

### Providers

| Provider | Key env var | Notes |
|---|---|---|
| Browser Use | `BROWSER_USE_API_KEY` | Default — cheapest, no extra config |
| OpenAI | `OPENAI_API_KEY` | Uses `gpt-4o` |
| Anthropic | `ANTHROPIC_API_KEY` | Uses `claude-sonnet-4-20250514` |

---

## Fill a form

```bash
autofill https://jobs.example.com/apply
```

The agent opens a browser, fills the form, and leaves it open for you to review and submit.

```bash
autofill --provider anthropic https://jobs.example.com/apply  # override provider
```

---

## Updating your profile

Edit `knowledge/profile.md` directly, or drop new files (PDF, markdown, text) into `knowledge/`. The database re-indexes automatically on every run.

---

## Uninstall

```bash
autofill uninstall
```

Removes the tool and all local files including your profile and knowledge directory.

---

## Privacy & telemetry

Your profile and documents never leave your machine — autofill reads them locally and passes them directly to the LLM you configured.

autofill collects **anonymous** usage events (tool version, OS, LLM provider, whether a run completed) to help prioritise development. No personal data, no form content, no URLs. To opt out:

```bash
echo "AUTOFILL_TELEMETRY=0" >> .env
```

---

## LLM Quickstart (for coding agents)

For Cursor, Claude Code, Copilot, etc.: start with [`AGENTS.md`](AGENTS.md). Claude Code also loads [`CLAUDE.md`](CLAUDE.md).
