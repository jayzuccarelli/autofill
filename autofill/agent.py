"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

import asyncio
from pathlib import Path

import browser_use as bu
import chromadb

_KNOWLEDGE_DIR = Path("knowledge")
_DB_PATH = _KNOWLEDGE_DIR / ".db"
_COLLECTION = "profile"


def _client() -> chromadb.ClientAPI:
    _DB_PATH.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(_DB_PATH))


def _read(path: Path) -> str:
    if path.suffix == ".pdf":
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return path.read_text()


def ingest() -> None:
    col = _client().get_or_create_collection(_COLLECTION)
    for path in sorted(_KNOWLEDGE_DIR.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        chunks = [c.strip() for c in _read(path).split("\n\n") if c.strip()]
        col.upsert(
            ids=[f"{path.name}:{i}" for i, _ in enumerate(chunks)],
            documents=chunks,
        )


def retrieve(query: str, n: int = 5) -> str:
    col = _client().get_or_create_collection(_COLLECTION)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)


url = "https://a16z.fillout.com/t/2dqvGNMYi9us"


async def main() -> None:
    ingest()
    profile = retrieve("contact identity address work experience")

    task = f"""
Open {url} and fill every applicable field using the profile below (map labels
loosely — e.g. "Phone" = telephone):

{profile}

Rules:
- Prefer selects and radios that match the values above; otherwise choose the closest reasonable option.
- Try to answer all the questions; if unsure, make a reasonable guess.
- For longer fields, write a few sentences consistent with the profile.
- Do not upload real identity documents; skip file uploads requiring real files.
- Do not click Submit, Apply, Send, or any control that finalises the application.
- When everything reasonable is filled, finish with the done action and tell the user to review and submit manually.
"""

    llm = bu.ChatBrowserUse()
    browser_profile = bu.BrowserProfile(keep_alive=True, headless=False)
    agent = bu.Agent(task=task, llm=llm, browser_profile=browser_profile)
    await agent.run()
    await asyncio.to_thread(
        input,
        "Browser left open — review and submit in the window. Press Enter here to exit when finished. ",
    )


if __name__ == "__main__":
    asyncio.run(main())
