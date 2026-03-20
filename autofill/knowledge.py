"""Knowledge base: ingest files from knowledge/, build a local vector index, retrieve context."""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
INDEX_PATH = KNOWLEDGE_DIR / ".index.pkl"

_SKIP = {".gitkeep", ".index.pkl"}

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader  # type: ignore[import-untyped]

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        from docx import Document  # type: ignore[import-untyped]

        return "\n".join(p.text for p in Document(path).paragraphs)
    return path.read_text(errors="replace")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk(text: str, size: int = 400, overlap: int = 40) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    step = size - overlap
    for i in range(0, len(words), step):
        piece = " ".join(words[i : i + size])
        if piece:
            chunks.append(piece)
    return chunks


# ---------------------------------------------------------------------------
# Embedding (lazy singleton)
# ---------------------------------------------------------------------------

_embedder = None  # type: ignore[assignment]


def _get_embedder():  # type: ignore[return]
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding  # type: ignore[import-untyped]

        _embedder = TextEmbedding()  # downloads BAAI/bge-small-en-v1.5 on first use
    return _embedder


def _embed(texts: list[str]) -> np.ndarray:
    vecs = np.array(list(_get_embedder().embed(texts)), dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs /= np.where(norms == 0, 1.0, norms)
    return vecs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_index(force: bool = False) -> None:
    """Index all files in knowledge/ into a local pickle-backed vector store."""
    if INDEX_PATH.exists() and not force:
        return

    chunks: list[str] = []
    metas: list[dict[str, object]] = []

    for path in sorted(KNOWLEDGE_DIR.iterdir()):
        if path.is_dir() or path.name.startswith(".") or path.name in _SKIP:
            continue
        text = _parse_file(path)
        for i, chunk in enumerate(_chunk(text)):
            chunks.append(chunk)
            metas.append({"source": path.name, "chunk": i})

    if not chunks:
        print(
            "knowledge/ is empty — run onboarding first:\n"
            "  uv run python -m autofill.onboarding"
        )
        return

    print(f"Embedding {len(chunks)} chunks from {len({m['source'] for m in metas})} file(s)…")
    vectors = _embed(chunks)
    INDEX_PATH.write_bytes(pickle.dumps({"chunks": chunks, "metas": metas, "vectors": vectors}))
    print(f"Index saved to {INDEX_PATH}")


def retrieve(query: str, n: int = 10) -> str:
    """Return the top-n most relevant chunks as a single formatted string."""
    if not INDEX_PATH.exists():
        return ""

    data = pickle.loads(INDEX_PATH.read_bytes())
    q_vec = _embed([query])[0]
    scores: np.ndarray = data["vectors"] @ q_vec
    top_idx = np.argsort(scores)[::-1][: min(n, len(scores))]

    parts: list[str] = []
    for idx in top_idx:
        source = data["metas"][idx]["source"]
        parts.append(f"[{source}]\n{data['chunks'][idx]}")
    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    build_index(force=True)
