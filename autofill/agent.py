"""Core agent: observe form fields, retrieve context, generate fills."""

import asyncio

import browser_use as bu

from autofill.knowledge import build_index, retrieve

url = "https://a16z.fillout.com/t/2dqvGNMYi9us"

_RETRIEVE_QUERY = (
    "contact name email phone address work experience job title company "
    "education skills cover letter bio summary salary start date "
    "work authorization relocation"
)

_RULES = """
Rules:
- Map field labels loosely (e.g. "Phone" = telephone, "Bio" = summary).
- Prefer selects and radios that match the values above; otherwise choose the closest reasonable option.
- Try to answer all questions; if you genuinely don't know, say so; if you can make a reasonable guess, do so.
- For longer free-text fields write a few sentences consistent with the profile above.
- Do not upload real identity documents; skip file uploads that require real files.
- Do not click Submit, Apply, Send, or any control that finalizes or sends the application.
- When everything reasonable is filled, use the done action and tell the user to review and submit manually.
"""


def build_task(target_url: str) -> str:
    build_index()
    context = retrieve(_RETRIEVE_QUERY)
    if not context:
        raise RuntimeError(
            "knowledge/ is empty — run onboarding first:\n"
            "  uv run python -m autofill.onboarding\n\n"
            "Then drop any extra documents (resume.pdf, cover_letter.txt, etc.) "
            "into knowledge/ and rebuild the index:\n"
            "  uv run python -m autofill.knowledge"
        )
    return (
        f"Open {target_url} and fill every applicable field using the profile "
        "information below.\n\n"
        "--- PROFILE & DOCUMENTS ---\n"
        f"{context}\n"
        "--- END PROFILE ---\n"
        f"{_RULES}"
    )


async def main() -> None:
    task = build_task(url)
    # Uses BROWSER_USE_API_KEY (see https://cloud.browser-use.com/new-api-key)
    llm = bu.ChatBrowserUse()
    browser_profile = bu.BrowserProfile(keep_alive=True, headless=False)
    agent = bu.Agent(task=task, llm=llm, browser_profile=browser_profile)
    await agent.run()
    # Keep the process (and usually the browser) alive until the user is done.
    await asyncio.to_thread(
        input,
        "Browser left open — review and submit in the window. Press Enter here to exit when finished. ",
    )


if __name__ == "__main__":
    asyncio.run(main())
