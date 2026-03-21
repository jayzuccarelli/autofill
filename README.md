# autofill

AI-powered form autofill: describe yourself once, then point it at any web form and it fills every field for you. You review and submit manually.

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

### Setup

```bash
autofill
```

The first time you run it, autofill walks you through:
1. **Profile** — asks your name, date of birth, email, phone, location, socials, and a short summary; saves to `knowledge/profile.md`.
2. **API key** — lets you pick a provider (Browser Use, OpenAI, or Anthropic), then paste your key; saves to `.env`.
3. **Extra files** — optionally add resumes, cover letters, etc. to `knowledge/`.
4. **Builds the database** — indexes everything under `knowledge/` so it's ready.

### Fill a form

```bash
autofill https://jobs.example.com/apply
```

The agent opens a browser, fills the form, and leaves it open for you to review and submit.

### Uninstall

```bash
autofill uninstall
```

---

## Notes

- The agent will **not** click Submit — you always review first
- Run `autofill` again any time to re-run setup if something is missing
- Edit `knowledge/profile.md` or add files to `knowledge/` to update your info; the database re-indexes on each run
- File uploads requiring real documents are skipped
