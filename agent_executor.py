import os
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

from loguru import logger

# context_id --> ClaudeSDKClient
# note: memory leak, will pile up if not collected
agent_sessions = {}

agent_options = ClaudeCodeOptions(
    system_prompt="You are a friendly assistant - reply to the user in a friendly manner",
    permission_mode='acceptEdits',
    cwd="/workspace"
)

async def run_agent(user_message: str, context_id: str):
    # Ensure workspace directory exists
    os.makedirs("/workspace", exist_ok=True)

    if context_id not in agent_sessions:
        logger.info(f"Creating new agent session for context_id: {context_id}")
        agent_sessions[context_id] = ClaudeSDKClient(agent_options)
        await agent_sessions[context_id].connect()
    else:
        logger.info(f"Reusing existing agent session for context_id: {context_id}")

    await agent_sessions[context_id].query(user_message)

    messages = []
    async for message in agent_sessions[context_id].receive_response():
        messages.append(message)

    # Get the final message (ResultMessage) and extract the result content
    return messages[-1].result


class AgentExecutorImplementation(AgentExecutor):

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Generate context_id if not provided
        context_id = context.context_id or str(uuid4())

        print(f"Executing context_id: {context_id}")
        print(f"Message: {context.message}")

        if context.message is None:
            raise ValueError("Message is None")

        user_message = context.message.parts[0].root.text

        result = await run_agent(user_message, context_id)

        # Create message with context_id
        message = new_agent_text_message(result)
        message.context_id = context_id

        await event_queue.enqueue_event(message)

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')
