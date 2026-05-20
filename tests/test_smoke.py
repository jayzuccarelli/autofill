"""Smoke tests for pure helpers in autofill.agent."""

import json

import pytest

from autofill import __version__
from autofill.agent import (
    _PROVIDERS,
    _SENSITIVE_FIELD_RE,
    _chunk_text,
    _detect_provider,
    _key_fingerprint,
    _load_corrections,
    _save_corrections,
    cfg,
)


def test_version_string():
    assert isinstance(__version__, str)
    assert __version__


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert _chunk_text("hello world") == ["hello world"]

    def test_empty_text(self):
        assert _chunk_text("") == []

    def test_long_text_splits(self):
        text = "paragraph one.\n\n" + ("a" * cfg.chunk_size) + "\n\nparagraph three."
        chunks = _chunk_text(text)
        assert len(chunks) >= 2
        assert all(c.strip() for c in chunks)

    def test_terminates_on_pathological_input(self):
        # Single long word with no separators — must not loop forever.
        chunks = _chunk_text("x" * (cfg.chunk_size * 3))
        assert len(chunks) >= 2


class TestSensitiveFieldRegex:
    @pytest.mark.parametrize(
        "field",
        ["password", "Password", "PASSWORD", "passcode", "otp", "pin",
         "ssn", "cvv", "cvc", "secret", "passport", "dob",
         "card_number", "cardnumber", "card-number",
         # Underscore-separated forms — these were silently slipping
         # through under the old \b regex because _ is a word char.
         "password_field", "auth_token", "account_number", "bank_routing",
         "social_security", "passport_no", "date_of_birth"],
    )
    def test_matches_sensitive(self, field):
        assert _SENSITIVE_FIELD_RE.search(field), f"expected match: {field!r}"

    @pytest.mark.parametrize(
        "field",
        ["first_name", "email", "phone", "address_line_1", "city", "country"],
    )
    def test_skips_benign(self, field):
        assert not _SENSITIVE_FIELD_RE.search(field), f"unexpected match: {field!r}"


@pytest.fixture
def tmp_corrections(tmp_path, monkeypatch):
    """Redirect cfg.corrections_file to a tmp path despite Config being frozen."""
    path = tmp_path / "corrections.jsonl"
    object.__setattr__(cfg, "corrections_file", path)
    yield path
    object.__setattr__(cfg, "corrections_file", type(cfg).corrections_file)


class TestCorrectionsRoundtrip:
    def test_save_strips_sensitive_then_load_returns_safe_only(self, tmp_corrections):
        _save_corrections(
            "https://example.com/form",
            {
                "first_name": {"agent": "Bob", "user": "Alice"},
                "password": {"agent": "x", "user": "secret"},
                "ssn": {"agent": "1", "user": "123-45-6789"},
            },
        )

        assert tmp_corrections.exists()
        entry = json.loads(tmp_corrections.read_text().strip())
        assert "first_name" in entry["corrections"]
        assert "password" not in entry["corrections"]
        assert "ssn" not in entry["corrections"]
        assert entry["domain"] == "example.com"

        loaded = _load_corrections("https://example.com/form")
        assert "first_name" in loaded
        assert "Alice" in loaded
        assert "secret" not in loaded

    def test_load_returns_empty_when_no_file(self, tmp_path):
        object.__setattr__(cfg, "corrections_file", tmp_path / "missing.jsonl")
        try:
            assert _load_corrections("https://example.com/x") == ""
        finally:
            object.__setattr__(cfg, "corrections_file", type(cfg).corrections_file)

    def test_load_filters_by_domain(self, tmp_corrections):
        _save_corrections(
            "https://a.com/form", {"name": {"agent": "x", "user": "A"}}
        )
        _save_corrections(
            "https://b.com/form", {"name": {"agent": "y", "user": "B"}}
        )

        loaded_a = _load_corrections("https://a.com/other")
        assert "A" in loaded_a
        assert "B" not in loaded_a

    def test_save_skips_when_only_sensitive(self, tmp_corrections):
        _save_corrections(
            "https://example.com/form",
            {"password": {"agent": "x", "user": "y"}},
        )
        assert not tmp_corrections.exists()


class TestDetectProvider:
    def _clear_keys(self, monkeypatch):
        monkeypatch.delenv("AUTOFILL_PROVIDER", raising=False)
        for info in _PROVIDERS.values():
            if info.get("env"):
                monkeypatch.delenv(info["env"], raising=False)

    def test_returns_none_when_no_keys(self, monkeypatch):
        self._clear_keys(monkeypatch)
        assert _detect_provider() is None

    def test_picks_only_present_key(self, monkeypatch):
        self._clear_keys(monkeypatch)
        monkeypatch.setenv(_PROVIDERS["anthropic"]["env"], "test-key")
        assert _detect_provider() == "anthropic"

    def test_autofill_provider_override_wins(self, monkeypatch):
        self._clear_keys(monkeypatch)
        monkeypatch.setenv(_PROVIDERS["browseruse"]["env"], "bu-key")
        monkeypatch.setenv(_PROVIDERS["openai"]["env"], "oa-key")
        monkeypatch.setenv("AUTOFILL_PROVIDER", "openai")
        assert _detect_provider() == "openai"

    def test_override_ignored_when_key_missing(self, monkeypatch):
        self._clear_keys(monkeypatch)
        monkeypatch.setenv(_PROVIDERS["anthropic"]["env"], "ak")
        monkeypatch.setenv("AUTOFILL_PROVIDER", "openai")  # but no OPENAI_API_KEY
        assert _detect_provider() == "anthropic"

    def test_ollama_activates_via_explicit_override(self, monkeypatch):
        # No API key needed for Ollama — opt-in via AUTOFILL_PROVIDER.
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("AUTOFILL_PROVIDER", "ollama")
        assert _detect_provider() == "ollama"

    def test_ollama_never_auto_detected(self, monkeypatch):
        # Without AUTOFILL_PROVIDER=ollama, Ollama is not selected.
        self._clear_keys(monkeypatch)
        assert _detect_provider() is None


class TestKeyFingerprint:
    def test_returns_masked_tail(self, monkeypatch):
        monkeypatch.setenv(_PROVIDERS["anthropic"]["env"], "sk-ant-abcd1234")
        assert _key_fingerprint("anthropic") == "(…1234)"

    def test_empty_when_key_missing(self, monkeypatch):
        monkeypatch.delenv(_PROVIDERS["anthropic"]["env"], raising=False)
        assert _key_fingerprint("anthropic") == ""

    def test_empty_for_keyless_provider(self):
        # Ollama has no env key — fingerprint should be empty.
        assert _key_fingerprint("ollama") == ""

    def test_empty_for_short_key(self, monkeypatch):
        monkeypatch.setenv(_PROVIDERS["openai"]["env"], "ab")
        assert _key_fingerprint("openai") == ""

    def test_strips_whitespace_before_measuring(self, monkeypatch):
        monkeypatch.setenv(_PROVIDERS["openai"]["env"], "  wxyz9876  ")
        assert _key_fingerprint("openai") == "(…9876)"
