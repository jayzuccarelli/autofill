# autofill

AI-powered form autofill: describe yourself once, then point it at any web form and it fills every field for you. You review and submit manually.

Built on [browser-use](https://github.com/browser-use/browser-use).

---

## LLM Quickstart

For Cursor, Claude Code, Copilot, etc.: **start with [`AGENTS.md`](AGENTS.md)**. Claude Code also loads [`CLAUDE.md`](CLAUDE.md).

---

## Install

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/jayzuccarelli/autofill@main/install.sh | bash
```

Then open a new terminal (or `source ~/.zshrc`).

---

## Use

```bash
autofill
```

The first time you run it, autofill walks you through setup:
1. **Profile** — asks your name, email, phone, location, and a short summary; saves to `knowledge/profile.md`.
2. **API key** — shows where to get a Browser Use key and lets you paste it; saves to `.env`.
3. **Extra files** — optionally add resumes, cover letters, etc. to `knowledge/`.
4. **Builds the database** — indexes everything under `knowledge/` so it's ready.

After setup:

```bash
autofill https://jobs.example.com/apply
```

The agent opens a browser, fills the form, and leaves it open for you to review and submit.

---

## Notes

- The agent will **not** click Submit — you always review first
- Run `autofill` again any time to re-run setup if something is missing
- Edit `knowledge/profile.md` or add files to `knowledge/` to update your info; the database re-indexes on each run
- File uploads requiring real documents are skipped
