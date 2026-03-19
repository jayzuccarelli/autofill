"""Core agent: observe form fields, retrieve context, generate fills."""

import asyncio

from browser_use import Agent
from langchain_anthropic import ChatAnthropic


TASK = """
Go to https://httpbin.org/forms/post and fill out the form with:

- Customer name: John Doe
- Telephone: +1 555-123-4567
- Email: john.doe@example.com
- Comments: This is a test submission.

Submit the form when done.
"""


async def main() -> None:
    llm = ChatAnthropic(model="claude-opus-4-6")
    agent = Agent(task=TASK, llm=llm)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
