from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from claude_code_sdk import ClaudeCodeOptions, query

async def run_agent(user_message: str):
    options = ClaudeCodeOptions(
        system_prompt="You are an expert Python developer",
        permission_mode='acceptEdits',
        cwd="."
    )

    messages = []
    async for message in query(
        prompt=user_message,
        options=options
    ):
        messages.append(message)

    # Get the final message (ResultMessage) and extract the result content
    return messages[-1].result


class HelloWorldAgentExecutor(AgentExecutor):
    """Test AgentProxy Implementation."""

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

        result = await run_agent(user_message)

        # Create message with context_id
        message = new_agent_text_message(result)
        message.context_id = context_id

        await event_queue.enqueue_event(message)

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')
