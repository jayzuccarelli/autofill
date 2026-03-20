# CLAUDE.md — autofill

AI agent that fills out any form or application on your behalf.
You give it your profile, point it at a URL, and it fills every field.
You review, then submit manually.

## Setup

```bash
uv sync
```

Requires a `BROWSER_USE_API_KEY` — get one at https://cloud.browser-use.com/new-api-key

## How to use it

1. Open `autofill/agent.py`
2. Replace the profile fields (name, email, address, etc.) with your own info
3. Set `url` to the form you want to fill
4. Run it:

```bash
uv run python autofill/agent.py
```

The browser will open, fill the form, and stay open so you can review.
Press Enter in the terminal when you're done.

## What the agent will and won't do

- Fills text fields, dropdowns, radio buttons, checkboxes
- Skips file uploads that require real documents
- **Will not click Submit** — you always review and submit yourself
