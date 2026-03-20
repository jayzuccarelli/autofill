# autofill
An AI agent that knows you and fills out any form, application, or document on your behalf.

## How it works
1. You describe yourself in `knowledge/profile.md`
2. At startup, your profile is indexed into a local vector database
3. When you point it at a form, the agent retrieves the relevant parts of your profile and fills every field automatically
4. The browser stays open for you to review and submit manually

## Setup

### 1. Install
```bash
git clone <repo>
cd autofill
uv pip install -e .
```

### 2. Set up your profile
```bash
cp knowledge/profile.example.md knowledge/profile.md
```
Edit `knowledge/profile.md` with your real information. This file is gitignored and never committed.

### 3. Add your API key
```bash
export BROWSER_USE_API_KEY=your_key_here
```
Get a key at [browser-use.com](https://browser-use.com).

## Usage
```bash
autofill <url>
```

Example:
```bash
autofill https://jobs.example.com/apply
```

The agent will open a browser, fill every applicable field, and prompt you to review before submitting.

## Notes
- The agent will **never** click Submit — you always review and submit manually
- File uploads requiring real documents are skipped
- Your profile is stored locally in `knowledge/.db/` and only re-indexed when files change
