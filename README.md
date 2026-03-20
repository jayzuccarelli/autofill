# autofill

An AI agent that knows you and fills out any form, application, or document on your behalf.

Point it at a URL. It fills every field. You review and submit.

---

## Quick start for LLMs

See [AGENTS.md](AGENTS.md).

---

## Quick start for humans

**1. Get an API key**

Sign up at https://cloud.browser-use.com/new-api-key and copy your `BROWSER_USE_API_KEY`.

**2. Clone and install**

```bash
git clone https://github.com/jayzuccarelli/autofill
cd autofill
uv sync
```

**3. Add your profile**

Open `autofill/agent.py` and replace the example fields with your own:

```python
url = 'https://yourform.com'   # ← the form you want to fill

# then update the profile fields: name, email, address, LinkedIn, etc.
```

**4. Run**

```bash
BROWSER_USE_API_KEY=your_key uv run python autofill/agent.py
```

A browser opens, fills the form, and waits. Review everything, then submit yourself.

---

## What it does and doesn't do

| Does | Doesn't |
|------|---------|
| Text fields, dropdowns, radios, checkboxes | File uploads requiring real documents |
| Maps loose label variations ("Phone" → telephone) | Click Submit / Apply / Send |
| Handles multi-page forms | Store or transmit your profile data |
| Leaves the browser open for review | Make decisions it's not confident about |

---

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv)
- `BROWSER_USE_API_KEY` from https://cloud.browser-use.com/new-api-key
