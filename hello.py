import asyncio
from claude_code_sdk import query, ClaudeCodeOptions

async def main():
    options = ClaudeCodeOptions(
        system_prompt="You are an expert Python developer",
        permission_mode='acceptEdits',
        cwd="./app"
    )

    async for message in query(
        prompt="Create a Python web server",
        options=options
    ):
        print(message)


asyncio.run(main())
