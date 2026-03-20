"""Core agent: observe form fields, retrieve context, generate fills."""

import asyncio

from browser_use import Agent, BrowserProfile, ChatBrowserUse

TASK = """
Open https://a16z.fillout.com/t/2dqvGNMYi9us
and fill every applicable field using this synthetic profile (map labels loosely—e.g. "Phone" = telephone):

Contact & identity:
- Full name: Morgan V. Ashford
- First name: Morgan
- Last name: Ashford
- Email: morgan.ashford.test@example.com
- Telephone: +1 555-284-0193

Address:
- Street address / Address line 1: 742 Evergreen Terrace
- Address line 2: Unit 12B
- City: Springfield
- State / Province: IL
- Postal / ZIP code: 62704
- Country: United States

Work:
- Current or most recent job title: Senior Product Analyst
- Current or most recent company: Northbridge Analytics Co.
- Years of experience (if asked as a number): 7
- LinkedIn URL: https://www.linkedin.com/in/morgan-ashford-demo
- Personal website or portfolio: https://portfolio-example.test/morgan-ash

Application-specific (use if fields exist):
- Desired salary / compensation expectation: 145000 USD (or flexible / negotiable if only free text)
- Earliest start date: 2026-04-15
- Work authorization: Yes, authorized to work in the United States
- Relocation: Open to relocation
- How did you hear about us?: Company careers page

Long text boxes (cover letter, summary, comments, "why this role"):
- I am a product analyst with 7+ years turning ambiguous problems into measurable outcomes. I enjoy collaborating across eng, design, and go-to-market, and I am excited to learn how this team ships and iterates. This submission uses placeholder data for testing the application flow.

Rules:
- Prefer selects and radios that match the values above; otherwise choose the closest reasonable option.
- Do not upload real identity documents; skip file uploads if they require real files, or use only clearly dummy filenames if the UI forces a choice.
- Do not click Submit, Apply, Send, or any control that would finalize or send the application.
- When everything reasonable is filled, finish with the done action and say the user should review and submit manually.
"""


async def main() -> None:
    # Uses BROWSER_USE_API_KEY (see https://cloud.browser-use.com/new-api-key)
    llm = ChatBrowserUse()
    browser_profile = BrowserProfile(keep_alive=True, headless=False)
    agent = Agent(task=TASK, llm=llm, browser_profile=browser_profile)
    await agent.run()
    # Keep the process (and usually the browser) alive until the user is done in the window.
    await asyncio.to_thread(
        input,
        "Browser left open — review and submit in the window. Press Enter here to exit when finished. ",
    )


if __name__ == "__main__":
    asyncio.run(main())
