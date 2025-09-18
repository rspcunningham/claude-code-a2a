import json
import logging
import os
from datetime import datetime, timezone

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def _configure_logging() -> logging.Logger:
    level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s %(message)s')
    return logging.getLogger('heartbeat_receiver')


logger = _configure_logging()


async def heartbeat_handler(request: Request) -> JSONResponse:
    body_bytes = await request.body()
    payload: dict[str, object] | None
    if body_bytes:
        try:
            payload = json.loads(body_bytes)
        except json.JSONDecodeError:
            payload = {'raw_body': body_bytes.decode('utf-8', 'replace')}
    else:
        payload = None

    agent = None
    url = None
    if isinstance(payload, dict):
        agent = payload.get('agent')
        url = payload.get('url')

    logger.info(
        'Heartbeat received at %s agent=%s url=%s payload=%s',
        datetime.now(timezone.utc).isoformat(),
        agent,
        url,
        payload,
    )
    return JSONResponse({'status': 'received'})


app = Starlette(routes=[Route('/heartbeat', heartbeat_handler, methods=['POST'])])


if __name__ == '__main__':
    import uvicorn

    port = int(os.getenv('HEARTBEAT_PORT', '8080'))
    uvicorn.run('heartbeat_receiver:app', host='0.0.0.0', port=port)
