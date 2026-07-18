"""Smoke tests for pure helpers in autofill.agent."""

import json
import os

import pytest

from autofill import __version__
from autofill import agent as agent_mod
from autofill.agent import (
    _PROFILE_FIELDS,
    _PROVIDERS,
    _SENSITIVE_FIELD_RE,
    _apply_profile_edits,
    _chunk_text,
    _cookiejar_to_storage_state,
    _detect_provider,
    _diff_corrections,
    _is_ambient_key,
    _key_fingerprint,
    _llm,
    _load_corrections,
    _normalize_dob,
    _parse_profile,
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
         "social_security", "passport_no", "date_of_birth",
         # Standard autocomplete tokens that keyFor can surface as the key.
         "cc-number", "cc-csc", "cc-exp", "csc", "one-time-code", "bday"],
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

    def test_save_filters_by_label_not_just_key(self, tmp_corrections):
        # Benign key, sensitive label — must still be stripped.
        _save_corrections(
            "https://example.com/form",
            {"field_7": {"label": "Social Security", "agent": "1", "user": "2"}},
        )
        assert not tmp_corrections.exists()

    def test_new_shape_renders_label_and_value(self, tmp_corrections):
        _save_corrections(
            "https://example.com/form",
            {"legal-name": {"label": "Legal Name", "agent": "Jay", "user": "Eugenio"}},
        )
        loaded = _load_corrections("https://example.com/form")
        assert "Legal Name" in loaded  # display label, not the semantic key
        assert "Eugenio" in loaded
        assert "legal-name" not in loaded

    def test_cleared_field_renders_leave_blank(self, tmp_corrections):
        _save_corrections(
            "https://example.com/form",
            {"middle-name": {"label": "Middle Name", "agent": "Q", "user": ""}},
        )
        loaded = _load_corrections("https://example.com/form")
        assert "Middle Name" in loaded
        assert "BLANK" in loaded


class TestDiffCorrections:
    def test_keeps_change_drops_noop_and_unchanged(self):
        agent = {
            "a": {"label": "A", "value": "x"},
            "b": {"label": "B", "value": ""},
            "c": {"label": "C", "value": "same"},
        }
        user = {
            "a": {"label": "A", "value": "y"},       # changed
            "b": {"label": "B", "value": ""},        # no-op (both empty)
            "c": {"label": "C", "value": "same"},    # unchanged
        }
        out = _diff_corrections(agent, user)
        assert set(out) == {"a"}
        assert out["a"] == {"label": "A", "agent": "x", "user": "y"}

    def test_keeps_deletion_as_strongest_signal(self):
        agent = {"phone": {"label": "Phone", "value": "555-1234"}}
        user = {"phone": {"label": "Phone", "value": ""}}  # user cleared it
        out = _diff_corrections(agent, user)
        assert out == {"phone": {"label": "Phone", "agent": "555-1234", "user": ""}}

    def test_user_field_absent_from_baseline_counts_as_new(self):
        # Field first seen on page 2 (no baseline) that the user fills.
        out = _diff_corrections({}, {"extra": {"label": "Extra", "value": "v"}})
        assert out == {"extra": {"label": "Extra", "agent": "", "user": "v"}}


class TestDetectProvider:
    def _clear_keys(self, monkeypatch):
        monkeypatch.delenv("AUTOFILL_PROVIDER", raising=False)
        monkeypatch.delenv("AUTOFILL_OLLAMA_MODEL", raising=False)
        for info in _PROVIDERS.values():
            if info.get("env"):
                monkeypatch.delenv(info["env"], raising=False)
        # Treat nothing as ambient, and pretend .env is empty, so these tests are
        # deterministic regardless of the runner's shell or cwd.
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset())
        monkeypatch.setattr(agent_mod, "_env_file_keys", frozenset)

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

    def test_ollama_never_inferred_from_model_var(self, monkeypatch):
        # A model name is not a provider choice: AUTOFILL_OLLAMA_MODEL alone must
        # not select Ollama, only an explicit AUTOFILL_PROVIDER=ollama does.
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("AUTOFILL_OLLAMA_MODEL", "qwen2.5:14b")
        assert _detect_provider() is None

    def test_explicit_ollama_outranks_a_later_cloud_key(self, monkeypatch):
        # Picking Ollama means keeping data local. A Browser Use key showing up
        # afterwards must not silently reroute profile PII to a cloud model.
        self._clear_keys(monkeypatch)
        monkeypatch.setenv("AUTOFILL_PROVIDER", "ollama")
        monkeypatch.setenv(_PROVIDERS["browseruse"]["env"], "bu-key")
        assert _detect_provider() == "ollama"

    def test_ollama_never_auto_detected(self, monkeypatch):
        # With no override, Ollama is not selected.
        self._clear_keys(monkeypatch)
        assert _detect_provider() is None

    def test_browseruse_beats_ambient_anthropic(self, monkeypatch):
        # Jay's shell: both keys exported, no AUTOFILL_PROVIDER. BROWSER_USE_API_KEY
        # is autofill-exclusive so it's never ambient; ANTHROPIC_API_KEY is shared
        # and gets skipped. Browser Use must win (JAY-93).
        self._clear_keys(monkeypatch)
        bu, ak = _PROVIDERS["browseruse"]["env"], _PROVIDERS["anthropic"]["env"]
        monkeypatch.setenv(bu, "bu-key")
        monkeypatch.setenv(ak, "ak-key")
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset({bu, ak}))
        assert _detect_provider() == "browseruse"

    def test_ambient_key_not_auto_adopted(self, monkeypatch):
        # A key exported in the shell (ambient) must not be auto-selected (JAY-93).
        self._clear_keys(monkeypatch)
        env = _PROVIDERS["anthropic"]["env"]
        monkeypatch.setenv(env, "ak")
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset({env}))
        assert _detect_provider() is None

    def test_explicit_provider_wins_even_if_key_ambient(self, monkeypatch):
        # An explicit AUTOFILL_PROVIDER is honored despite the key being ambient.
        self._clear_keys(monkeypatch)
        env = _PROVIDERS["anthropic"]["env"]
        monkeypatch.setenv(env, "ak")
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset({env}))
        monkeypatch.setenv("AUTOFILL_PROVIDER", "anthropic")
        assert _detect_provider() == "anthropic"


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


class TestIsAmbientKey:
    """A key is ambient only if it's *shared*, from the shell, and not in .env."""

    def _no_env_file(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_env_file_keys", frozenset)

    def test_true_when_shared_key_in_snapshot(self, monkeypatch):
        # ANTHROPIC_API_KEY was in the shell before .env loaded, and Claude reads
        # that var too — so it says nothing about autofill.
        self._no_env_file(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "_AMBIENT_ENV_KEYS", frozenset({"ANTHROPIC_API_KEY"})
        )
        assert _is_ambient_key("anthropic") is True

    def test_false_when_env_name_absent(self, monkeypatch):
        # browseruse key isn't in the snapshot — autofill wrote it to .env.
        self._no_env_file(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "_AMBIENT_ENV_KEYS", frozenset({"ANTHROPIC_API_KEY"})
        )
        assert _is_ambient_key("browseruse") is False

    def test_false_for_exclusive_key_even_when_in_shell(self, monkeypatch):
        # Nothing but autofill reads BROWSER_USE_API_KEY, so a shell export is
        # still a statement about autofill. It must not be dismissed as ambient.
        self._no_env_file(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "_AMBIENT_ENV_KEYS", frozenset({"BROWSER_USE_API_KEY"})
        )
        assert _is_ambient_key("browseruse") is False

    def test_false_when_shared_key_also_in_env_file(self, monkeypatch):
        # Written into autofill's own .env, it's explicit config — not ambient,
        # even though the shell exports the same name.
        monkeypatch.setattr(
            agent_mod, "_AMBIENT_ENV_KEYS", frozenset({"ANTHROPIC_API_KEY"})
        )
        monkeypatch.setattr(
            agent_mod, "_env_file_keys", lambda: frozenset({"ANTHROPIC_API_KEY"})
        )
        assert _is_ambient_key("anthropic") is False

    def test_blank_env_file_line_does_not_count_as_configured(
        self, monkeypatch, tmp_path
    ):
        # `ANTHROPIC_API_KEY=` is how you switch a key off while keeping the line.
        # dotenv_values still reports the name, so a naive membership test would
        # treat it as explicit config and hand the ambient guard back the very key
        # the user just disabled (JAY-93).
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\nOPENAI_API_KEY=oa-key\n")
        monkeypatch.setattr(
            agent_mod,
            "_AMBIENT_ENV_KEYS",
            frozenset({"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}),
        )
        assert agent_mod._env_file_keys() == frozenset({"OPENAI_API_KEY"})
        assert _is_ambient_key("anthropic") is True
        assert _is_ambient_key("openai") is False

    def test_false_for_keyless_provider(self, monkeypatch):
        # Ollama has no API-key var, so it can never be ambient.
        self._no_env_file(monkeypatch)
        monkeypatch.setattr(
            agent_mod, "_AMBIENT_ENV_KEYS", frozenset({"AUTOFILL_PROVIDER"})
        )
        assert _is_ambient_key("ollama") is False


class TestEnvSet:
    """`.env` writes replace and remove, rather than piling up."""

    def test_replaces_rather_than_appends(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("A=1\nAUTOFILL_PROVIDER=openai\nB=2\n")
        agent_mod._env_set("AUTOFILL_PROVIDER", "browseruse")
        assert (tmp_path / ".env").read_text() == (
            "A=1\nB=2\nAUTOFILL_PROVIDER=browseruse\n"
        )

    def test_removes_when_value_is_none(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("A=1\nAUTOFILL_PROVIDER=openai\n")
        agent_mod._env_set("AUTOFILL_PROVIDER", None)
        assert (tmp_path / ".env").read_text() == "A=1\n"

    def test_handles_missing_trailing_newline(self, monkeypatch, tmp_path):
        # Appending to a file with no final newline glues lines together.
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("A=1")
        agent_mod._env_set("B", "2")
        assert (tmp_path / ".env").read_text() == "A=1\nB=2\n"

    def test_creates_file_when_absent(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        agent_mod._env_set("A", "1")
        assert (tmp_path / ".env").read_text() == "A=1\n"

    def test_does_not_match_on_prefix(self, monkeypatch, tmp_path):
        # AUTOFILL_PROVIDER must not eat AUTOFILL_PROVIDER_EXTRA.
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("AUTOFILL_PROVIDER_EXTRA=keep\n")
        agent_mod._env_set("AUTOFILL_PROVIDER", None)
        assert (tmp_path / ".env").read_text() == "AUTOFILL_PROVIDER_EXTRA=keep\n"


class TestProviderReady:
    """`--provider X` is an explicit choice, so an ambient key must not block it."""

    def _clear(self, monkeypatch):
        for info in _PROVIDERS.values():
            if info.get("env"):
                monkeypatch.delenv(info["env"], raising=False)

    def test_true_for_ambient_key_when_named_explicitly(self, monkeypatch):
        # `autofill --provider anthropic <url>` with ANTHROPIC_API_KEY only in the
        # shell must run, not report "Not set up yet". Naming the provider settles
        # the question the ambient guard exists to ask.
        self._clear(monkeypatch)
        ak = _PROVIDERS["anthropic"]["env"]
        monkeypatch.setenv(ak, "ak-key")
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset({ak}))
        monkeypatch.setattr(agent_mod, "_env_file_keys", frozenset)
        assert _is_ambient_key("anthropic") is True  # guard still says ambient...
        assert _detect_provider() is None  # ...so inference declines to guess...
        assert agent_mod._provider_ready("anthropic") is True  # ...but the flag wins

    def test_false_when_key_missing(self, monkeypatch):
        self._clear(monkeypatch)
        assert agent_mod._provider_ready("openai") is False

    def test_true_for_keyless_provider(self, monkeypatch):
        self._clear(monkeypatch)
        assert agent_mod._provider_ready("ollama") is True

    def test_false_for_unknown_provider(self, monkeypatch):
        # Must not read as "no key needed, good to go".
        self._clear(monkeypatch)
        assert agent_mod._provider_ready("gemini") is False


class TestPersistProviderChoice:
    """AUTOFILL_PROVIDER is written only when inference can't reach the choice.

    A stale pointer outranks every key and silently hijacks later runs, so the
    common paths must not create one at all (JAY-93).
    """

    def _setup(self, monkeypatch, tmp_path):
        # cfg is frozen and cfg.env_file is relative, so chdir is how we redirect it.
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AUTOFILL_PROVIDER", raising=False)
        monkeypatch.delenv("AUTOFILL_OLLAMA_MODEL", raising=False)
        for info in _PROVIDERS.values():
            if info.get("env"):
                monkeypatch.delenv(info["env"], raising=False)
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset())
        return tmp_path / ".env"

    def test_writes_nothing_when_inference_agrees(self, monkeypatch, tmp_path):
        # The whole point: picking Browser Use with a Browser Use key present
        # leaves no pointer behind, so there's nothing to go stale.
        env_file = self._setup(monkeypatch, tmp_path)
        monkeypatch.setenv(_PROVIDERS["browseruse"]["env"], "bu-key")
        agent_mod._persist_provider_choice("browseruse")
        assert not env_file.exists()
        assert "AUTOFILL_PROVIDER" not in os.environ

    def test_removes_stale_pointer_inference_outvotes(self, monkeypatch, tmp_path):
        # A keyless AUTOFILL_PROVIDER=openai is dormant, not harmless: inference
        # outvotes it today, but it outranks every key the moment an OPENAI_API_KEY
        # appears. Confirming Browser Use has to clear it, not just ignore it.
        env_file = self._setup(monkeypatch, tmp_path)
        env_file.write_text("AUTOFILL_PROVIDER=openai\nBROWSER_USE_API_KEY=bu-key\n")
        monkeypatch.setenv(_PROVIDERS["browseruse"]["env"], "bu-key")
        monkeypatch.setenv("AUTOFILL_PROVIDER", "openai")
        agent_mod._persist_provider_choice("browseruse")
        assert "AUTOFILL_PROVIDER" not in env_file.read_text()
        assert "BROWSER_USE_API_KEY=bu-key" in env_file.read_text()
        assert "AUTOFILL_PROVIDER" not in os.environ
        # The latent hijack is gone: an OpenAI key appearing no longer flips it.
        monkeypatch.setenv(_PROVIDERS["openai"]["env"], "oa-key")
        assert _detect_provider() == "browseruse"

    def test_writes_pointer_to_break_a_real_tie(self, monkeypatch, tmp_path):
        # OpenAI chosen while a Browser Use key is also present: inference walks
        # registry order and would say browseruse, so the pick must be recorded.
        env_file = self._setup(monkeypatch, tmp_path)
        monkeypatch.setenv(_PROVIDERS["browseruse"]["env"], "bu-key")
        monkeypatch.setenv(_PROVIDERS["openai"]["env"], "oa-key")
        agent_mod._persist_provider_choice("openai")
        assert "AUTOFILL_PROVIDER=openai" in env_file.read_text()
        assert os.environ["AUTOFILL_PROVIDER"] == "openai"

    def test_writes_pointer_for_deliberate_ambient_key(self, monkeypatch, tmp_path):
        # Anthropic picked on purpose while its key is only in the shell:
        # inference skips ambient keys, so record the choice.
        env_file = self._setup(monkeypatch, tmp_path)
        ak = _PROVIDERS["anthropic"]["env"]
        monkeypatch.setenv(ak, "ak-key")
        monkeypatch.setattr(agent_mod, "_AMBIENT_ENV_KEYS", frozenset({ak}))
        agent_mod._persist_provider_choice("anthropic")
        assert "AUTOFILL_PROVIDER=anthropic" in env_file.read_text()


class TestModelOverride:
    """AUTOFILL_*_MODEL env vars override the default model without a code edit."""

    def test_anthropic_env_override(self, monkeypatch):
        monkeypatch.setenv("AUTOFILL_ANTHROPIC_MODEL", "claude-test-xyz")
        assert _llm("anthropic").model == "claude-test-xyz"

    def test_anthropic_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("AUTOFILL_ANTHROPIC_MODEL", raising=False)
        assert _llm("anthropic").model == cfg.anthropic_model


class TestNormalizeDob:
    """`_normalize_dob` coerces common inputs to YYYY-MM-DD, '' , or None."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1990-05-23", "1990-05-23"),
            ("05/23/1990", "1990-05-23"),
            ("May 23, 1990", "1990-05-23"),
            ("23 May 1990", "1990-05-23"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_parses_or_blanks(self, raw, expected):
        assert _normalize_dob(raw) == expected

    def test_none_for_unparseable(self):
        assert _normalize_dob("not a date") is None


class TestParseProfile:
    """`_parse_profile` reads back the `- **Key:** value` lines onboarding writes."""

    def test_roundtrips_written_fields(self, tmp_path):
        p = tmp_path / "profile.md"
        p.write_text(
            "# Jane Doe\n"
            "- **Full name:** Jane Doe\n"
            "- **Date of birth:** 1990-05-23\n"
            "- **Email:** jane@example.com\n"
        )
        object.__setattr__(cfg, "profile", p)
        try:
            parsed = _parse_profile()
        finally:
            object.__setattr__(cfg, "profile", type(cfg).profile)
        assert parsed["Full name"] == "Jane Doe"
        assert parsed["Date of birth"] == "1990-05-23"
        assert parsed["Email"] == "jane@example.com"
        assert "Jane Doe" not in parsed  # the `# heading` line isn't a field

    def test_empty_when_no_file(self, tmp_path):
        object.__setattr__(cfg, "profile", tmp_path / "missing.md")
        try:
            assert _parse_profile() == {}
        finally:
            object.__setattr__(cfg, "profile", type(cfg).profile)


class TestApplyProfileEdits:
    """`autofill setup` updates known fields but never destroys other content."""

    def test_updates_field_and_preserves_extras(self):
        original = (
            "# Jane Doe\n\n"
            "## Contact\n"
            "- **Full name:** Jane Doe\n"
            "- **Email:** jane@old.com\n"
            "- **Nationality:** Italian\n\n"
            "## Summary\n"
            "Builder of things.\n"
        )
        values = {k: "" for k in _PROFILE_FIELDS}
        values["Full name"] = "Jane Doe"
        values["Email"] = "jane@new.com"
        out = _apply_profile_edits(original, values)
        assert "- **Email:** jane@new.com" in out
        assert "jane@old.com" not in out
        assert "- **Nationality:** Italian" in out  # unknown field preserved
        assert "## Summary" in out and "Builder of things." in out
        assert "## Contact" in out

    def test_blank_value_drops_the_field_line(self):
        original = "- **Full name:** Jane\n- **Phone:** 555\n"
        values = {k: "" for k in _PROFILE_FIELDS}
        values["Full name"] = "Jane"  # Phone left blank -> cleared
        out = _apply_profile_edits(original, values)
        assert "- **Full name:** Jane" in out
        assert "Phone" not in out

    def test_appends_newly_set_field(self):
        original = "- **Full name:** Jane\n"
        values = {k: "" for k in _PROFILE_FIELDS}
        values["Full name"] = "Jane"
        values["Email"] = "jane@x.com"
        out = _apply_profile_edits(original, values)
        assert "- **Email:** jane@x.com" in out


class TestCookiejarToStorageState:
    """`_cookiejar_to_storage_state` maps a cookielib jar to Playwright shape."""

    def _cookie(self, **kw):
        from http.cookiejar import Cookie

        defaults = dict(
            version=0, name="sid", value="abc", port=None, port_specified=False,
            domain=".workday.com", domain_specified=True, domain_initial_dot=True,
            path="/", path_specified=True, secure=True, expires=1893456000,
            discard=False, comment=None, comment_url=None, rest={},
        )
        defaults.update(kw)
        # ty can't check **dict unpack against Cookie's typed signature; the
        # runtime values above are correct.
        return Cookie(**defaults)  # ty: ignore[invalid-argument-type]

    def test_basic_fields_map_through(self):
        state = _cookiejar_to_storage_state([self._cookie()])
        assert state["origins"] == []
        (c,) = state["cookies"]
        assert c["name"] == "sid"
        assert c["value"] == "abc"
        assert c["domain"] == ".workday.com"
        assert c["secure"] is True
        assert c["expires"] == 1893456000.0
        assert c["sameSite"] == "Lax"

    def test_session_cookie_gets_minus_one(self):
        state = _cookiejar_to_storage_state([self._cookie(expires=None)])
        assert state["cookies"][0]["expires"] == -1

    def test_httponly_detected_from_rest(self):
        # browser_cookie3 stashes HttpOnly in the cookie's nonstandard attrs.
        on = self._cookie(rest={"HttpOnly": None})
        off = self._cookie(rest={})
        assert _cookiejar_to_storage_state([on])["cookies"][0]["httpOnly"] is True
        assert _cookiejar_to_storage_state([off])["cookies"][0]["httpOnly"] is False

    def test_empty_jar_yields_empty_cookies(self):
        assert _cookiejar_to_storage_state([]) == {"cookies": [], "origins": []}
