"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import browser_use as bu
import chromadb
import questionary
from autofill.telemetry import track as _capture
from dotenv import load_dotenv
from rich.console import Console
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

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200
    upsert_batch: int = 50
    max_text_chars: int = 100_000

    # Retrieval
    retrieval_query: str = "contact identity address work experience"
    retrieval_n: int = 10

    # Models — bump these when upgrading provider SDKs
    anthropic_model: str = "claude-sonnet-4-20250514"  # Anthropic Sonnet
    openai_model: str = "gpt-4o"                       # OpenAI GPT-4o

    # Corrections
    corrections_file: Path = Path("knowledge/.corrections.jsonl")

    # Agent
    agent_timeout: int = 600  # seconds before agent.run() is cancelled


cfg = Config()

# Attachable document types (not .md/.txt — those are indexed as text, not file-input bytes).
_ATTACHABLE_SUFFIXES = frozenset({".pdf", ".doc", ".docx"})
# Legacy .doc (1997-2003 OLE binary) has no viable pure-Python parser; we skip
# it during ingestion but still allow it as an upload attachment.
_UNPARSEABLE_SUFFIXES = frozenset({".doc"})

_PROVIDERS: dict[str, dict[str, str]] = {
    "browseruse": {
        "env": "BROWSER_USE_API_KEY",
        "label": "Browser Use (default — cheapest, no extra deps)",
        "url": "https://cloud.browser-use.com/settings?tab=api-keys&new=1",
    },
    "openai": {
        "env": "OPENAI_API_KEY",
        "label": "OpenAI",
        "url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "env": "ANTHROPIC_API_KEY",
        "label": "Anthropic",
        "url": "https://console.anthropic.com/settings/keys",
    },
}

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

_LOGO_LINES = [
    "  [rgb(188,167,202) on rgb(162,132,185)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(188,167,202) on rgb(162,132,185)]▀[/]",
    "  [rgb(162,132,185)]█[/][rgb(113,67,149)]█[/][rgb(55,33,72) on rgb(113,67,149)]▀[/][rgb(113,67,149)]█[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(113,67,149)]█[/][rgb(55,33,72) on rgb(113,67,149)]▀[/][rgb(113,67,149)]█[/][rgb(162,132,185)]█[/]",
    "  [rgb(162,132,185)]█[/][rgb(113,67,149)]█[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(113,67,149)]█[/][rgb(113,67,149)]█[/][rgb(113,67,149)]█[/][rgb(140,102,170) on rgb(113,67,149)]▀[/][rgb(113,67,149)]█[/][rgb(162,132,185)]█[/]",
    "[rgb(140,102,170)]▄[/][rgb(188,167,202) on rgb(113,67,149)]▀[/][rgb(113,67,149) on rgb(162,132,185)]▀[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(140,102,170)]█[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(140,102,170)]█[/][rgb(140,102,170) on rgb(162,132,185)]▀[/][rgb(113,67,149) on rgb(162,132,185)]▀[/][rgb(188,167,202) on rgb(113,67,149)]▀[/][rgb(140,102,170)]▄[/]",
    "[rgb(188,167,202)]▀[/][rgb(188,167,202)]█[/][rgb(188,167,202) on rgb(113,67,149)]▀[/][rgb(140,102,170)]█[/][rgb(162,132,185)]▀[/][rgb(162,132,185) on rgb(140,102,170)]▀[/][rgb(162,132,185)]█[/][rgb(162,132,185)]█[/][rgb(162,132,185) on rgb(140,102,170)]▀[/][rgb(162,132,185)]▀[/][rgb(140,102,170)]█[/][rgb(188,167,202) on rgb(113,67,149)]▀[/][rgb(188,167,202)]█[/][rgb(188,167,202)]▀[/]",
    "   [rgb(188,167,202)]▄[/][rgb(162,132,185) on rgb(113,67,149)]▀[/][rgb(113,67,149) on rgb(162,132,185)]▀[/][rgb(188,167,202)]▀[/][rgb(188,167,202)]▀[/][rgb(113,67,149) on rgb(188,167,202)]▀[/][rgb(162,132,185) on rgb(113,67,149)]▀[/][rgb(188,167,202)]▄[/]",
]


def _banner(*info_lines: str) -> Table:
    """Build a Claude-Code-style banner: pixel-art logo left, info text right."""
    logo = Text()
    for i, line in enumerate(_LOGO_LINES):
        if i:
            logo.append("\n")
        logo.append_text(Text.from_markup(line))

    info = Text()
    for i, line in enumerate(info_lines):
        if i:
            info.append("\n")
        info.append_text(Text.from_markup(line))

    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_row(logo, info)
    return table


def _detect_provider() -> str | None:
    """Return the first provider whose API key is present in the environment."""
    saved = os.environ.get("AUTOFILL_PROVIDER", "").strip().lower()
    if saved in _PROVIDERS and os.environ.get(_PROVIDERS[saved]["env"]):
        return saved
    for name, info in _PROVIDERS.items():
        if os.environ.get(info["env"]):
            return name
    return None


def _has_any_api_key() -> bool:
    """Return True if at least one recognised API key is present in the environment."""
    return _detect_provider() is not None


def _client() -> chromadb.ClientAPI:
    """Return a persistent Chroma client, creating the DB directory if needed."""
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
    for doc_id, meta in zip(stored["ids"], stored["metadatas"]):
        fname = doc_id.split(":")[0]
        stored_ids.setdefault(fname, []).append(doc_id)
        if meta and "hash" in meta and fname not in stored_hashes:
            stored_hashes[fname] = meta["hash"]

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
                f"[yellow]Warning:[/] [bold]{path.name}[/] is a legacy .doc file — "
                "its content won't be indexed. Resave as .docx or PDF to make it searchable."
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
    to_ingest = {f: p for f, p in current_files.items() if stored_hashes.get(f) != hashes[f]}
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
                console.print(f"[yellow]Warning:[/] [bold]{fname}[/] produced no text chunks — skipping.")
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
    """Query the Chroma collection and return the top-*n* chunks joined by blank lines."""
    col = _client().get_or_create_collection(cfg.collection)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)


def _attachment_paths() -> list[str]:
    """Paths browser-use may pass to ``<input type="file">``.

    Includes every PDF/DOC/DOCX in ``knowledge/`` (same visibility rules as ``ingest``).
    There is **no** basename pattern or "resume" substring — only the suffix allowlist.
    Which path belongs to which upload field is decided by the agent from **form labels**,
    not from matching strings in filenames.
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


def _llm(provider: str) -> object:
    """Instantiate the chat model for the given *provider* name."""
    if provider == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic
        return ChatAnthropic(model=cfg.anthropic_model)
    if provider == "openai":
        from browser_use.llm.openai.chat import ChatOpenAI
        return ChatOpenAI(model=cfg.openai_model)
    if provider == "browseruse":
        return bu.ChatBrowserUse()
    raise ValueError(f"Unknown provider '{provider}'. Choose: anthropic, openai, browseruse")


_FORM_TAGS = frozenset({"input", "textarea", "select"})
_FORM_ROLES = frozenset({"textbox", "combobox", "listbox", "spinbutton", "searchbox",
                          "radio", "checkbox", "switch"})


async def _snapshot_fields(session) -> dict:
    """Snapshot form field values using browser-use's DOM + CDP value reads.

    **Field discovery and labeling** — browser-use's accessibility tree
    (``get_browser_state_summary``).  Labels come from the browser's own
    accessible-name computation, which works on every site.

    **Live values** — CDP ``DOM.resolveNode`` + ``Runtime.callFunctionOn``
    to read the JS ``.value`` property for each field.  HTML attributes
    don't update when users type, but ``.value`` does.
    """
    try:
        state = await session.get_browser_state_summary(include_screenshot=False)
        if not state or not state.dom_state or not state.dom_state.selector_map:
            return {}

        cdp_session = await session.get_or_create_cdp_session(focus=False)

        result: dict[str, str] = {}
        # Disambiguate repeated labels (multi-row employment history, duplicate
        # "Address line", etc.) by suffixing "(2)", "(3)", …  Stable within a
        # run and usually stable across runs on the same form.
        seen_counts: dict[str, int] = {}
        for _idx, node in state.dom_state.selector_map.items():
            try:
                tag = (node.tag_name or "").lower()
                role = (node.ax_node.role or "").lower() if node.ax_node else ""

                if tag not in _FORM_TAGS and role not in _FORM_ROLES:
                    continue

                attrs = node.attributes or {}

                # Build label from accessibility name.
                label = ""
                if node.ax_node and node.ax_node.name:
                    label = node.ax_node.name.strip()
                if not label:
                    label = (attrs.get("aria-label", "")
                             or attrs.get("placeholder", "")
                             or attrs.get("name", "")
                             or attrs.get("id", "")
                             or f"field_{_idx}")

                # Skip sensitive fields (passwords, OTP, card numbers, etc.)
                if _SENSITIVE_FIELD_RE.search(label):
                    continue

                seen_counts[label] = seen_counts.get(label, 0) + 1
                key = label if seen_counts[label] == 1 else f"{label} ({seen_counts[label]})"

                # Read live value via CDP.
                value = await _read_live_value(cdp_session, node.backend_node_id, role)
                if value is not None:
                    result[key] = value
            except Exception:
                continue
        return result
    except Exception:
        return {}


async def _read_live_value(cdp_session, backend_node_id: int, role: str) -> str | None:
    """Read the current JS .value (or checked state) of a DOM node via CDP."""
    try:
        resolve_result = await cdp_session.cdp_client.send.DOM.resolveNode(
            {"backendNodeId": backend_node_id},
            session_id=cdp_session.session_id,
        )
        object_id = resolve_result.get("object", {}).get("objectId")
        if not object_id:
            return None

        if role in ("checkbox", "radio", "switch"):
            # Native inputs use .checked; ARIA widgets (e.g. div[role=radio])
            # use the aria-checked attribute instead.
            fn = (
                "function() {"
                "  if (typeof this.checked === 'boolean') return this.checked ? 'true' : 'false';"
                "  var ac = this.getAttribute('aria-checked');"
                "  if (ac) return ac;"
                "  return 'false';"
                "}"
            )
        elif role in ("combobox", "listbox"):
            # Read both .value and aria-selected text for custom dropdowns.
            fn = (
                "function() {"
                "  if (this.value) return this.value;"
                "  var sel = this.querySelector('[aria-selected=\"true\"]');"
                "  if (sel) return sel.textContent.trim();"
                "  return '';"
                "}"
            )
        else:
            fn = "function() { return this.value || ''; }"

        call_result = await cdp_session.cdp_client.send.Runtime.callFunctionOn(
            {
                "objectId": object_id,
                "functionDeclaration": fn,
                "returnByValue": True,
            },
            session_id=cdp_session.session_id,
        )
        return call_result.get("result", {}).get("value", "")
    except Exception:
        return None


async def _poll_fields(session, snapshot: dict, interval: float = 1.0,
                       timeout: float = 600, empty_exit_after: int = 5) -> None:
    """Continuously update snapshot with current field values until *timeout*.

    Transient empty reads (mid-navigation, shadow DOM hiccups) are tolerated,
    but *empty_exit_after* consecutive empty reads are treated as "user
    navigated away / submitted" and stop the loop.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    empty_streak = 0
    while loop.time() < deadline:
        await asyncio.sleep(interval)
        try:
            current = await _snapshot_fields(session)
        except Exception:
            break
        if current:
            snapshot.update(current)
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak >= empty_exit_after:
                break


def _load_corrections(url: str) -> str:
    """Return previously saved corrections for this domain, formatted for the task prompt."""
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
        lines.append(f"- {field}: use '{change['user']}' (not '{change['agent']}')")
    return "\n".join(lines)


_SENSITIVE_FIELD_RE = re.compile(
    r"\b(password|passcode|otp|pin|2fa|ssn|social.?sec|cvv|cvc|card.?num|card.?number"
    r"|expir|exp_|secret|token|auth|passport|birth|dob|bank|routing|account.?num)\b",
    re.IGNORECASE,
)


def _save_corrections(url: str, corrections: dict) -> None:
    """Append field corrections to the corrections log.

    Sensitive fields (passwords, OTP, SSN, CVV, etc.) are stripped before
    writing so they are never persisted or later injected into an LLM prompt.
    """
    safe = {k: v for k, v in corrections.items() if not _SENSITIVE_FIELD_RE.search(k)}
    if not safe:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "domain": urlparse(url).netloc,
        "corrections": safe,
    }
    cfg.corrections_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.corrections_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def main(url: str, provider: str) -> None:
    """Build the task prompt and run the browser agent (ingest already ran in cli)."""
    profile = retrieve(cfg.retrieval_query)
    if not profile.strip():
        raise SystemExit(
            "No profile in the knowledge store. Add one or more files under knowledge/ "
            "(e.g. knowledge/profile.md — see README), run from the project root, then try again."
        )

    attachments = _attachment_paths()
    if attachments:
        _capture("file_attachments_found", {"attachment_count": len(attachments)})
        upload_rule = (
            "- For each file upload, read the field label on the page; choose one path from "
            f"this list that fits that label (CV vs cover letter vs other document): {attachments}.\n"
            "- Do not upload passport/license/ID scans unless required; skip if unsure."
        )
    else:
        upload_rule = (
            "- Do not upload real identity documents; skip file uploads requiring real files."
        )

    prior_corrections = _load_corrections(url)
    corrections_section = f"\n{prior_corrections}\n" if prior_corrections else ""

    task = f"""
Open {url} and fill every applicable field using the profile below (map labels
loosely — e.g. "Phone" = telephone):

{profile}
{corrections_section}
Rules:
- Prefer selects and radios that match the values above; otherwise choose the closest reasonable option.
- Try to answer all the questions; if unsure, make a reasonable guess.
- For longer fields, write a few sentences consistent with the profile.
{upload_rule}
- Do not click Submit, Apply, Send, or any control that finalises the application.
- When everything reasonable is filled, finish with the done action and tell the user to review and submit manually.
"""

    llm = _llm(provider)
    browser_profile = bu.BrowserProfile(keep_alive=True, headless=False)
    agent = bu.Agent(
        task=task,
        llm=llm,
        browser_profile=browser_profile,
        initial_actions=[{"navigate": {"url": url, "new_tab": False}}],
        available_file_paths=attachments or None,
        use_judge=False,
    )
    _capture("form_fill_started", {
        "provider": provider,
        "has_attachments": bool(attachments),
        "has_prior_corrections": bool(prior_corrections),
    })
    timed_out = False
    try:
        async with asyncio.timeout(cfg.agent_timeout):
            await agent.run(max_steps=15)
    except TimeoutError:
        timed_out = True
        _capture("form_fill_timed_out", {
            "provider": provider,
            "timeout_seconds": cfg.agent_timeout,
        })
        console.print(
            f"\n[err]Agent timed out after {cfg.agent_timeout}s.[/] "
            "The browser is still open — you can continue manually.",
        )
    try:
        if not timed_out:
            _capture("form_fill_completed", {"provider": provider, "has_attachments": bool(attachments)})
        # Snapshot what the agent filled, then poll for user edits until submit/navigate.
        console.print("\n[info]Capturing form state — please review and submit in the browser.[/]")
        agent_snapshot: dict = {}
        user_snapshot: dict = {}
        if agent.browser_session is not None:
            try:
                agent_snapshot = await _snapshot_fields(agent.browser_session)
                console.print(f"[dim]Tracking {len(agent_snapshot)} field(s)…[/]")
                user_snapshot = dict(agent_snapshot)
                await _poll_fields(agent.browser_session, user_snapshot)
            except Exception as exc:
                console.print(f"[err]Warning:[/] Could not track field changes: {exc}")

        print("\a", end="", flush=True)

        corrections = {
            k: {"agent": agent_snapshot.get(k, ""), "user": v}
            for k, v in user_snapshot.items()
            if agent_snapshot.get(k) != v and v
        }
        if corrections:
            _save_corrections(url, corrections)
            _capture("corrections_saved", {"correction_count": len(corrections)})
            console.print(f"[info]Saved {len(corrections)} correction(s) for next time.[/]")

        console.print("[info]Submitted — browser stays open.[/]")
    finally:
        # Always tear down event buses and watchdogs (keeps the browser window open).
        if agent.browser_session is not None:
            try:
                await agent.browser_session.stop()
            except Exception:
                pass


def _has_profile_content() -> bool:
    """True if knowledge/ has at least one non-hidden, non-example file with real content."""
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
    """Show an interactive text prompt and return the stripped answer (or *default*)."""
    try:
        val = questionary.text(prompt, style=_Q_STYLE).ask()
    except (EOFError, KeyboardInterrupt):
        console.print()
        val = None
    return (val or "").strip() or default


def _onboard_profile() -> None:
    """Walk the user through creating knowledge/profile.md if it doesn't exist."""
    if _has_profile_content():
        return

    console.print()
    console.print(Rule("Profile", style="accent"))
    console.print("I need some info to fill forms on your behalf.\n", style="info")

    name = _ask("Full name")
    dob = _ask("Date of birth (MM/DD/YYYY, or Enter to skip)")
    email = _ask("Email")
    phone = _ask("Phone (or Enter to skip)")
    location = _ask("Location (City, Country)")
    linkedin = _ask("LinkedIn URL (or Enter to skip)")
    x_handle = _ask("X / Twitter URL (or Enter to skip)")
    github = _ask("GitHub URL (or Enter to skip)")
    summary = _ask("One-line about yourself (work, education, interests)")

    lines = [f"# {name}\n"]
    lines.append(f"- **Full name:** {name}")
    if dob:
        lines.append(f"- **Date of birth:** {dob}")
    if email:
        lines.append(f"- **Email:** {email}")
    if phone:
        lines.append(f"- **Phone:** {phone}")
    if location:
        lines.append(f"- **Location:** {location}")
    if linkedin:
        lines.append(f"- **LinkedIn:** {linkedin}")
    if x_handle:
        lines.append(f"- **X:** {x_handle}")
    if github:
        lines.append(f"- **GitHub:** {github}")
    if summary:
        lines.append(f"- **About:** {summary}")
    lines.append("")

    cfg.knowledge_dir.mkdir(parents=True, exist_ok=True)
    cfg.profile.write_text("\n".join(lines))
    _capture("profile_created")
    console.print(f"\n[success]✓[/] Saved to [bold]{cfg.profile}[/]")
    console.print(
        "  Drop extra files (PDF, markdown, text) into knowledge/ any time.\n",
        style="info",
    )


def _onboard_api_key() -> None:
    """Prompt for an LLM API key if none is set, letting the user pick a provider."""
    if _has_any_api_key():
        return

    console.print()
    console.print(Rule("API key", style="accent"))

    names = list(_PROVIDERS)
    choices = [
        questionary.Choice(title=_PROVIDERS[n]["label"], value=n) for n in names
    ]
    provider = questionary.select(
        "Which LLM provider?", choices=choices, style=_Q_STYLE
    ).ask()
    if not provider:
        provider = "browseruse"

    info = _PROVIDERS[provider]
    console.print(f"\n  Get a key here: [accent]{info['url']}[/]\n")

    key = _ask("Paste your API key (or Enter to skip)")
    if key:
        with open(cfg.env_file, "a") as f:
            f.write(f"{info['env']}={key}\n")
            f.write(f"AUTOFILL_PROVIDER={provider}\n")
        cfg.env_file.chmod(0o600)
        os.environ[info["env"]] = key
        os.environ["AUTOFILL_PROVIDER"] = provider
        _capture("api_key_configured", {"provider": provider})
        console.print("[success]✓[/] Saved to .env\n")
    else:
        console.print("[info]Skipped — set an API key before running autofill.[/]\n")


def _onboard_files() -> None:
    """Ask the user if they want to add extra files to knowledge/."""
    console.print(Rule("Additional files", style="accent"))
    console.print(
        "You can add resumes, cover letters, etc. (.md, .txt, .pdf)", style="info"
    )
    add = questionary.confirm(
        "Add files to knowledge/ now?", default=False, style=_Q_STYLE
    ).ask()
    if add:
        console.print(f"  Drop files into: [bold]{cfg.knowledge_dir.resolve()}[/]")
        _ask("Press Enter when done…")
    console.print()


def _onboard() -> None:
    """Run the full first-time setup: profile, API key, extra files, then ingest."""
    _capture("onboarding_started")
    console.print()
    console.print(_banner(
        f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
        "",
        "Looks like you're new here — starting setup.",
    ))
    console.print()

    _onboard_profile()
    _onboard_api_key()
    if not _has_any_api_key():
        raise SystemExit(
            "No API key set. Set BROWSER_USE_API_KEY, OPENAI_API_KEY, or "
            "ANTHROPIC_API_KEY, then run autofill again."
        )
    _onboard_files()
    ingest()
    profile = retrieve(cfg.retrieval_query)
    if not profile.strip():
        raise SystemExit(
            "No profile content found after indexing. "
            "Add info to knowledge/profile.md and run autofill again."
        )
    console.print("[success]✓[/] Setup complete. Run [bold]autofill <url>[/] to fill a form.\n")


def _uninstall() -> None:
    """Remove the autofill wrapper script and install directory after user confirmation."""
    import shutil

    install_dir = Path.home() / "autofill"
    wrapper = Path.home() / ".local" / "bin" / "autofill"

    targets = [p for p in (install_dir, wrapper) if p.exists() or p.is_symlink()]
    if not targets:
        print("Nothing to uninstall: no install found at ~/autofill or ~/.local/bin/autofill.")
        return

    print("\033[1;31mThis will delete:\033[0m")
    for p in targets:
        print(f"  {p}")
    if install_dir in targets:
        print("(including your profile and knowledge files)")

    confirm = questionary.confirm(
        "Are you sure?", default=False, style=_Q_STYLE
    ).ask()
    if not confirm:
        print("Cancelled.")
        return

    if wrapper.exists() or wrapper.is_symlink():
        wrapper.unlink()
    if install_dir.exists():
        shutil.rmtree(install_dir)
    print("\u2713 autofill uninstalled.")


def cli() -> None:
    """Entry point: parse arguments and dispatch to onboarding, status display, or form fill."""
    os.chdir(Path(__file__).resolve().parent.parent)
    load_dotenv()
    import argparse
    parser = argparse.ArgumentParser(description="AI-powered form autofill")
    parser.add_argument("command", nargs="?", default=None,
                        help="URL of the form to fill, or 'uninstall'")
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai", "browseruse"],
        default=None,
        help="LLM provider (auto-detected from API key if omitted)",
    )
    args = parser.parse_args()

    if args.command == "uninstall":
        _uninstall()
        return

    needs_setup = not _has_profile_content() or not _has_any_api_key()

    if not args.command:
        if needs_setup:
            _onboard()
        else:
            console.print()
            console.print(_banner(
                f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
                "",
                "Usage: [bold]autofill <url>[/]",
            ))
        return

    from urllib.parse import urlparse
    parsed = urlparse(args.command)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(
            f"Invalid URL '{args.command}'. Please provide a URL starting with http:// or https://"
        )

    if needs_setup:
        console.print(
            "[err]Not set up yet.[/] Run [bold]autofill[/] first, then [bold]autofill <url>[/]."
        )
        raise SystemExit(1)

    provider = args.provider or _detect_provider() or "browseruse"
    _capture("cli_invoked", {"provider": provider, "version": _VERSION})

    console.print()
    console.print(_banner(f"[bold]autofill[/]  [dim]v{_VERSION}[/]"))
    console.print()
    ingest()
    asyncio.run(main(args.command, provider))


if __name__ == "__main__":
    cli()
