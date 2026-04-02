"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import browser_use as bu
import chromadb
import questionary
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
    corrections: Path = Path("knowledge/corrections.md")
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

    # Agent
    agent_timeout: int = 600  # seconds before agent.run() is cancelled


cfg = Config()

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
    return _detect_provider() is not None


def _client() -> chromadb.ClientAPI:
    """Return a persistent Chroma client, creating the DB directory if needed."""
    cfg.db_path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(cfg.db_path))


def _read(path: Path) -> str:
    """Read a file's text content, truncating to ``cfg.max_text_chars``."""
    if path.suffix == ".pdf":
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
    text = path.read_text()
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
        start = max(0, end - cfg.chunk_overlap) if end < len(text) else end
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

    current_files = {
        path.name: path
        for path in sorted(cfg.knowledge_dir.iterdir())
        if not path.name.startswith(".")
        and path.is_file()
        and path.name != "profile.example.md"
    }

    # Remove deleted files
    for fname in set(stored_hashes) - set(current_files):
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


def retrieve(query: str, n: int = cfg.retrieval_n) -> str:
    """Query the Chroma collection and return the top-*n* chunks joined by blank lines."""
    col = _client().get_or_create_collection(cfg.collection)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)


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


def _load_corrections() -> str:
    """Load accumulated user corrections from the corrections file, if any."""
    if cfg.corrections.is_file() and cfg.corrections.stat().st_size > 0:
        return cfg.corrections.read_text().strip()
    return ""


def _collect_corrections() -> None:
    """Ask the user if they made edits and record corrections for future runs."""
    console.print()
    made_edits = questionary.confirm(
        "Did you make any corrections to what the agent filled?",
        default=False,
        style=_Q_STYLE,
    ).ask()
    if not made_edits:
        return

    console.print(
        "  Describe what you changed so the agent learns for next time.\n"
        "  (e.g. \"Use +1 country code for phone\", \"Pick 'Senior' not 'Mid-level'\")\n"
        "  Enter a blank line when done.\n",
        style="info",
    )
    corrections: list[str] = []
    while True:
        line = _ask("  Correction (or Enter to finish)")
        if not line:
            break
        corrections.append(f"- {line}")

    if not corrections:
        return

    header = "# Corrections\n\nLearned preferences from past form fills.\n\n"
    new_entries = "\n".join(corrections) + "\n"

    if cfg.corrections.is_file() and cfg.corrections.stat().st_size > 0:
        existing = cfg.corrections.read_text()
        cfg.corrections.write_text(existing.rstrip() + "\n" + new_entries)
    else:
        cfg.corrections.write_text(header + new_entries)

    console.print(
        f"[success]✓[/] Saved {len(corrections)} correction(s) to [bold]{cfg.corrections}[/] "
        "— the agent will apply them next time.",
    )


async def main(url: str, provider: str) -> None:
    """Ingest knowledge, build the task prompt, and run the browser agent."""
    ingest()
    profile = retrieve(cfg.retrieval_query)
    if not profile.strip():
        raise SystemExit(
            "No profile in the knowledge store. Add one or more files under knowledge/ "
            "(e.g. knowledge/profile.md — see README), run from the project root, then try again."
        )

    corrections = _load_corrections()
    corrections_block = ""
    if corrections:
        corrections_block = f"""

Past corrections from the user (apply these lessons — they override defaults):
{corrections}
"""

    task = f"""
Open {url} and fill every applicable field using the profile below (map labels
loosely — e.g. "Phone" = telephone):

{profile}
{corrections_block}
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
    try:
        async with asyncio.timeout(cfg.agent_timeout):
            await agent.run()
    except TimeoutError:
        console.print(
            f"\n[err]Agent timed out after {cfg.agent_timeout}s.[/] "
            "The browser is still open — you can continue manually.",
        )
    console.print(
        "\n[success]✓[/] Browser left open — review and submit in the window."
    )
    await asyncio.to_thread(
        input, "  Press Enter after you've reviewed (and edited) the form. "
    )
    _collect_corrections()


def _has_profile_content() -> bool:
    """True if knowledge/ has at least one non-hidden, non-example file with real content."""
    if not cfg.knowledge_dir.is_dir():
        return False
    for p in sorted(cfg.knowledge_dir.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if p.name == "profile.example.md":
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
    console.print()
    console.print(_banner(
        f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
        "",
        "Welcome! Let's get you set up.",
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
    console.print("[success]✓[/] Done! You're all set.\n")


def _uninstall() -> None:
    import shutil

    repo_root = Path(__file__).resolve().parent.parent
    symlink = Path.home() / ".local" / "bin" / "autofill"

    console.print(
        f"This will delete [bold]{repo_root}[/] "
        "(including your profile and knowledge files).",
        style="err",
    )
    confirm = questionary.confirm(
        "Are you sure?", default=False, style=_Q_STYLE
    ).ask()
    if not confirm:
        console.print("Cancelled.")
        return

    if symlink.is_symlink():
        symlink.unlink()

    shutil.rmtree(repo_root)
    print("\u2713 autofill uninstalled.")


def cli() -> None:
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

    if needs_setup:
        _onboard()

    if not args.command:
        if needs_setup:
            console.print(
                "Setup complete. Next: [bold]autofill <form-url>[/]"
            )
        else:
            console.print()
            console.print(_banner(
                f"[bold]autofill[/]  [dim]v{_VERSION}[/]",
                "",
                "Usage: [bold]autofill <form-url>[/]",
            ))
        return

    from urllib.parse import urlparse
    parsed = urlparse(args.command)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(
            f"Invalid URL '{args.command}'. Please provide a URL starting with http:// or https://"
        )

    console.print()
    console.print(_banner(f"[bold]autofill[/]  [dim]v{_VERSION}[/]"))
    console.print()
    provider = args.provider or _detect_provider() or "browseruse"
    ingest()
    asyncio.run(main(args.command, provider))


if __name__ == "__main__":
    cli()
