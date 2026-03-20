# CLAUDE.md — autofill

AI agent that fills out any form or application on your behalf.
Run onboarding once, drop in your documents, point it at a URL, and it fills every field.
You review, then submit manually.

## Setup

```bash
uv sync
```

Requires a `BROWSER_USE_API_KEY` — get one at https://cloud.browser-use.com/new-api-key

## How to use it

### 1. Run onboarding (once)

```bash
uv run python -m autofill.onboarding
```

Answer the prompts. Your profile is saved to `knowledge/profile.md`.

### 2. Add any extra documents (optional)

Drop files into `knowledge/` — resume, cover letter, project reports, etc.
Supported formats: `.pdf`, `.docx`, `.md`, `.txt`

### 3. Build (or rebuild) the knowledge index

```bash
uv run python -m autofill.knowledge
```

Re-run this any time you update or add files to `knowledge/`.

### 4. Point at a form and run

Edit the `url` variable at the top of `autofill/agent.py`, then:

```bash
uv run python autofill/agent.py
```

The browser opens, fills the form from your knowledge base, and stays open for review.
Press Enter in the terminal when you're done.

## What the agent will and won't do

- Fills text fields, dropdowns, radio buttons, checkboxes
- Retrieves the most relevant parts of your profile and documents for each form
- Skips file uploads that require real documents
- **Will not click Submit** — you always review and submit yourself

## Knowledge folder

```
knowledge/
├── profile.md          ← created by onboarding
├── resume.pdf          ← drop in your own files
├── cover_letter.txt
└── projects.md
```

All files in `knowledge/` are git-ignored — your personal data never leaves your machine.
