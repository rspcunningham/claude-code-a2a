import os
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from agent_executor import (
    HelloWorldAgentExecutor
)

PORT = int(os.environ.get('PORT', '9999'))

skill = AgentSkill(
    id='reply',
    name='Reply',
    description='responds to your message in a thoughtful manner',
    tags=['reply'],
    examples=['That\'s a great question!'],
)

public_agent_card = AgentCard(
    name='Hello World Agent',
    description='Just a hello world agent',
    url=f'http://localhost:{PORT}/',
    version='1.0.0',
    default_input_modes=['text'],
    default_output_modes=['text'],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill]
)

request_handler = DefaultRequestHandler(
    agent_executor=HelloWorldAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(
    agent_card=public_agent_card,
    http_handler=request_handler
)

app = server.build()

if __name__ == '__main__':
    uvicorn.run("a2a_server:app", host='0.0.0.0', port=PORT, reload=True)
