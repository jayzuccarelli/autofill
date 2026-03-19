"""Core agent: observe form fields, retrieve context, generate fills."""

import asyncio

from browser_use import Agent
from langchain_anthropic import ChatAnthropic


DUMMY_PROFILE = {
    "name": "John Doe",
    "email": "john.doe@example.com",
    "phone": "+1 555-123-4567",
    "linkedin": "https://linkedin.com/in/johndoe",
    "github": "https://github.com/johndoe",
    "location": "San Francisco, CA",
    "bio": "Software engineer with 5 years of experience building web applications.",
    "goal": "To build impactful products at the intersection of AI and developer tooling.",
    "project": (
        "I built an open-source CLI tool that uses LLMs to automatically fill out "
        "forms and job applications, saving hours of repetitive data entry."
    ),
}

TASK = f"""
Go to https://httpbin.org/forms/post and fill out the form using this profile:

Name: {DUMMY_PROFILE["name"]}
Email: {DUMMY_PROFILE["email"]}
Phone: {DUMMY_PROFILE["phone"]}

For any open-ended fields like comments or notes, use:
"{DUMMY_PROFILE["bio"]}"

Submit the form when all fields are filled.
"""


async def main() -> None:
    llm = ChatAnthropic(model="claude-opus-4-6")
    agent = Agent(task=TASK, llm=llm)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
