"""Anonymous, opt-out usage telemetry.

To disable: add AUTOFILL_TELEMETRY=0 to .env or your environment.

Events sent (no PII):
  install  — first-time setup completed
  run      — form fill started (URL domain only, no path/query/fragment)
  complete — form fill finished
  timeout  — agent hit the time limit

All events include: tool version, Python version, OS platform, LLM provider.
Nothing is sent if AUTOFILL_TELEMETRY=0, or if the PostHog key is not set.
"""

import os
import platform
import sys
import threading
import uuid
from pathlib import Path

# ── PostHog setup ────────────────────────────────────────────────────────────
# Sign up at https://posthog.com (free tier is fine), create a project, and
# replace the placeholder below with your Project API key.
_POSTHOG_KEY = "REPLACE_WITH_YOUR_POSTHOG_KEY"
_POSTHOG_HOST = "https://us.i.posthog.com"
# ─────────────────────────────────────────────────────────────────────────────


def _enabled() -> bool:
    return (
        os.environ.get("AUTOFILL_TELEMETRY", "1").strip() != "0"
        and not _POSTHOG_KEY.startswith("REPLACE_")
    )


def _install_id() -> str:
    """Return a persistent anonymous install UUID, creating it on first call."""
    id_path = Path.home() / ".config" / "autofill" / "id"
    try:
        if id_path.exists():
            return id_path.read_text().strip()
        id_path.parent.mkdir(parents=True, exist_ok=True)
        new_id = str(uuid.uuid4())
        id_path.write_text(new_id)
        return new_id
    except Exception:
        return "unknown"


def track(event: str, properties: dict | None = None) -> None:
    """Fire-and-forget telemetry ping. Never raises, never blocks the caller."""
    if not _enabled():
        return
    threading.Thread(
        target=_send,
        args=(event, properties or {}),
        daemon=True,
    ).start()


def _send(event: str, extra: dict) -> None:
    try:
        import json
        import urllib.request
        from importlib.metadata import version as _pkg_version

        try:
            pkg_version = _pkg_version("autofill")
        except Exception:
            pkg_version = "unknown"

        props = {
            "$lib": "autofill",
            "version": pkg_version,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "platform": platform.system().lower(),
            **extra,
        }
        payload = json.dumps({
            "api_key": _POSTHOG_KEY,
            "event": event,
            "distinct_id": _install_id(),
            "properties": props,
        }).encode()
        req = urllib.request.Request(
            f"{_POSTHOG_HOST}/capture/",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
