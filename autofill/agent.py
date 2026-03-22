"""AI-powered form autofill: ingest local knowledge, retrieve context, fill form."""

import asyncio
import hashlib
import os
from pathlib import Path

import browser_use as bu
import chromadb
import questionary
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.rule import Rule
from rich.theme import Theme

_KNOWLEDGE_DIR = Path("knowledge")
_DB_PATH = _KNOWLEDGE_DIR / ".db"
_COLLECTION = "profile"
_PROFILE_EXAMPLE = _KNOWLEDGE_DIR / "profile.example.md"
_PROFILE = _KNOWLEDGE_DIR / "profile.md"
_ENV_FILE = Path(".env")

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
_VERSION = "0.1.0"

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

_LOGO = """\
       _____
     .'     '.
    / (◉)-(◉) \\
   |    \\_/    |
    '.._____.'
   /|/ | | \\|\\
  (_/  | |  \\_)"""


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
    _DB_PATH.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(_DB_PATH))


_MAX_TEXT_CHARS = 100_000


def _read(path: Path) -> str:
    if path.suffix == ".pdf":
        import pdfplumber
        parts: list[str] = []
        total = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                parts.append(text)
                total += len(text)
                if total >= _MAX_TEXT_CHARS:
                    break
        return "\n".join(parts)
    text = path.read_text()
    return text[:_MAX_TEXT_CHARS]


def _hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 200
_UPSERT_BATCH = 50


def _chunk_text(text: str) -> list[str]:
    """Split text into chunks of ~_CHUNK_SIZE chars, preferring paragraph/sentence boundaries."""
    separators = ["\n\n", "\n", ". ", " "]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        if end < len(text):
            # Try each separator to find a clean break point
            for sep in separators:
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - _CHUNK_OVERLAP if end < len(text) else end
    return chunks


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
            if fname in stored_ids:
                col.delete(ids=stored_ids[fname])
            chunks = _chunk_text(_read(path))
            if not chunks:
                progress.advance(task_id)
                continue
            for i in range(0, len(chunks), _UPSERT_BATCH):
                batch = chunks[i : i + _UPSERT_BATCH]
                col.upsert(
                    ids=[f"{fname}:{i + j}" for j in range(len(batch))],
                    documents=batch,
                    metadatas=[{"hash": h}] * len(batch),
                )
            progress.advance(task_id)


def retrieve(query: str, n: int = 10) -> str:
    col = _client().get_or_create_collection(_COLLECTION)
    results = col.query(query_texts=[query], n_results=n)
    docs: list[str] = results["documents"][0]  # type: ignore[index]
    return "\n\n".join(docs)


def _llm(provider: str) -> object:
    if provider == "anthropic":
        from browser_use.llm.anthropic.chat import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-20250514")
    if provider == "openai":
        from browser_use.llm.openai.chat import ChatOpenAI
        return ChatOpenAI(model="gpt-4o")
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
    console.print(
        "\n[success]✓[/] Browser left open — review and submit in the window."
    )
    await asyncio.to_thread(
        input, "  Press Enter to exit when finished. "
    )


def _has_profile_content() -> bool:
    """True if knowledge/ has at least one non-hidden, non-example file with real content."""
    if not _KNOWLEDGE_DIR.is_dir():
        return False
    for p in sorted(_KNOWLEDGE_DIR.iterdir()):
        if p.name.startswith(".") or not p.is_file():
            continue
        if p.name == "profile.example.md":
            continue
        if p.stat().st_size > 0:
            return True
    return False


def _ask(prompt: str, default: str = "") -> str:
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

    _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE.write_text("\n".join(lines))
    console.print(f"\n[success]✓[/] Saved to [bold]{_PROFILE}[/]")
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
        with open(_ENV_FILE, "a") as f:
            f.write(f"export {info['env']}=\"{key}\"\n")
            f.write(f'export AUTOFILL_PROVIDER="{provider}"\n')
        _ENV_FILE.chmod(0o600)
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
        console.print(f"  Drop files into: [bold]{_KNOWLEDGE_DIR.resolve()}[/]")
        _ask("Press Enter when done…")
    console.print()


def _onboard() -> None:
    """Run the full first-time setup: profile, API key, extra files, then ingest."""
    console.print()
    console.print(
        Panel(
            f"[accent]{_LOGO}[/]\n\n  [bold]autofill[/]  [dim]v{_VERSION}[/]",
            border_style="accent",
            padding=(1, 2),
        )
    )
    console.print("  Welcome! Let's get you set up.\n")

    _onboard_profile()
    _onboard_api_key()
    if not _has_any_api_key():
        raise SystemExit(
            "No API key set. Set BROWSER_USE_API_KEY, OPENAI_API_KEY, or "
            "ANTHROPIC_API_KEY, then run autofill again."
        )
    _onboard_files()
    ingest()
    profile = retrieve("contact identity address work experience")
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
    console.print("[success]✓[/] autofill uninstalled.")


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
            console.print(
                f"[accent]◉[/] [bold]autofill[/] [dim]v{_VERSION}[/]"
            )
            console.print("Usage: [bold]autofill <form-url>[/]")
        return

    console.print(f"\n  [accent]◉[/] [bold]autofill[/] [dim]v{_VERSION}[/]\n")
    provider = args.provider or _detect_provider() or "browseruse"
    ingest()
    asyncio.run(main(args.command, provider))


if __name__ == "__main__":
    cli()
