from urllib.parse import urlunsplit

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    PREV_AGENT_CARD_WELL_KNOWN_PATH,
)

from claude_agent import ClaudeAgentExecutor
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

INTERNAL_PORT = 9999

skill = AgentSkill(
    id='reply',
    name='Reply',
    description='responds to your message in a thoughtful manner',
    tags=[],
)

base_agent_card = AgentCard(
    name='Agent',
    description='Just an agent',
    url=f'http://localhost:{INTERNAL_PORT}/',
    version='1.0.0',
    default_input_modes=['text'],
    default_output_modes=['text'],
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],
)

request_handler = DefaultRequestHandler(
    agent_executor=ClaudeAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

server = A2AStarletteApplication(
    agent_card=base_agent_card,
    http_handler=request_handler,
)

app = server.build()


async def root_handler(request: Request) -> JSONResponse:
    return JSONResponse({'status': 'ok'})


# Add routes for both GET and POST on root
app.router.routes.extend([
    Route('/', root_handler, methods=['GET']),
    Route('/', root_handler, methods=['POST']),
])


def _select_first_header_value(value: str | None) -> str | None:
    """Return the first comma-separated header value, stripping whitespace."""
    if not value:
        return None
    return value.split(',')[0].strip()


def _build_base_url_from_request(request: Request) -> str:
    """Derive the external base URL for the requesting client."""
    forwarded_host = _select_first_header_value(
        request.headers.get('x-forwarded-host')
    )
    forwarded_proto = _select_first_header_value(
        request.headers.get('x-forwarded-proto')
    )
    forwarded_port = _select_first_header_value(
        request.headers.get('x-forwarded-port')
    )

    if forwarded_host:
        host = forwarded_host
        if ':' not in host and forwarded_port:
            host = f'{host}:{forwarded_port}'
        scheme = forwarded_proto or request.url.scheme
        base = urlunsplit((scheme, host, '', '', ''))
        return base.rstrip('/') + '/'

    return str(request.base_url).rstrip('/') + '/'


def _build_agent_card_for_request(request: Request) -> AgentCard:
    """Create a fresh AgentCard that reflects the request's base URL."""
    external_base_url = _build_base_url_from_request(request)
    return base_agent_card.model_copy(deep=True, update={'url': external_base_url})


async def dynamic_agent_card_handler(request: Request) -> JSONResponse:
    """Serve the agent card using the caller's externally visible base URL."""
    card = _build_agent_card_for_request(request)
    return JSONResponse(
        card.model_dump(
            exclude_none=True,
            by_alias=True,
        )
    )


def _replace_agent_card_routes() -> None:
    """Replace default agent card routes with dynamic versions."""
    card_paths = [
        AGENT_CARD_WELL_KNOWN_PATH,
        PREV_AGENT_CARD_WELL_KNOWN_PATH,
    ]

    def is_agent_card_route(route: Route) -> bool:
        return (
            isinstance(route, Route)
            and route.path in card_paths
            and route.methods
            and 'GET' in route.methods
        ) # type: ignore

    app.router.routes = [
        route for route in app.router.routes
        if not is_agent_card_route(route) # type: ignore
    ]

    for path in card_paths:
        app.router.routes.append(
            Route(path, dynamic_agent_card_handler, methods=['GET'])
        )


_replace_agent_card_routes()


if __name__ == '__main__':
    uvicorn.run("a2a_server:app", host='0.0.0.0', port=INTERNAL_PORT, reload=True)
