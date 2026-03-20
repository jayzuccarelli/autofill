"""Local RAG: ingest files from knowledge/ and retrieve relevant chunks."""

from pathlib import Path

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


def ingest(knowledge_dir: Path = _KNOWLEDGE_DIR) -> None:
    """Index all files in knowledge_dir into ChromaDB."""
    col = _client().get_or_create_collection(_COLLECTION)
    for path in sorted(knowledge_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        chunks = [c.strip() for c in _read(path).split("\n\n") if c.strip()]
        col.upsert(
            ids=[f"{path.name}:{i}" for i, _ in enumerate(chunks)],
            documents=chunks,
        )


def retrieve(query: str, n: int = 5) -> str:
    """Return the top-n most relevant chunks for a query."""
    col = _client().get_or_create_collection(_COLLECTION)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)
