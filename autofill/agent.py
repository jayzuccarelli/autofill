"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

import asyncio
import hashlib
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


def _hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def ingest() -> None:
    col = _client().get_or_create_collection(_COLLECTION)

    # Build stored state: {filename: hash} and {filename: [ids]}
    stored = col.get(include=["metadatas"])
    stored_hashes: dict[str, str] = {}
    stored_ids: dict[str, list[str]] = {}
    for doc_id, meta in zip(stored["ids"], stored["metadatas"]):
        fname = doc_id.split(":")[0]
        stored_ids.setdefault(fname, []).append(doc_id)
        if meta and "hash" in meta and fname not in stored_hashes:
            stored_hashes[fname] = meta["hash"]

    current_files = {
        path.name: path
        for path in sorted(_KNOWLEDGE_DIR.iterdir())
        if not path.name.startswith(".") and path.is_file()
    }

    # Remove deleted files
    for fname in set(stored_hashes) - set(current_files):
        col.delete(ids=stored_ids[fname])

    # Add new or re-ingest modified files
    for fname, path in current_files.items():
        h = _hash(path)
        if stored_hashes.get(fname) == h:
            continue
        if fname in stored_ids:
            col.delete(ids=stored_ids[fname])
        chunks = [c.strip() for c in _read(path).split("\n\n") if c.strip()]
        if not chunks:
            continue
        col.upsert(
            ids=[f"{fname}:{i}" for i, _ in enumerate(chunks)],
            documents=chunks,
            metadatas=[{"hash": h}] * len(chunks),
        )


def retrieve(query: str, n: int = 5) -> str:
    col = _client().get_or_create_collection(_COLLECTION)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)


def _llm(provider: str) -> object:
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-opus-4-6")  # type: ignore[return-value]
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o")  # type: ignore[return-value]
    if provider == "browseruse":
        return bu.ChatBrowserUse()
    raise ValueError(f"Unknown provider '{provider}'. Choose: anthropic, openai, browseruse")


async def main(url: str, provider: str) -> None:
    ingest()
    profile = retrieve("contact identity address work experience")
    if not profile.strip():
        raise SystemExit(
            "No profile in the knowledge store. Add one or more files under knowledge/ "
            "(e.g. knowledge/profile.md — see README), run from the project root, then try again."
        )

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

    llm = _llm(provider)
    browser_profile = bu.BrowserProfile(keep_alive=True, headless=False)
    agent = bu.Agent(task=task, llm=llm, browser_profile=browser_profile)
    await agent.run()
    await asyncio.to_thread(
        input,
        "Browser left open — review and submit in the window. Press Enter here to exit when finished. ",
    )


def cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AI-powered form autofill")
    parser.add_argument("url", help="URL of the form to fill")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "browseruse"],
        default="browseruse",
        help="LLM provider to use (default: browseruse)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.url, args.provider))


if __name__ == "__main__":
    cli()
