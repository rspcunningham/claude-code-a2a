import os
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from a2a.types import TextPart, FilePart

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

from loguru import logger
from typing import override

# context_id --> ClaudeSDKClient
# note: memory leak, will pile up if not collected
agent_sessions = {}

AGENT_CWD = "/workspace"
UPLOAD_DIR = "/user_uploaded_files"

agent_options = ClaudeCodeOptions(
    system_prompt="You are a friendly assistant - reply to the user in a friendly manner",
    permission_mode="acceptEdits",
    cwd=AGENT_CWD,
)


def process_message_parts(message):
    """Process interleaved message parts and reconstruct user prompt"""
    user_prompt_parts = []

    # Process parts in order to maintain exact positioning
    for part in message.parts:
        # Handle the nested Part structure where the actual content is in part.root
        if hasattr(part, "root"):
            actual_part = part.root
        else:
            actual_part = part

        if isinstance(actual_part, TextPart):
            if hasattr(actual_part, "text"):
                user_prompt_parts.append(actual_part.text)
        elif isinstance(actual_part, FilePart):
            if hasattr(actual_part, "file") and hasattr(actual_part.file, "name"):
                filename = actual_part.file.name
                file_path = f"{AGENT_CWD}/{UPLOAD_DIR}/{filename}"

                # Save the file content (decode from base64)
                import base64


                with open(file_path, "wb") as f:
                    f.write(base64.b64decode(actual_part.file.bytes))

                user_prompt_parts.append(f"[{UPLOAD_DIR}/{filename}]")
                logger.info(f"Saved file: {filename} to {file_path}")

    # Join all parts to reconstruct the original message with file references
    return "".join(user_prompt_parts)


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


class ClaudeAgentExecutor(AgentExecutor):
    @override
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

        # Process message parts to extract text and file information
        user_message = process_message_parts(context.message)

        logger.info(f"Processed message: {user_message}")

        result = await run_agent(user_message, context_id)

        # Create message with context_id
        message = new_agent_text_message(result)
        message.context_id = context_id

        await event_queue.enqueue_event(message)

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("cancel not supported")
