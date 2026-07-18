"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

import questionary
from dotenv import dotenv_values, load_dotenv
from rich.console import Console
from rich.live import Live
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from autofill.telemetry import init_sentry as _init_sentry
from autofill.telemetry import track as _capture

# browser_use and chromadb cost ~2.3s to import between them — most of the wait
# before the first prompt. Neither is needed to onboard, print help, or pick a
# provider, so they're imported at the point of use instead of on every startup.
if TYPE_CHECKING:
    import browser_use as bu
    import chromadb

# Env-var NAMES present at import — the user's shell environment, captured
# before cli() calls load_dotenv(). Lets onboarding tell an ambient key (e.g.
# ANTHROPIC_API_KEY exported for Claude) apart from one autofill itself wrote to
# .env, so it never silently adopts a key the user set for another tool.
_AMBIENT_ENV_KEYS = frozenset(os.environ)


@dataclass(frozen=True)
class Config:
    """Central configuration — paths, chunking params, model IDs, and timeouts."""

    # Paths
    knowledge_dir: Path = Path("knowledge")
    db_path: Path = Path("knowledge/.db")
    collection: str = "profile"
    profile_example: Path = Path("knowledge/profile.example.md")
    profile: Path = Path("knowledge/profile.md")
    env_file: Path = Path(".env")
    # Persistent browser profile — lives in $HOME (not cwd) so logins survive
    # across runs. "chrome" must NOT appear in the path or browser-use copies it
    # to a throwaway temp dir (see BrowserProfile._copy_profile) and persistence
    # silently breaks.
    browser_profile_dir: Path = Path.home() / ".autofill" / "browser-profile"
    # One-time cookie seed imported from the user's Chrome at setup. Loaded into
    # the browser on the next run (via storage_state), then deleted — afterwards
    # the persistent profile above is the single source of truth.
    seed_state_file: Path = Path.home() / ".autofill" / "seed-cookies.json"

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200
    upsert_batch: int = 50
    max_text_chars: int = 100_000

    # Retrieval — natural-language query so Chroma's embedding model
    # surfaces a wide cross-section of the profile, not just contact basics.
    retrieval_query: str = (
        "personal contact information, home address, education, work history, "
        "skills, languages, work authorization and visa status, salary "
        "expectations, demographics, references, certifications, projects"
    )
    retrieval_n: int = 5

    # Models — bump when upgrading provider SDKs. Override any of these at
    # runtime without editing code via AUTOFILL_ANTHROPIC_MODEL /
    # AUTOFILL_OPENAI_MODEL / AUTOFILL_OLLAMA_MODEL.
    # Sonnet 5 reliably emits browser-use's structured tool calls; Haiku 4.5
    # drops the required `action` on real forms, so it can't be the default.
    anthropic_model: str = "claude-sonnet-5"             # Anthropic Sonnet 5
    # One-shot fallback: auto-engages on a provider/rate-limit error so a bad
    # step recovers instead of hard-crashing "no fallback_llm configured".
    anthropic_fallback_model: str = "claude-opus-4-8"    # Anthropic Opus 4.8
    openai_model: str = "gpt-4o-mini"                    # OpenAI GPT-4o mini
    # Ollama default — 14B is the smallest size that fills real forms reliably.
    # Override via AUTOFILL_OLLAMA_MODEL env var or the onboarding prompt.
    ollama_model: str = "qwen2.5:14b"

    # Corrections
    corrections_file: Path = Path("knowledge/.corrections.jsonl")

    # Agent
    agent_timeout: int = 600  # seconds before agent.run() is cancelled
    agent_max_steps: int = 30  # LLM turns; one turn = read DOM + 1-3 actions


cfg = Config()

# Attachable document types (not .md/.txt — those are indexed as text, not bytes).
_ATTACHABLE_SUFFIXES = frozenset({".pdf", ".doc", ".docx"})
# Legacy .doc (1997-2003 OLE binary) has no viable pure-Python parser; we skip
# it during ingestion but still allow it as an upload attachment.
_UNPARSEABLE_SUFFIXES = frozenset({".doc"})

# Provider registry. "env" is the API key env var, or None for providers that
# don't take one (e.g. Ollama, which talks to a local server). "label" and
# "url" are always strings — using Any to keep call sites typed as `str`.
# "shared" marks an env var other tools also read, so finding one in the shell
# says nothing about what autofill should use. BROWSER_USE_API_KEY is ours alone.
_PROVIDERS: dict[str, dict[str, Any]] = {
    "browseruse": {
        "env": "BROWSER_USE_API_KEY",
        "label": "Browser Use (recommended)",
        "url": "https://cloud.browser-use.com/settings?tab=api-keys&new=1",
        "shared": False,
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "label": "Anthropic",
        "url": "https://console.anthropic.com/settings/keys",
        "shared": True,
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "label": "OpenAI",
        "url": "https://platform.openai.com/api-keys",
        "shared": True,
    },
    "ollama": {
        "env": None,
        "label": "Ollama (local)",
        "url": "https://ollama.com/download",
        "shared": False,
    },
}

_LOG_RETENTION = 10  # Keep this many most-recent per-run log files (npm-style).


def _log_dir() -> Path:
    """Per-OS state dir for autofill log files.

    Linux/other: ``$XDG_STATE_HOME/autofill/logs`` (default ``~/.local/state/...``).
    macOS: ``~/Library/Logs/autofill``.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "autofill"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "autofill" / "logs"


def _setup_logging() -> Path | None:
    """Attach a per-run file handler to the root logger; return its path.

    Captures whatever browser-use (``Agent``, ``prompts``, ``BrowserSession``,
    ``tools``) writes via the stdlib ``logging`` module — same lines the user
    sees on the terminal. Opt out with ``AUTOFILL_LOG=0``. Returns ``None``
    when disabled or if the log directory can't be created.
    """
    if os.environ.get("AUTOFILL_LOG", "1").strip() == "0":
        return None
    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    path = log_dir / f"{timestamp}.log"
    try:
        handler = logging.FileHandler(path, mode="w", encoding="utf-8")
    except Exception:
        return None
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    # Root defaults to WARNING; gate must be at INFO or our handler sees nothing.
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Prune older runs, keep last N.
    try:
        runs = sorted(
            log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for old in runs[_LOG_RETENTION:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass
    return path


def _field_count_bucket(n: int) -> str:
    """Bucket field counts for telemetry — never sends a raw integer."""
    if n <= 5:
        return "0-5"
    if n <= 15:
        return "6-15"
    if n <= 30:
        return "16-30"
    if n <= 60:
        return "31-60"
    return "60+"


_ACCENT = "#7851A9"
try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("autofill")
except Exception:
    _VERSION = "unknown"

_THEME = Theme(
    {"accent": _ACCENT, "success": "green", "info": "dim", "err": "bold red"}
)
console = Console(theme=_THEME)


# ---------------------------------------------------------------------------

_Q_STYLE = questionary.Style(
    [
        ("qmark", f"fg:{_ACCENT} bold"),
        ("question", "bold"),
        ("answer", f"fg:{_ACCENT} bold"),
        ("pointer", f"fg:{_ACCENT} bold"),
        ("highlighted", f"fg:{_ACCENT} bold"),
        ("selected", f"fg:{_ACCENT}"),
    ]
)

# Phil the octopus, rendered with unicode half-blocks.  Palette mirrors phil.svg.
_B = "rgb(121,82,179)"    # body main
_L = "rgb(162,132,185)"   # highlight / underside / tentacle tips
_D = "rgb(42,24,69)"      # glasses frame
_W = "white"
_P = "rgb(26,26,46)"      # pupil

# Pixel-art markup below; wrapping would break the rendered layout.
_LOGO_LINES = [
    f" [{_L}]▄[/][{_B}]▄[/][{_L} on {_B}]▀[/][{_B}]████████████[/][{_L} on {_B}]▀[/][{_B}]▄[/][{_L}]▄[/] ",  # noqa: E501
    f" [{_B}]███[/][{_D}]█[/][{_D} on {_W}]▀▀▀[/][{_D}]█[/][{_B}]██[/][{_D}]█[/][{_D} on {_W}]▀▀▀[/][{_D}]█[/][{_B}]███[/] ",  # noqa: E501
    f" [{_B}]███[/][{_D}]█[/][{_W}]█[/][{_P} on {_W}]▀[/][{_W}]█[/][{_D}]█[/][{_D} on {_B}]▀▀[/][{_D}]█[/][{_W}]█[/][{_P} on {_W}]▀[/][{_W}]█[/][{_D}]█[/][{_B}]███[/] ",  # noqa: E501
    f" [{_B} on {_L}]▀[/][{_B}]██[/][{_D} on {_B}]▀▀▀▀▀[/][{_B}]██[/][{_D} on {_B}]▀▀▀▀▀[/][{_B}]██[/][{_B} on {_L}]▀[/] ",  # noqa: E501
    f"  [{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/][{_L}]▀▀[/][{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/][{_L}]▀[/][{_L} on {_B}]▀[/]  ",  # noqa: E501
    f"[{_B}]▄▀▄▀▄▀▄▀[/]    [{_B}]▀▄▀▄▀▄▀▄[/]",
    f"[{_L}]▀[/] [{_L}]▀[/] [{_L}]▀[/] [{_L}]▀[/]      [{_L}]▀[/] [{_L}]▀[/] [{_L}]▀[/] [{_L}]▀[/]",  # noqa: E501
]

# Blink frame: eyes closed (dark fill where the white eyeballs sit).
_LOGO_LINES_BLINK = list(_LOGO_LINES)
_LOGO_LINES_BLINK[1] = (
    f" [{_B}]███[/][{_D}]█▄▄▄█[/][{_B}]██[/][{_D}]█▄▄▄█[/][{_B}]███[/] "
)
_LOGO_LINES_BLINK[2] = (
    f" [{_B}]███[/][{_D}]█████[/][{_D} on {_B}]▀▀[/][{_D}]█████[/][{_B}]███[/] "
)

# Wave frame: tentacles swap direction.
_LOGO_LINES_WAVE = list(_LOGO_LINES)
_LOGO_LINES_WAVE[5] = f"[{_B}]▀▄▀▄▀▄▀▄[/]    [{_B}]▄▀▄▀▄▀▄▀[/]"


def _logo_text(lines: list[str]) -> Text:
    logo = Text()
    for i, line in enumerate(lines):
        if i:
            logo.append("\n")
        logo.append_text(Text.from_markup(line))
    return logo


def _banner_from(lines: list[str], info_lines: tuple[str, ...]) -> Table:
    info = Text()
    for i, line in enumerate(info_lines):
        if i:
            info.append("\n")
        info.append_text(Text.from_markup(line))

    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_row(_logo_text(lines), info)
    return table


def _banner(*info_lines: str) -> Table:
    """Build a Claude-Code-style banner: pixel-art logo left, info text right."""
    return _banner_from(_LOGO_LINES, info_lines)


def _play_intro(*info_lines: str) -> None:
    """Briefly animate Phil before settling on the static banner."""
    static = _banner(*info_lines)
    if not console.is_terminal:
        console.print(static)
        return
    frames = [_LOGO_LINES_BLINK, _LOGO_LINES, _LOGO_LINES_WAVE, _LOGO_LINES]
    with Live(static, console=console, refresh_per_second=15, transient=False) as live:
        time.sleep(0.18)
        for frame in frames:
            live.update(_banner_from(frame, info_lines))
            time.sleep(0.14)


def _detect_provider() -> str | None:
    """Return the active provider, based on env vars.

    Cloud providers are *inferred* from which key is present, in _PROVIDERS
    order: Browser Use, Anthropic, OpenAI. An ambient key (a shared var like
    ANTHROPIC_API_KEY exported in the shell for another tool) is skipped — the
    user must pick it explicitly. Ollama takes no key, so it is never inferred;
    only an explicit ``AUTOFILL_PROVIDER=ollama`` selects it.

    ``AUTOFILL_PROVIDER`` overrides all of it, but setup writes it only when
    inference can't reach the user's choice — a stale one silently hijacks every
    later run (JAY-93).
    """
    saved = os.environ.get("AUTOFILL_PROVIDER", "").strip().lower()
    if saved in _PROVIDERS:
        env = _PROVIDERS[saved].get("env")
        if env is None or os.environ.get(env):
            return saved
    return _infer_provider()


def _infer_provider() -> str | None:
    """The provider the present keys imply, ignoring any AUTOFILL_PROVIDER.

    Separate from _detect_provider() so setup can ask "would the keys alone reach
    this choice?" without the answer being coloured by the pointer it's deciding
    whether to write.
    """
    for name, info in _PROVIDERS.items():
        env = info.get("env")
        if env and os.environ.get(env) and not _is_ambient_key(name):
            return name
    return None


def _has_any_api_key() -> bool:
    """Return True if a provider is configured (API key present, or Ollama selected)."""
    return _detect_provider() is not None


def _provider_ready(provider: str) -> bool:
    """True if `provider` could run right now: its key is present, or it needs none.

    Deliberately ignores the ambient check. That guard exists because a shell key
    alone doesn't say which provider the user wants — but naming the provider
    outright (``--provider anthropic``) is exactly the explicit choice it asks
    for, so the key should be honoured rather than the flag ignored.
    """
    if provider not in _PROVIDERS:
        return False
    env = _PROVIDERS[provider].get("env")
    return env is None or bool(os.environ.get(env))


def _key_fingerprint(provider: str) -> str:
    """Return a short masked tail like ``(…a4f2)`` so the active key is visible.

    Disambiguates when the same provider has different keys in the shell vs ``.env``.
    Returns ``""`` for key-less providers (Ollama) or when the key is missing/too short.
    """
    env = _PROVIDERS.get(provider, {}).get("env")
    if not env:
        return ""
    key = (os.environ.get(env) or "").strip()
    if len(key) < 4:
        return ""
    return f"(…{key[-4:]})"


def _env_file_keys() -> frozenset[str]:
    """Names with a non-empty value in autofill's own .env — explicit config.

    Blank lines like ``ANTHROPIC_API_KEY=`` are how people disable a key while
    keeping it around, so they must not count as configuring it: dotenv_values
    still reports the name, and treating that as explicit would hand the ambient
    guard back the very key the user just switched off.
    """
    if not cfg.env_file.exists():
        return frozenset()
    return frozenset(k for k, v in dotenv_values(cfg.env_file).items() if v)


def _is_ambient_key(provider: str) -> bool:
    """True if the provider's key was in the shell and might belong to another tool.

    Only *shared* vars can be ambient: ANTHROPIC_API_KEY is read by Claude and
    plenty else, so exporting one says nothing about autofill. BROWSER_USE_API_KEY
    is autofill's alone — wherever it came from, it was set for us. A key in
    autofill's own .env is explicit config, never ambient.
    """
    info = _PROVIDERS.get(provider, {})
    env = info.get("env")
    if not env or not info.get("shared"):
        return False
    return env in _AMBIENT_ENV_KEYS and env not in _env_file_keys()


def _client() -> chromadb.ClientAPI:
    """Return a persistent Chroma client, creating the DB directory if needed."""
    import chromadb
    cfg.db_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(cfg.db_path))


def _read(path: Path) -> str:
    """Read a file's text content, truncating to ``cfg.max_text_chars``."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber
        parts: list[str] = []
        total = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                remaining = cfg.max_text_chars - total
                if len(text) >= remaining:
                    parts.append(text[:remaining])
                    break
                parts.append(text)
                total += len(text)
        return "\n".join(parts)
    if suffix == ".docx":
        import docx2txt
        try:
            text = docx2txt.process(str(path)) or ""
        except Exception as exc:
            console.print(
                f"[yellow]Warning:[/] failed to parse [bold]{path.name}[/] "
                f"as .docx ({exc.__class__.__name__}); skipping."
            )
            return ""
        return text[:cfg.max_text_chars]
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:cfg.max_text_chars]


def _hash(path: Path) -> str:
    """Return the MD5 hex digest of a file's raw bytes."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def _chunk_text(text: str) -> list[str]:
    """Split *text* into chunks of ~``cfg.chunk_size`` chars.

    Tries to break on paragraph, line, sentence, then word boundaries
    (in that order) so chunks stay semantically coherent.  Consecutive
    chunks overlap by ``cfg.chunk_overlap`` characters.
    """
    separators = ["\n\n", "\n", ". ", " "]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + cfg.chunk_size, len(text))
        if end < len(text):
            for sep in separators:
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # Always advance: without this, an early separator can make
        # end - chunk_overlap <= start and the loop never terminates.
        start = max(start + 1, end - cfg.chunk_overlap)
    return chunks


def ingest() -> None:
    """Index all non-hidden files in the knowledge directory into Chroma."""
    col = _client().get_or_create_collection(cfg.collection)

    # Build stored state: {filename: hash} and {filename: [ids]}
    stored = col.get(include=["metadatas"])
    stored_hashes: dict[str, str] = {}
    stored_ids: dict[str, list[str]] = {}
    for doc_id, meta in zip(stored["ids"] or [], stored["metadatas"] or []):
        fname = doc_id.split(":")[0]
        stored_ids.setdefault(fname, []).append(doc_id)
        if meta and "hash" in meta and fname not in stored_hashes:
            stored_hashes[fname] = str(meta["hash"])

    visible_files = [
        path for path in sorted(cfg.knowledge_dir.iterdir())
        if not path.name.startswith(".")
        and path.is_file()
        and path.name != "profile.example.md"
        and path.name != cfg.corrections_file.name
    ]
    for path in visible_files:
        if path.suffix.lower() in _UNPARSEABLE_SUFFIXES:
            console.print(
                f"[yellow]Warning:[/] [bold]{path.name}[/] is a legacy .doc file"
                " — its content won't be indexed. Resave as .docx or PDF to make"
                " it searchable."
            )
    current_files = {
        path.name: path
        for path in visible_files
        if path.suffix.lower() not in _UNPARSEABLE_SUFFIXES
    }

    # Remove deleted files (covers rows even if they lacked a hash metadata).
    for fname in set(stored_ids) - set(current_files):
        col.delete(ids=stored_ids[fname])

    # Add new or re-ingest modified files
    hashes = {f: _hash(p) for f, p in current_files.items()}
    to_ingest = {
        f: p for f, p in current_files.items() if stored_hashes.get(f) != hashes[f]
    }
    if not to_ingest:
        return

    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("[accent]{task.description}[/]"),
        BarColumn(complete_style="accent"),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Indexing", total=len(to_ingest))
        for fname, path in to_ingest.items():
            progress.update(task_id, description=f"Indexing [bold]{fname}[/]")
            h = hashes[fname]
            chunks = _chunk_text(_read(path))
            if not chunks:
                console.print(
                    f"[yellow]Warning:[/] [bold]{fname}[/] produced no text "
                    "chunks — skipping."
                )
                progress.advance(task_id)
                continue
            if fname in stored_ids:
                col.delete(ids=stored_ids[fname])
            for i in range(0, len(chunks), cfg.upsert_batch):
                batch = chunks[i : i + cfg.upsert_batch]
                col.upsert(
                    ids=[f"{fname}:{i + j}" for j in range(len(batch))],
                    documents=batch,
                    metadatas=[{"hash": h}] * len(batch),
                )
            progress.advance(task_id)

    _capture("knowledge_ingested", {"file_count": len(to_ingest)})


def retrieve(query: str, n: int = cfg.retrieval_n) -> str:
    """Query Chroma and return the top-*n* chunks joined by blank lines."""
    col = _client().get_or_create_collection(cfg.collection)
    results = col.query(query_texts=[query], n_results=n)
    docs_lists = results["documents"] or [[]]
    docs: list[str] = docs_lists[0]
    return "\n\n".join(docs)


def _attachment_paths() -> list[str]:
    """Paths browser-use may pass to ``<input type="file">``.

    Includes every PDF/DOC/DOCX in ``knowledge/`` (same visibility rules as
    ``ingest``). There is **no** basename pattern or "resume" substring — only
    the suffix allowlist. Which path belongs to which upload field is decided
    by the agent from **form labels**, not from matching strings in filenames.
    """
    if not cfg.knowledge_dir.is_dir():
        return []
    paths: list[Path] = []
    for path in sorted(cfg.knowledge_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.name == "profile.example.md":
            continue
        if path.suffix.lower() in _ATTACHABLE_SUFFIXES:
            paths.append(path.resolve())
    return [str(p) for p in paths]


def _llm(provider: str) -> Any:
    """Instantiate the chat model for the given *provider* name."""
    if provider == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic
        model = os.environ.get("AUTOFILL_ANTHROPIC_MODEL") or cfg.anthropic_model
        return ChatAnthropic(model=model)
    if provider == "openai":
        from browser_use.llm.openai.chat import ChatOpenAI
        model = os.environ.get("AUTOFILL_OPENAI_MODEL") or cfg.openai_model
        return ChatOpenAI(model=model)
    if provider == "browseruse":
        from browser_use import ChatBrowserUse
        return ChatBrowserUse()
    if provider == "ollama":
        from browser_use.llm.ollama.chat import ChatOllama
        model = os.environ.get("AUTOFILL_OLLAMA_MODEL") or cfg.ollama_model
        # host=None lets the ollama SDK use OLLAMA_HOST or default to localhost.
        return ChatOllama(model=model)
    raise ValueError(
        f"Unknown provider '{provider}'. Choose: anthropic, openai, browseruse, ollama"
    )


# ---------------------------------------------------------------------------
# Field capture: a full-DOM CDP collector for the baseline snapshot, plus an
# event-driven listener that pushes each user edit as it happens. Both embed the
# shared JS helpers below so the baseline and the live tracker key a field the
# same way.

# JS helpers embedded in _COLLECT_JS:
#   SEL      — form controls + ARIA widgets + contenteditable we track
#   labelFor — human label: aria-label → aria-labelledby → <label for> →
#              wrapping <label> → placeholder
#   keyFor   — stable identity: autocomplete token → name → id → label. Survives
#              re-renders that reorder fields (unlike a positional label suffix).
#   valueOf  — current value: .checked for checkboxes, the selected option for
#              native radio groups (which collapse to one key) and custom
#              dropdowns, textContent for contenteditable, else .value
_FIELD_JS_HELPERS = r"""
const SEL = 'input,textarea,select,[role="textbox"],[role="combobox"],' +
  '[role="listbox"],[role="spinbutton"],[role="searchbox"],[role="radio"],' +
  '[role="checkbox"],[role="switch"],[contenteditable="true"]';
const labelFor = (el) => {
  const al = el.getAttribute('aria-label'); if (al) return al.trim();
  const lb = el.getAttribute('aria-labelledby');
  if (lb) {
    const t = lb.split(/\s+/).map(function(id){
      const n = document.getElementById(id); return n ? n.textContent : '';
    }).join(' ').trim();
    if (t) return t;
  }
  if (el.id) {
    try {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l) return l.textContent.trim();
    } catch (e) {}
  }
  const anc = el.closest ? el.closest('label') : null;
  if (anc) return anc.textContent.trim();
  return (el.getAttribute('placeholder') || '').trim();
};
const keyFor = (el, label) => {
  const ac = el.getAttribute('autocomplete');
  if (ac && ac !== 'off' && ac !== 'on') return ac;
  return el.getAttribute('name') || el.id || label;
};
const valueOf = (el) => {
  const role = (el.getAttribute('role') || '').toLowerCase();
  if (el.matches && el.matches('input[type="checkbox"]')) {
    return el.checked ? 'true' : 'false';
  }
  if (el.matches && el.matches('input[type="radio"]')) {
    // A native radio group shares one name, so keyFor collapses it to a single
    // key. Report which option is selected (its value/label), not this element's
    // checked bit — a bare true/false can't tell the agent which option to pick.
    let sel = el.checked ? el : null;
    if (el.name) {
      const scope = el.form || el.getRootNode();
      try {
        sel = scope.querySelector('input[type="radio"][name="' +
          CSS.escape(el.name) + '"]:checked') || sel;
      } catch (e) {}
    }
    return sel ? (sel.value || labelFor(sel) || 'on') : '';
  }
  if (role === 'radio' || role === 'checkbox' || role === 'switch') {
    return el.getAttribute('aria-checked') || 'false';
  }
  if (el.tagName === 'SELECT') return el.value || '';
  if (el.isContentEditable) return (el.textContent || '').trim();
  if (role === 'combobox' || role === 'listbox') {
    if (el.value) return el.value;
    const s = el.querySelector ?
      el.querySelector('[aria-selected="true"]') : null;
    return s ? s.textContent.trim() : '';
  }
  return el.value != null ? el.value : '';
};
"""

# Walk the whole DOM (light + open shadow roots + same-origin iframes) and return
# JSON [{key,label,value}]. Bypasses browser-use's viewport-filtered selector_map,
# which only surfaced fields the agent could act on (Greenhouse reported 1 of N).
# Cross-origin iframes are skipped — job-application forms are same-origin.
_COLLECT_JS = "(() => {" + _FIELD_JS_HELPERS + r"""
const out = [], seen = new Set();
const walk = (root) => {
  let nodes; try { nodes = root.querySelectorAll(SEL); } catch (e) { return; }
  for (const el of nodes) {
    if (seen.has(el) || el.disabled || el.type === 'hidden' ||
        el.type === 'password') continue;
    seen.add(el);
    const label = labelFor(el);
    out.push({ key: keyFor(el, label), label: label, value: valueOf(el) });
  }
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) walk(el.shadowRoot);
  }
  for (const f of root.querySelectorAll('iframe')) {
    try { if (f.contentDocument) walk(f.contentDocument); } catch (e) {}
  }
};
walk(document);
return JSON.stringify(out);
})()"""


async def _snapshot_fields(session) -> dict:
    """Return ``{key: {"label", "value"}}`` for every field in the DOM.

    One CDP ``Runtime.evaluate`` runs :data:`_COLLECT_JS`, which walks the whole
    document (not browser-use's viewport-filtered selector_map), so below-the-fold
    and shadow-DOM fields are captured too. Fields are keyed by stable identity
    (autocomplete/name/id), not a positional label, so a saved correction still
    lines up after the form re-renders. Sensitive fields are dropped.
    """
    try:
        cdp_session = await session.get_or_create_cdp_session(focus=False)
        result = await cdp_session.cdp_client.send.Runtime.evaluate(
            {"expression": _COLLECT_JS, "returnByValue": True},
            session_id=cdp_session.session_id,
        )
        raw = (result.get("result") or {}).get("value") or "[]"
        fields = json.loads(raw)
    except Exception:
        return {}

    out: dict[str, dict] = {}
    for f in fields:
        key = (f.get("key") or "").strip()
        label = (f.get("label") or "").strip()
        if (not key or _SENSITIVE_FIELD_RE.search(key)
                or _SENSITIVE_FIELD_RE.search(label)):
            continue
        # Same-key collisions (e.g. two unlabelled fields sharing a name) collapse
        # to the last occurrence — semantic keys make this rare, and it keeps the
        # baseline consistent with the live listener, which can't know positions.
        out[key] = {"label": label or key, "value": f.get("value", "")}
    return out


def _diff_corrections(agent_snapshot: dict, user_snapshot: dict) -> dict:
    """Diff the agent's baseline against the user's final field values.

    Both snapshots are ``{key: {"label", "value"}}``. Keeps genuine changes and
    deletions (user cleared an agent-filled value — a "don't fill this" signal),
    and drops no-ops where both sides are empty. Returns
    ``{key: {"label", "agent", "user"}}``.
    """
    corrections: dict[str, dict] = {}
    for key, u in user_snapshot.items():
        a_val = agent_snapshot.get(key, {}).get("value", "")
        u_val = u.get("value", "")
        if a_val != u_val and (u_val or a_val):
            corrections[key] = {
                "label": u.get("label", key),
                "agent": a_val,
                "user": u_val,
            }
    return corrections


async def _watch_fields(session, agent_snapshot: dict, url: str) -> dict:
    """Let the user edit the form, then diff the final DOM and persist corrections.

    *agent_snapshot* is the baseline the caller took right after the agent finished.
    We block on a single Enter prompt while the user reviews and edits in the
    browser, then re-read the whole DOM and diff. Reading the final DOM — rather
    than tracking edit events — is what catches custom dropdowns (Airtable,
    react-select) that fire no ``change``/``focusout``. The re-read and save run in
    a ``finally`` so Ctrl-C or a normal Enter both flush; a dead browser snapshots
    to ``{}`` and simply yields no corrections. Returns the corrections dict.
    """
    corrections: dict = {}
    try:
        # to_thread keeps the blocking prompt off the running event loop.
        await asyncio.to_thread(
            _ask,
            "Review and edit the form in the browser, then press Enter here when done…",
        )
    finally:
        user_snapshot = await _snapshot_fields(session)
        corrections = _diff_corrections(agent_snapshot, user_snapshot)
        if corrections:
            _save_corrections(url, corrections)
    return corrections


def _load_corrections(url: str) -> str:
    """Return saved corrections for this domain, formatted for the task prompt."""
    if not cfg.corrections_file.exists():
        return ""
    domain = urlparse(url).netloc
    entries = []
    with open(cfg.corrections_file, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("domain") == domain:
                    entries.append(entry)
            except Exception:
                continue
    if not entries:
        return ""
    # Deduplicate: latest correction per field wins, capped to last 5 sessions.
    merged: dict[str, dict] = {}
    for entry in entries[-5:]:
        for field, change in entry["corrections"].items():
            merged[field] = change
    lines = [f"Previously corrected fields on {domain}:"]
    for field, change in merged.items():
        # New entries carry a display label; old ones keyed by label fall back to it.
        label = change.get("label", field)
        user_val = change.get("user", "")
        if user_val:
            agent_val = change.get("agent", "")
            lines.append(f"- {label}: use '{user_val}' (not '{agent_val}')")
        else:
            lines.append(
                f"- {label}: leave BLANK — the user cleared this; do NOT fill it"
            )
    return "\n".join(lines)


# Lookarounds (not \b) so '_' acts as a separator — `\w` includes underscore,
# which would otherwise let `password_field` and `auth_token` slip through.
_SENSITIVE_FIELD_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(password|passcode|otp|pin|2fa|ssn|social.?sec(?:urity)?|cvv|cvc"
    r"|card.?num(?:ber)?|expir|exp_|secret|token|auth|passport|birth|dob"
    r"|bank|routing|account.?num(?:ber)?)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _save_corrections(url: str, corrections: dict) -> None:
    """Append field corrections to the corrections log.

    Sensitive fields (passwords, OTP, SSN, CVV, etc.) are stripped before
    writing so they are never persisted or later injected into an LLM prompt.
    """
    def _label(v: object) -> str:
        if isinstance(v, dict):
            lab = cast("dict[str, object]", v).get("label", "")
            return lab if isinstance(lab, str) else ""
        return ""

    safe = {
        k: v
        for k, v in corrections.items()
        if not _SENSITIVE_FIELD_RE.search(k)
        and not _SENSITIVE_FIELD_RE.search(_label(v))
    }
    if not safe:
        return
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "url": url,
        "domain": urlparse(url).netloc,
        "corrections": safe,
    }
    cfg.corrections_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.corrections_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _force_input_clear(agent: bu.Agent) -> None:
    """Force the LLM-controlled `clear` flag on `input_text` to True.

    The action's schema exposes `clear=False` ("append") to the model, which
    it occasionally picks to add a second profile value (e.g. GitHub) into
    an already-filled field (e.g. LinkedIn). The library's auto-retry that
    fixes accidental concatenation is gated on clear=True, so the append
    path slips past it.
    """
    actions = agent.tools.registry.registry.actions
    action = actions.get("input")
    if action is None:
        return
    original = action.function

    async def _input_with_forced_clear(params, **kwargs):
        params.clear = True
        return await original(params=params, **kwargs)

    action.function = _input_with_forced_clear


def _cookiejar_to_storage_state(jar) -> dict:
    """Convert a cookielib-style jar to a Playwright storage_state dict.

    Mirrors the shape browser-use's StorageStateWatchdog loads (see
    ``export_storage_state``): a ``cookies`` list with name/value/domain/path/
    expires/httpOnly/secure/sameSite, plus an empty ``origins`` list. Session
    cookies (no expiry) get ``expires: -1``, which the loader normalises.
    """
    cookies = []
    for c in jar:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "expires": float(c.expires) if c.expires else -1,
            "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")),
            "secure": bool(c.secure),
            # cookielib doesn't expose SameSite; "Lax" is the browser default.
            "sameSite": "Lax",
        })
    return {"cookies": cookies, "origins": []}


def _import_chrome_cookies() -> dict | None:
    """Read + decrypt the user's Chrome cookies into a storage_state dict.

    Best-effort: returns None if ``browser_cookie3`` is missing, Chrome can't
    be found, or the cookie store is locked/undecryptable. Callers fall back to
    the manual sign-in flow in that case.
    """
    try:
        import browser_cookie3
    except ImportError:
        return None
    try:
        jar = browser_cookie3.chrome()
    except Exception:
        return None
    state = _cookiejar_to_storage_state(jar)
    return state if state["cookies"] else None


async def main(url: str, provider: str, log_path: Path | None = None) -> None:
    """Build the task prompt and run the browser agent (ingest already ran in cli)."""
    profile = retrieve(cfg.retrieval_query)
    if not profile.strip():
        raise SystemExit(
            "No profile in the knowledge store. Add one or more files under"
            " knowledge/ (e.g. knowledge/profile.md — see README), run from the"
            " project root, then try again."
        )
    if log_path is not None:
        console.print(f"[dim]Logs: {log_path}[/]")

    attachments = _attachment_paths()
    if attachments:
        _capture("file_attachments_found", {"attachment_count": len(attachments)})
        upload_rule = (
            "- For each file upload, read the field label on the page; choose"
            " one path from this list that fits that label (CV vs cover letter"
            f" vs other document): {attachments}.\n"
            "- Do not upload passport/license/ID scans unless required; skip if"
            " unsure."
        )
    else:
        upload_rule = (
            "- Do not upload real identity documents; skip file uploads"
            " requiring real files."
        )

    prior_corrections = _load_corrections(url)
    corrections_section = f"\n{prior_corrections}\n" if prior_corrections else ""

    task = f"""
Open {url} and fill every applicable field using the profile below (map labels
loosely — e.g. "Phone" = telephone):

{profile}
{corrections_section}
Rules:
- Prefer selects and radios that match the values above; otherwise choose the
  closest reasonable option.
- Try to answer all the questions; if unsure, make a reasonable guess.
- For longer fields, write a few sentences consistent with the profile.
{upload_rule}
- Multi-step forms: clicking "Next", "Continue", "Save and continue", or
  similar between-step buttons IS allowed — that's how you reach the next
  page of fields.
- What is FORBIDDEN is the FINAL action that submits the application:
  buttons like "Submit", "Submit application", "Apply", "Send application",
  "Finish", or anything similar that finalises and sends the form. When you
  reach that final button, STOP and finish with the done action.
- If the page shows a login form, sign-in/sign-up wall, or CAPTCHA, do NOT
  type credentials or solve it yourself. Stop immediately with the done action
  and make your message start with the exact token LOGIN_REQUIRED followed by
  a short note on what's needed (e.g. "LOGIN_REQUIRED: Workday account sign-in").
  The user will sign in manually and you'll resume on the form afterwards.
- When everything reasonable is filled, finish with the done action and tell
  the user to review and submit manually.
"""

    llm = _llm(provider)
    # Persistent user-data dir: the user signs into Workday/Greenhouse/etc. once,
    # the cookies live here, and every later run is already authenticated.
    cfg.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    # One-time seed: if Chrome cookies were imported at setup, load them on this
    # run (storage_state) so the user starts already signed in. They get baked
    # into the persistent profile, so we delete the seed afterwards (in finally).
    seed_state = str(cfg.seed_state_file) if cfg.seed_state_file.exists() else None
    if seed_state:
        _capture("chrome_cookies_seeding")
    from browser_use import Agent, BrowserProfile
    browser_profile = BrowserProfile(
        keep_alive=True,
        headless=False,
        user_data_dir=str(cfg.browser_profile_dir),
        storage_state=seed_state,
    )

    # Step-level progress so users have proof of life during long runs.
    # We can't predict total duration; show the live counter and elapsed time.
    run_start = time.monotonic()
    last_step = 0

    def _on_step(_state, _output, step_n: int) -> None:
        nonlocal last_step
        last_step = step_n
        elapsed = int(time.monotonic() - run_start)
        console.print(
            f"[dim]autofill › step {step_n}/{cfg.agent_max_steps}"
            f" · {elapsed}s elapsed[/]"
        )

    def _build_agent(session=None) -> Agent:
        """Construct the agent; reuse *session* (keeps the window) on resume."""
        kwargs: dict = dict(
            task=task,
            llm=llm,
            initial_actions=[{"navigate": {"url": url, "new_tab": False}}],
            available_file_paths=attachments or None,
            use_judge=False,
            # Cap actions per step so the model observes page state between input
            # batches instead of blind-batching fills (guards against values being
            # concatenated into the wrong field / double-filled).
            max_actions_per_step=3,
            register_new_step_callback=_on_step,
        )
        # A malformed step from a weak model — or a 429/5xx — otherwise
        # hard-crashes the run ("no fallback_llm configured"). Give the Anthropic
        # path a stronger model to switch to once, so a bad step recovers.
        if provider == "anthropic":
            from browser_use.llm.anthropic.chat import ChatAnthropic
            kwargs["fallback_llm"] = ChatAnthropic(model=cfg.anthropic_fallback_model)
        if session is not None:
            kwargs["browser_session"] = session
        else:
            kwargs["browser_profile"] = browser_profile
        agent = Agent(**kwargs)
        _force_input_clear(agent)
        return agent

    agent = _build_agent()
    _capture("form_fill_started", {
        "provider": provider,
        "has_attachments": bool(attachments),
        "has_prior_corrections": bool(prior_corrections),
    })
    timed_out = False
    # Pause-and-resume for login walls: the agent stops at a sign-in/sign-up
    # page (emitting LOGIN_REQUIRED), the user authenticates manually in the
    # open window, then we re-run on the same URL — now logged in. Cap at two
    # resumes so a misfiring detector can't loop forever.
    for attempt in range(3):
        try:
            async with asyncio.timeout(cfg.agent_timeout):
                await agent.run(max_steps=cfg.agent_max_steps)
        except TimeoutError:
            timed_out = True
            _capture("form_fill_timed_out", {
                "provider": provider,
                "timeout_seconds": cfg.agent_timeout,
                "last_step": last_step,
            })
            console.print(
                f"\n[err]Agent timed out after {cfg.agent_timeout}s.[/] "
                "The browser is still open — you can continue manually.",
            )
            break

        result = (agent.history.final_result() or "").strip()
        if result.startswith("LOGIN_REQUIRED") and attempt < 2:
            _capture("login_required", {"provider": provider, "attempt": attempt + 1})
            note = result[len("LOGIN_REQUIRED"):].lstrip(" :-").strip()
            console.print(
                f"\n[accent]Sign-in needed[/]"
                f"{' — ' + note if note else '.'}\n"
                "  Log in (or sign up) in the open browser window. Your session"
                " is saved here, so you'll only do this once per site.\n"
            )
            # main() runs under asyncio.run(); _ask() -> questionary .ask()
            # calls asyncio.run() internally, which raises inside a running
            # loop. Run it in a worker thread so prompt_toolkit gets its own.
            await asyncio.to_thread(
                _ask, "Press Enter once you're signed in and I'll continue…"
            )
            agent = _build_agent(session=agent.browser_session)
            continue
        break
    agent_run_elapsed = int(time.monotonic() - run_start)
    try:
        # Snapshot what the agent filled (full-DOM baseline), then re-snapshot
        # after the user edits to diff out their corrections.
        console.print(
            "\n[info]Capturing form state — review and edit in the browser.[/]"
        )
        agent_snapshot: dict = {}
        if agent.browser_session is not None:
            try:
                agent_snapshot = await _snapshot_fields(agent.browser_session)
                console.print(f"[dim]Tracking {len(agent_snapshot)} field(s)…[/]")
            except Exception as exc:
                console.print(f"[err]Warning:[/] Could not snapshot fields: {exc}")

        if not timed_out:
            _capture(
                "form_fill_completed",
                {
                    "provider": provider,
                    "has_attachments": bool(attachments),
                    "last_step": last_step,
                    "elapsed_seconds": agent_run_elapsed,
                    "field_count_bucket": _field_count_bucket(len(agent_snapshot)),
                },
            )

        corrections: dict = {}
        if agent.browser_session is not None:
            try:
                corrections = await _watch_fields(
                    agent.browser_session, agent_snapshot, url
                )
            except Exception as exc:
                console.print(f"[err]Warning:[/] Could not track field changes: {exc}")
        if corrections:
            _capture("corrections_saved", {"correction_count": len(corrections)})
            console.print(
                f"[info]Saved {len(corrections)} correction(s) for next time.[/]"
            )

        console.print(
            "[info]Tracking complete — browser stays open for you to submit.[/]"
        )
    finally:
        # Always tear down event buses and watchdogs (keeps the browser window open).
        if agent.browser_session is not None:
            try:
                await agent.browser_session.stop()
            except Exception:
                pass
        # One-time seed: it's baked into the persistent profile now, and
        # browser-use's storage watchdog keeps re-saving the live cookie jar
        # back to it — plus .json.bak/.json.tmp rotations. Drop all three,
        # unconditionally, so artifacts from a crashed earlier run get swept too.
        for _seed_artifact in (
            cfg.seed_state_file,
            cfg.seed_state_file.with_suffix(".json.bak"),
            cfg.seed_state_file.with_suffix(".json.tmp"),
        ):
            _seed_artifact.unlink(missing_ok=True)


def _has_profile_content() -> bool:
    """True if knowledge/ has a non-hidden, non-example file with real content."""
    if not cfg.knowledge_dir.is_dir():
        return False
    for p in sorted(cfg.knowledge_dir.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if p.name == "profile.example.md":
            continue
        if p.name == cfg.corrections_file.name:
            continue
        if p.stat().st_size > 0:
            return True
    return False


def _ask(prompt: str, default: str = "") -> str:
    """Show an interactive text prompt and return the stripped answer (or *default*).

    *default* is pre-loaded into the editable buffer (so ``autofill setup`` can
    show current values to tweak), and is also the fallback if the answer is
    blank. Uses ``unsafe_ask`` so Ctrl-C raises ``KeyboardInterrupt`` (caught in
    ``cli`` to abort the whole run) instead of being swallowed and silently
    skipping to the next question. ``EOFError`` (piped stdin) yields *default*.
    """
    try:
        val = questionary.text(prompt, default=default, style=_Q_STYLE).unsafe_ask()
    except EOFError:
        val = None
    return (val or "").strip() or default


def _parse_profile() -> dict[str, str]:
    """Parse knowledge/profile.md's ``- **Key:** value`` lines into a dict."""
    if not cfg.profile.is_file():
        return {}
    out: dict[str, str] = {}
    for line in cfg.profile.read_text().splitlines():
        m = re.match(r"-\s+\*\*(.+?):\*\*\s*(.*)", line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


# Canonical field order — used to append newly-set fields in edit mode.
_PROFILE_FIELDS = (
    "Full name", "Preferred Name", "Date of birth", "Email", "Phone",
    "Location", "LinkedIn", "X", "GitHub", "About",
)


def _apply_profile_edits(original: str, values: dict[str, str]) -> str:
    """Splice edited field *values* into *original*, preserving every other line.

    A recognized ``- **Key:** value`` line is updated in place (or dropped if the
    new value is blank); a newly-set field is appended after the last field line.
    Hand-added sections, paragraphs, and unknown bullets are kept as-is, so
    ``autofill setup`` never destroys content it doesn't understand.
    """
    seen: set[str] = set()
    out: list[str] = []
    last_field_idx = -1
    for line in original.splitlines():
        m = re.match(r"-\s+\*\*(.+?):\*\*", line)
        key = m.group(1).strip() if m else None
        if key in values:
            seen.add(key)
            if values[key]:
                out.append(f"- **{key}:** {values[key]}")
                last_field_idx = len(out) - 1
            # blank new value -> drop the line
        else:
            out.append(line)
            if key is not None:  # an unknown field the user added — keep it
                last_field_idx = len(out) - 1
    extra = [
        f"- **{k}:** {values[k]}"
        for k in _PROFILE_FIELDS
        if k not in seen and values.get(k)
    ]
    if extra:
        at = last_field_idx + 1 if last_field_idx >= 0 else len(out)
        out[at:at] = extra
    return "\n".join(out).rstrip("\n") + "\n"


def _normalize_dob(raw: str) -> str | None:
    """Return *raw* as YYYY-MM-DD, ``""`` if blank, or None if unparseable."""
    raw = raw.strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _ask_dob(default: str = "") -> str:
    """Ask for date of birth, re-prompting until it parses (Enter = skip)."""
    while True:
        dob = _normalize_dob(
            _ask("Date of birth (YYYY-MM-DD, or Enter to skip)", default=default)
        )
        if dob is not None:
            return dob
        console.print(
            "[err]Couldn't parse that date.[/] Try 1990-05-23 or 05/23/1990."
        )
        # Drop a bad pre-filled default so a non-interactive stdin (EOF keeps
        # returning `default`) resolves to a skip instead of spinning forever.
        default = ""


def _ask_email(default: str = "") -> str:
    """Ask for an email, re-prompting until it contains '@' (Enter = skip)."""
    while True:
        email = _ask("Email", default=default)
        if not email or "@" in email:
            return email
        console.print("[err]That doesn't look like an email[/] (needs an @).")
        default = ""  # avoid an EOF re-prompt loop on a bad pre-filled default


def _onboard_profile(edit: bool = False) -> None:
    """Create knowledge/profile.md, or (edit=True) re-prompt pre-filled to fix it."""
    if _has_profile_content() and not edit:
        return

    cur = _parse_profile() if edit else {}
    console.print()
    console.print(Rule("Profile", style="accent"))
    console.print(
        "Edit any field — Enter keeps the current value.\n" if edit
        else "I need some info to fill forms on your behalf.\n",
        style="info",
    )

    name = _ask("Full name", default=cur.get("Full name", ""))
    preferred = _ask(
        "Preferred Name (or Enter to skip)", default=cur.get("Preferred Name", "")
    )
    dob = _ask_dob(cur.get("Date of birth", ""))
    email = _ask_email(cur.get("Email", ""))
    phone = _ask("Phone (or Enter to skip)", default=cur.get("Phone", ""))
    location = _ask("Location (City, Country)", default=cur.get("Location", ""))
    linkedin = _ask(
        "LinkedIn URL (or Enter to skip)", default=cur.get("LinkedIn", "")
    )
    x_handle = _ask(
        "X / Twitter URL (or Enter to skip)", default=cur.get("X", "")
    )
    github = _ask("GitHub URL (or Enter to skip)", default=cur.get("GitHub", ""))
    summary = _ask(
        "One-line about yourself (work, education, interests)",
        default=cur.get("About", ""),
    )

    values = {
        "Full name": name,
        "Preferred Name": preferred,
        "Date of birth": dob,
        "Email": email,
        "Phone": phone,
        "Location": location,
        "LinkedIn": linkedin,
        "X": x_handle,
        "GitHub": github,
        "About": summary,
    }

    cfg.knowledge_dir.mkdir(parents=True, exist_ok=True)
    if edit and cfg.profile.is_file():
        # Preserve hand-added sections/paragraphs — update only known fields.
        cfg.profile.write_text(
            _apply_profile_edits(cfg.profile.read_text(), values)
        )
    else:
        lines = [f"# {name}\n", f"- **Full name:** {name}"]
        for label, val in list(values.items())[1:]:
            if val:
                lines.append(f"- **{label}:** {val}")
        lines.append("")
        cfg.profile.write_text("\n".join(lines))
    _capture("profile_created")
    console.print(f"\n[success]✓[/] Saved to [bold]{cfg.profile}[/]")
    console.print(
        "  Drop extra files (PDF, markdown, text) into knowledge/ any time.\n",
        style="info",
    )


def _probe_ollama() -> bool:
    """Return True if an Ollama server responds at OLLAMA_HOST (or localhost)."""
    import httpx
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    try:
        return httpx.get(f"{host}/api/tags", timeout=2.0).is_success
    except Exception:
        return False


def _env_set(name: str, value: str | None) -> None:
    """Set `name` to `value` in .env, or remove it entirely when value is None.

    Replaces rather than appends. Appending leaves the old line behind, so a
    pointer that should be gone lives on in the file and reappears the moment its
    key does — and a file without a trailing newline gets the next line glued to
    it.
    """
    if not cfg.env_file.exists():
        if value is None:
            return  # nothing to remove, and no reason to create the file
        lines = []
    else:
        lines = [
            ln
            for ln in cfg.env_file.read_text().splitlines()
            if not ln.strip().startswith(f"{name}=")
        ]
    if value is not None:
        lines.append(f"{name}={value}")
    cfg.env_file.write_text("\n".join(lines) + "\n" if lines else "")
    cfg.env_file.chmod(0o600)


def _persist_provider_choice(provider: str) -> None:
    """Record `provider` — but only if the keys present don't already imply it.

    The pointer outranks every key, so a redundant one is a loaded gun: confirm
    Browser Use while a keyless ``AUTOFILL_PROVIDER=openai`` sits in .env and
    OpenAI hijacks the day an OPENAI_API_KEY shows up. So it's removed whenever
    inference already reaches the choice, and written only to break a genuine tie
    (Ollama, which no key implies; or a shared shell key adopted on purpose).

    Call *after* writing any key to .env, so inference sees it.
    """
    if _infer_provider() == provider:
        _env_set("AUTOFILL_PROVIDER", None)
        os.environ.pop("AUTOFILL_PROVIDER", None)
        return
    _env_set("AUTOFILL_PROVIDER", provider)
    os.environ["AUTOFILL_PROVIDER"] = provider


def _onboard_ollama() -> None:
    """Configure Ollama: prompt for model, probe the server, write .env."""
    url = _PROVIDERS["ollama"]["url"]
    console.print(f"\n  Install Ollama and pull a model: [accent]{url}[/]\n")
    console.print("  [dim]Local and free, but needs a 14B+ model to fill well.[/]\n")
    model = _ask(
        f"Model name (Enter for default '{cfg.ollama_model}')",
        default=cfg.ollama_model,
    )
    # Ollama takes no API key, so nothing about the environment can imply it —
    # the pointer is the only record of the choice and is always written. It also
    # has to outrank any cloud key that shows up later: picking Ollama means
    # keeping the data local, and a BROWSER_USE_API_KEY appearing next week is no
    # reason to start shipping profile PII to a cloud model.
    _env_set("AUTOFILL_PROVIDER", "ollama")
    _env_set("AUTOFILL_OLLAMA_MODEL", model)
    os.environ["AUTOFILL_PROVIDER"] = "ollama"
    os.environ["AUTOFILL_OLLAMA_MODEL"] = model
    _capture("api_key_configured", {"provider": "ollama"})

    if _probe_ollama():
        console.print(f"[success]✓[/] Using Ollama with [bold]{model}[/].\n")
    else:
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        console.print(
            f"[success]✓[/] Saved Ollama config (model: [bold]{model}[/]).\n"
            f"[info]Note:[/] no Ollama server is responding at "
            f"[bold]{host}[/]. Start it with [bold]ollama serve[/] and run"
            f" [bold]ollama pull {model}[/] before using autofill.\n"
        )


def _onboard_api_key() -> None:
    """Prompt for a provider (and API key, unless local); confirm any detected one."""
    console.print()
    console.print(Rule("Provider", style="accent"))

    # A shell-exported AUTOFILL_PROVIDER outranks every key, and .env can't undo
    # it — load_dotenv() keeps the shell's value — so nothing chosen below would
    # stick. Say so rather than silently ignoring the answer (JAY-93).
    if "AUTOFILL_PROVIDER" in _AMBIENT_ENV_KEYS:
        stale = os.environ.get("AUTOFILL_PROVIDER", "")
        console.print(
            f"\n  [err]Your shell exports AUTOFILL_PROVIDER={stale}[/], which"
            " overrides whatever you pick here. Run [bold]unset"
            " AUTOFILL_PROVIDER[/] and drop it from your shell profile,"
            " otherwise this choice won't take effect.\n"
        )

    detected = _detect_provider()
    # Confirm a detected provider rather than adopting it silently. Ambient keys
    # (shared vars exported for another tool, e.g. ANTHROPIC_API_KEY for Claude)
    # don't get even that — they're skipped, so a user who wants Browser Use
    # never silently gets Anthropic (JAY-93).
    if detected and not _is_ambient_key(detected):
        detected_label = _PROVIDERS[detected]["label"].split(" (")[0]
        fp = _key_fingerprint(detected)
        fp_suffix = f" {fp}" if fp else ""
        if _PROVIDERS[detected].get("env") is None:
            detected_msg = (
                f"\n  Detected [accent]{detected_label}[/] configured in .env.\n"
            )
        else:
            detected_msg = (
                f"\n  Detected [accent]{detected_label}[/] API key"
                f" [dim]{fp}[/] in your environment.\n"
                if fp
                else f"\n  Detected [accent]{detected_label}[/]"
                " API key in your environment.\n"
            )
        console.print(detected_msg)
        keep = questionary.confirm(
            f"Use {detected_label}{fp_suffix}?", default=True, style=_Q_STYLE
        ).unsafe_ask()
        if keep:
            # Normally a no-op — inference already reaches `detected`, so this
            # writes nothing. It's here to clear a stale pointer that inference
            # is currently outvoting but which would hijack the run the moment
            # its key appeared.
            _persist_provider_choice(detected)
            _capture("api_key_configured", {"provider": detected, "source": "detected"})
            console.print(f"[success]✓[/] Using {detected_label}{fp_suffix}.\n")
            return
        console.print()
    else:
        # Explain why a key that's sitting right there wasn't offered.
        shared = [
            _PROVIDERS[n]["label"].split(" (")[0]
            for n in _PROVIDERS
            if _is_ambient_key(n)
        ]
        if shared:
            console.print(
                f"\n  Your shell has a [accent]{' and '.join(shared)}[/] key, but"
                " other tools read that variable too — so pick what autofill"
                " should use:\n"
            )

    names = list(_PROVIDERS)
    choices = [
        questionary.Choice(title=_PROVIDERS[n]["label"], value=n) for n in names
    ]
    provider = questionary.select(
        "Which LLM provider?", choices=choices, style=_Q_STYLE
    ).unsafe_ask()
    if not provider:
        provider = "browseruse"

    if provider == "ollama":
        _onboard_ollama()
        return

    info = _PROVIDERS[provider]
    existing = os.environ.get(info["env"])
    if existing:
        fp = _key_fingerprint(provider)
        key = _ask(f"Paste a key, or Enter to use your shell's {info['env']} {fp}")
    else:
        console.print(f"\n  Get a key here: [accent]{info['url']}[/]\n")
        key = _ask("Paste your API key (or Enter to skip)")

    if key:
        _env_set(info["env"], key)
        os.environ[info["env"]] = key
        _persist_provider_choice(provider)
        _capture("api_key_configured", {"provider": provider})
        console.print("[success]✓[/] Saved to .env\n")
    elif existing:
        # Nothing pasted, but a key is already in the environment. The user picked
        # this provider on purpose, so record it if inference can't infer it.
        _persist_provider_choice(provider)
        _capture("api_key_configured", {"provider": provider, "source": "ambient"})
        console.print(
            f"[success]✓[/] Using your {info['env']} from the environment.\n"
        )
    else:
        # No key for the pick — so it won't be used. Name what will be, rather
        # than let a provider they just declined quietly take the run.
        fallback = _infer_provider()
        note = (
            f" [bold]{_PROVIDERS[fallback]['label'].split(' (')[0]}[/] will be used"
            " until you do."
            if fallback
            else ""
        )
        console.print(
            f"[info]Skipped — set {info['env']} to use"
            f" {_PROVIDERS[provider]['label'].split(' (')[0]}.{note}[/]\n"
        )


def _onboard_files() -> None:
    """Ask the user if they want to add extra files to knowledge/."""
    console.print(Rule("Additional files", style="accent"))
    console.print(
        "You can add resumes, cover letters, etc. (.md, .txt, .pdf)", style="info"
    )
    add = questionary.confirm(
        "Add files to knowledge/ now?", default=False, style=_Q_STYLE
    ).unsafe_ask()
    if add:
        console.print(f"  Drop files into: [bold]{cfg.knowledge_dir.resolve()}[/]")
        _ask("Press Enter when done…")
    console.print()


def _onboard_browser_cookies() -> None:
    """Optionally import existing Chrome logins so autofill starts signed in."""
    console.print(Rule("Browser logins", style="accent"))
    console.print(
        "autofill can import your existing Chrome logins (cookies, never"
        " passwords) so it starts already signed in to sites like Workday.",
        style="info",
    )
    do_import = questionary.confirm(
        "Import Chrome logins now?", default=True, style=_Q_STYLE
    ).unsafe_ask()
    if not do_import:
        console.print(
            "[info]Skipped — you'll sign in manually the first time autofill"
            " hits a login (it remembers after that).[/]\n"
        )
        return

    state = _import_chrome_cookies()
    if not state:
        console.print(
            "[yellow]Couldn't read Chrome cookies[/] — Chrome may not be"
            " installed, or the cookie store is locked/encrypted on this"
            " system. No problem: sign in manually the first time autofill"
            " hits a login and it'll remember after that.\n"
        )
        return

    cfg.seed_state_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.seed_state_file.write_text(json.dumps(state))
    cfg.seed_state_file.chmod(0o600)
    _capture("chrome_cookies_imported", {"cookie_count": len(state["cookies"])})
    console.print(
        f"[success]✓[/] Imported {len(state['cookies'])} cookies — they'll load"
        " on your next run.\n"
    )


def _onboard(edit: bool = False) -> None:
    """Run first-time setup, or (edit=True) reconfigure: profile, key, files, ingest."""
    _capture("onboarding_started", {"edit": edit})
    console.print()
    console.print(_banner(
        f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
        "",
        "Reconfiguring — Enter keeps current values."
        if edit
        else "Looks like you're new here — starting setup.",
    ))
    console.print()

    _onboard_profile(edit=edit)
    _onboard_api_key()
    if not _has_any_api_key():
        raise SystemExit(
            "No provider configured. Set BROWSER_USE_API_KEY,"
            " ANTHROPIC_API_KEY, or OPENAI_API_KEY — or pick Ollama (local)"
            " by running autofill again."
        )
    _onboard_files()
    _onboard_browser_cookies()
    ingest()
    profile = retrieve(cfg.retrieval_query)
    if not profile.strip():
        raise SystemExit(
            "No profile content found after indexing. "
            "Add info to knowledge/profile.md and run autofill again."
        )
    console.print(
        "[success]✓[/] Setup complete. Run [bold]autofill '<url>'[/] to fill"
        " a form.\n"
    )


def _uninstall() -> None:
    """Remove the wrapper script and install directory after user confirmation."""
    import shutil

    install_dir = Path.home() / "autofill"
    wrapper = Path.home() / ".local" / "bin" / "autofill"

    targets = [p for p in (install_dir, wrapper) if p.exists() or p.is_symlink()]
    if not targets:
        console.print(
            "[info]Nothing to uninstall:[/] no install found at ~/autofill or"
            " ~/.local/bin/autofill."
        )
        return

    console.print("[err]This will delete:[/]")
    for p in targets:
        console.print(f"  {p}")
    if install_dir in targets:
        console.print("[dim](including your profile and knowledge files)[/]")

    confirm = questionary.confirm(
        "Are you sure?", default=False, style=_Q_STYLE
    ).unsafe_ask()
    if not confirm:
        console.print("[info]Cancelled.[/]")
        return

    if wrapper.exists() or wrapper.is_symlink():
        wrapper.unlink()
    if install_dir.exists():
        shutil.rmtree(install_dir)
    # Runs after irreversible deletion, so it must never crash: use builtin
    # print, not rich, which measures glyph width and can fail on a broken
    # unicode-width table and turn a successful uninstall into a traceback.
    print("\u2713 autofill uninstalled.")


def cli() -> None:
    """Entry point — abort cleanly on Ctrl-C anywhere (onboarding prompts
    included) with exit code 130 instead of dumping a KeyboardInterrupt traceback."""
    try:
        _run_cli()
    except KeyboardInterrupt:
        console.print("\n[info]Cancelled.[/]")
        raise SystemExit(130)


def _run_cli() -> None:
    """Parse arguments and dispatch to onboarding, status, or form fill."""
    os.chdir(Path(__file__).resolve().parent.parent)
    load_dotenv()
    # browser-use's built-in telemetry is opt-out and would ship the task
    # prompt (which embeds the user's profile PII), the form URL, and typed
    # field values to browser-use's PostHog. Disable it before any Agent is
    # built; setdefault honors an explicit user override.
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    _init_sentry()
    import argparse
    parser = argparse.ArgumentParser(description="AI-powered form autofill")
    parser.add_argument("command", nargs="?", default=None,
                        help="URL of the form to fill, 'setup', or 'uninstall'")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "browseruse", "ollama"],
        default=None,
        help="LLM provider (auto-detected from API key if omitted)",
    )
    parser.add_argument(
        "--version", action="version", version=f"autofill {_VERSION}"
    )
    args = parser.parse_args()

    if args.command == "uninstall":
        _uninstall()
        return

    if args.command == "setup":
        # Explicit reconfigure — re-run onboarding pre-filled with current values
        # so a mistyped field (e.g. date of birth) or the provider can be fixed.
        _onboard(edit=True)
        return

    # `--provider X` names the provider outright, so it settles the question the
    # ambient guard exists to ask. Gating on _has_any_api_key() alone would send
    # `--provider anthropic` to "Not set up yet" when the only ANTHROPIC_API_KEY
    # is a shell export, ignoring the very flag the user reached for.
    configured = (
        _provider_ready(args.provider) if args.provider else _has_any_api_key()
    )
    needs_setup = not _has_profile_content() or not configured

    if not args.command:
        if needs_setup:
            _onboard()
        else:
            console.print()
            console.print(_banner(
                f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
                "",
                "Usage: [bold]autofill '<url>'[/]",
                "Reconfigure: [bold]autofill setup[/]",
            ))
        return

    parsed = urlparse(args.command)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(
            f"Invalid URL '{args.command}'. Please provide a URL starting with"
            " http:// or https://"
        )

    if needs_setup:
        console.print(
            "[err]Not set up yet.[/] Run [bold]autofill setup[/] first, then"
            " [bold]autofill '<url>'[/]."
        )
        raise SystemExit(1)

    provider = args.provider or _detect_provider() or "browseruse"
    provider_label = _PROVIDERS[provider]["label"].split(" (")[0]
    fp = _key_fingerprint(provider)
    provider_line = (
        f"[dim]Provider:[/] [accent]{provider_label}[/] [dim]{fp}[/]"
        if fp
        else f"[dim]Provider:[/] [accent]{provider_label}[/]"
    )
    _capture("cli_invoked", {"provider": provider, "version": _VERSION})

    console.print()
    _play_intro(
        f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
        provider_line,
    )
    console.print()
    ingest()
    log_path = _setup_logging()
    asyncio.run(main(args.command, provider, log_path))


if __name__ == "__main__":
    cli()
