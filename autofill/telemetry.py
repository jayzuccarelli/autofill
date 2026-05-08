"""Anonymous, opt-out usage telemetry.

To disable: set ``AUTOFILL_TELEMETRY=0`` in ``.env`` or your environment.

Events sent (no PII):
  install            — first-time setup completed
  run / complete     — form fill started / finished
  timeout            — agent hit the time limit
  corrections_saved  — user corrections recorded

All events include: tool version, Python version, OS platform.
Nothing is sent when ``AUTOFILL_TELEMETRY=0`` or the PostHog key is a placeholder.
"""

import os
import platform
import sys
import threading
import uuid
from pathlib import Path

# ── PostHog setup ────────────────────────────────────────────────────────────
# Public PostHog Project API key — write-only, safe to commit.
# Users opt out via AUTOFILL_TELEMETRY=0.
_POSTHOG_KEY = "phc_nrQoCoVSPLxMjGfXNXSjsBuXRdpGFnV9CuD6BYRahruy"
_POSTHOG_HOST = "https://us.i.posthog.com"
# Hard cap on events per CLI invocation — guards against runaway loops
# inflating event volume from a single install.
_MAX_EVENTS_PER_PROCESS = 25
_event_count = 0
_event_count_lock = threading.Lock()
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
    """Fire-and-forget telemetry ping.  Never raises, never blocks the caller."""
    if not _enabled():
        return
    global _event_count
    with _event_count_lock:
        if _event_count >= _MAX_EVENTS_PER_PROCESS:
            return
        _event_count += 1
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
