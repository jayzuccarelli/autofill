"""Interactive onboarding: collect the user's profile and save to knowledge/profile.md."""

from __future__ import annotations

from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
PROFILE_PATH = KNOWLEDGE_DIR / "profile.md"

_QUESTIONS: list[tuple[str, str, bool]] = [
    # (key, label, required)
    ("full_name",   "Full name",                                          True),
    ("email",       "Email address",                                      True),
    ("phone",       "Phone number",                                       True),
    ("street",      "Street address",                                     False),
    ("city",        "City",                                               False),
    ("state",       "State / Province",                                   False),
    ("zip",         "ZIP / Postal code",                                  False),
    ("country",     "Country",                                            False),
    ("job_title",   "Current or most recent job title",                   False),
    ("company",     "Current or most recent company",                     False),
    ("years_exp",   "Years of experience",                                False),
    ("linkedin",    "LinkedIn URL",                                       False),
    ("website",     "Personal website or portfolio URL",                  False),
    ("github",      "GitHub URL",                                         False),
    ("salary",      "Desired salary (e.g. 120000 USD or 'negotiable')",   False),
    ("start_date",  "Earliest start date (e.g. 2026-06-01)",              False),
    ("work_auth",   "Work authorization status",                          False),
    ("relocation",  "Open to relocation? (Yes / No / Open to discuss)",   False),
    ("skills",      "Key skills, comma-separated",                        False),
    ("bio",         "Short bio / cover letter paragraph (a few sentences)", False),
]


def _ask(label: str, required: bool) -> str:
    suffix = "" if required else " (optional, press Enter to skip)"
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if val or not required:
            return val
        print("  This field is required.")


def run() -> None:
    print("=== autofill onboarding ===")
    print(f"Your profile will be saved to: {PROFILE_PATH}")
    print("You can edit it later, or add documents (resume.pdf, cover_letter.txt, etc.)")
    print("to the knowledge/ folder. Required fields are marked.\n")

    answers: dict[str, str] = {}
    for key, label, required in _QUESTIONS:
        val = _ask(label, required)
        if val:
            answers[key] = val

    # -----------------------------------------------------------------------
    # Build markdown
    # -----------------------------------------------------------------------
    lines: list[str] = ["# User Profile\n"]

    def section(title: str, keys: list[str]) -> None:
        items = [(k, v) for k, v in answers.items() if k in keys]
        if not items:
            return
        lines.append(f"\n## {title}\n")
        key_to_label = {k: lbl for k, lbl, _ in _QUESTIONS}
        for k, v in items:
            lines.append(f"- {key_to_label[k]}: {v}")

    section("Contact & Identity", ["full_name", "email", "phone"])
    section("Address", ["street", "city", "state", "zip", "country"])
    section("Work", ["job_title", "company", "years_exp", "linkedin", "website", "github"])
    section("Application Preferences", ["salary", "start_date", "work_auth", "relocation"])

    if "skills" in answers:
        lines.append("\n## Skills\n")
        lines.append(answers["skills"])

    if "bio" in answers:
        lines.append("\n## Bio / Cover Letter\n")
        lines.append(answers["bio"])

    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    PROFILE_PATH.write_text("\n".join(lines) + "\n")

    print(f"\nProfile saved to {PROFILE_PATH}")
    print("\nNext steps:")
    print("  1. Drop any extra documents into knowledge/  (resume.pdf, projects.md, etc.)")
    print("  2. Build the index:  uv run python -m autofill.knowledge")
    print("  3. Run autofill:     uv run python autofill/agent.py")


if __name__ == "__main__":
    run()
