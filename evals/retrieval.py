"""Measure whether retrieval actually surfaces the facts a form asks for.

``retrieve()`` returns the only profile text the browser agent ever sees.  A
fact missing from that string cannot be filled in correctly no matter how good
the model is, so recall over it is the ceiling on the whole tool.

Every run rebuilds a real Chroma index from a fixture using the shipped
``ingest()``, then queries with the shipped ``cfg.retrieval_query``.  No API
key and no network are needed once Chroma's embedding model is cached.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from autofill import agent as agent_mod
from autofill.agent import cfg

from .cases import CASES, Case

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Why a fact was not in the retrieved context.
OK = "ok"
NOT_RANKED = "not_ranked"  # in a chunk, but that chunk lost the ranking
SPLIT = "split"  # in no single chunk; chunking cut it in half


@dataclass(frozen=True)
class Result:
    case: Case
    status: str


def _flatten(text: str) -> str:
    """Collapse whitespace so patterns ignore the source's hard line wraps."""
    return re.sub(r"\s+", " ", text)


def _index(fixture: str, root: Path) -> str:
    """Ingest one fixture into a throwaway Chroma index; return its raw text."""
    knowledge = root / "knowledge"
    knowledge.mkdir(parents=True, exist_ok=True)
    source = FIXTURE_DIR / f"{fixture}.md"
    shutil.copy(source, knowledge / "profile.md")

    object.__setattr__(cfg, "knowledge_dir", knowledge)
    object.__setattr__(cfg, "db_path", root / "db")
    agent_mod.ingest()
    return source.read_text()


def _classify(case: Case, context: str, chunks: list[str]) -> str:
    if re.search(case.pattern, _flatten(context)):
        return OK
    if any(re.search(case.pattern, _flatten(chunk)) for chunk in chunks):
        return NOT_RANKED
    return SPLIT


def run(fixture: str, ns: list[int]) -> dict[int, list[Result]]:
    """Score every case for *fixture* at each top-*n* in *ns*.

    Indexes once and re-queries, so sweeping *n* costs one ingest, not one
    per value.
    """
    cases = [case for case in CASES if case.fixture == fixture]
    if not cases:
        return {n: [] for n in ns}

    root = Path(tempfile.mkdtemp(prefix=f"autofill-eval-{fixture}-"))
    try:
        text = _index(fixture, root)
        chunks = agent_mod._chunk_text(text)
        scored: dict[int, list[Result]] = {}
        for n in ns:
            context = agent_mod.retrieve(cfg.retrieval_query, n=n)
            scored[n] = [
                Result(case, _classify(case, context, chunks)) for case in cases
            ]
        return scored
    finally:
        shutil.rmtree(root, ignore_errors=True)


def tally(results: list[Result]) -> Counter[str]:
    return Counter(result.status for result in results)


def recall(results: list[Result]) -> float:
    if not results:
        return 0.0
    return tally(results)[OK] / len(results)
