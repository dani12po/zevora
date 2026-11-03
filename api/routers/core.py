"""Core gateway endpoints: dashboard, health, shutdown, rate limiting, error contract."""
import asyncio
import hmac
import os
import time
from collections import deque
from threading import Lock

import main
from fastapi import Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent.config import ROOT
from zevora.version import __version__

from main import app

# ── Lightweight in-process rate limiter ────────────────────────────────────
# Protects expensive endpoints (chat, agent planning, provider calls) from
# runaway client loops. Localhost-first tool: generous budget, sliding window
# per client IP, no external dependency. Health/static endpoints exempt.
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get('ZEVORA_RATE_LIMIT', '60'))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get('ZEVORA_RATE_LIMIT_WINDOW', '60'))
RATE_LIMIT_PATH_PREFIXES = ('/api/chat', '/api/agent')
_rate_limit_events: dict[str, deque] = {}
_rate_limit_lock = Lock()


@app.middleware('http')
async def rate_limit_expensive_endpoints(request: Request, call_next):
    path = request.url.path
    if main.RATE_LIMIT_MAX_REQUESTS > 0 and path.startswith(main.RATE_LIMIT_PATH_PREFIXES):
        client = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        with main._rate_limit_lock:
            window = main._rate_limit_events.setdefault(client, deque())
            while window and window[0] <= now - main.RATE_LIMIT_WINDOW_SECONDS:
                window.popleft()
            if len(window) >= main.RATE_LIMIT_MAX_REQUESTS:
                return JSONResponse(
                    status_code=429,
                    content={'code': 'RATE_LIMITED',
                             'message': 'Too many requests; slow down and retry shortly.'},
                    headers={'Retry-After': str(int(main.RATE_LIMIT_WINDOW_SECONDS))},
                )
            window.append(now)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def api_validation_error(_: Request, error: RequestValidationError):
    details = [
        {key: value for key, value in item.items() if key not in {'ctx', 'input'}}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={
        'ok': False,
        'error': {
            'code': 'VALIDATION_ERROR',
            'message': 'Request validation failed.',
            'details': details,
        },
    })


@app.exception_handler(HTTPException)
async def api_http_error(_: Request, error: HTTPException):
    """Return machine-readable failures without affecting the gateway process."""
    detail = error.detail
    message = detail.get('message') if isinstance(detail, dict) else str(detail)
    code = (detail.get('code') if isinstance(detail, dict) else None) or (
        'AI_EXECUTION_ERROR' if error.status_code >= 500 else 'REQUEST_ERROR'
    )
    error_payload = {'code': code, 'message': message}
    if isinstance(detail, dict):
        error_payload.update({
            key: value for key, value in detail.items()
            if key not in {'code', 'message'}
        })
    return JSONResponse(
        status_code=error.status_code,
        content={'ok': False, 'error': error_payload},
    )

@app.exception_handler(Exception)
async def api_unexpected_error(_: Request, error: Exception):
    # The gateway logs the full error; never surface raw Python internals to users.
    return JSONResponse(status_code=500, content={
        'ok': False,
        'error': {'code': 'INTERNAL_ERROR',
                  'message': 'An unexpected gateway error occurred. Retry the request; restart the gateway if it continues.'},
    })


def _dashboard_response():
    from fastapi.responses import FileResponse
    return FileResponse(
        ROOT / 'static' / 'index.html',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


@app.get('/')
def dashboard():
    return _dashboard_response()
@app.get('/health')
def gateway_health(): return {'ok':True,'status':'ok','service':'zevora','version':__version__,'gateway':'running'}
def _schedule_shutdown():
    asyncio.get_running_loop().call_later(
        .2, lambda: os.kill(os.getpid(), __import__('signal').SIGINT)
    )


main._schedule_shutdown = _schedule_shutdown
@app.post('/shutdown')
async def shutdown_gateway(x_zevora_shutdown_token: str | None = Header(default=None)):
    expected = os.environ.get('ZEVORA_SHUTDOWN_TOKEN', '')
    if not expected or not x_zevora_shutdown_token or not hmac.compare_digest(
        x_zevora_shutdown_token, expected
    ):
        raise HTTPException(403, {
            'code': 'SHUTDOWN_FORBIDDEN',
            'message': 'A valid gateway controller token is required.',
        })
    main._schedule_shutdown()
    return {'status':'stopping'}
