"""Telegram channel gateway management endpoints.

The gateway itself is a standalone process (scripts/telegram_gateway.py) that
long-polls the Telegram Bot API and talks to ZEVORA over local HTTP. These
endpoints expose its status and lifecycle to the dashboard and let the gateway
register a heartbeat, guarded by a shared token so only the local gateway
process can mark itself connected.
"""
import os
import time
from threading import Lock

from fastapi import HTTPException, Request

import main
from main import app

_gateway_state_lock = Lock()
_gateway_state: dict = {'connected': False, 'last_seen': None, 'started_at': None}


def gateway_heartbeat() -> None:
    """Record a gateway heartbeat (used by the gateway process and tests)."""
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with _gateway_state_lock:
        if not _gateway_state['connected']:
            _gateway_state['started_at'] = now
        _gateway_state['connected'] = True
        _gateway_state['last_seen'] = now


def gateway_disconnect() -> dict:
    with _gateway_state_lock:
        _gateway_state.update({'connected': False, 'last_seen': None, 'started_at': None})
        return {'ok': True, 'connected': False}


def _require_gateway_token(request: Request) -> None:
    expected = os.environ.get('ZEVORA_TELEGRAM_GATEWAY_TOKEN', '')
    provided = request.headers.get('X-ZEVORA-Telegram-Token', '')
    if not expected or provided != expected:
        raise HTTPException(403, {
            'code': 'TELEGRAM_FORBIDDEN',
            'message': 'Gateway token missing or invalid.',
        })


def telegram_bot_configured() -> bool:
    return bool(os.environ.get('ZEVORA_TELEGRAM_BOT_TOKEN'))


@app.get('/api/telegram/status')
def telegram_status():
    with _gateway_state_lock:
        state = dict(_gateway_state)
    return {
        'ok': True,
        'bot_configured': telegram_bot_configured(),
        'gateway_token_configured': bool(os.environ.get('ZEVORA_TELEGRAM_GATEWAY_TOKEN')),
        'gateway': state,
    }


@app.post('/api/telegram/gateway/heartbeat')
def telegram_gateway_heartbeat(request: Request):
    _require_gateway_token(request)
    gateway_heartbeat()
    with _gateway_state_lock:
        state = dict(_gateway_state)
    return {'ok': True, **state}


@app.post('/api/telegram/gateway/disconnect')
def telegram_gateway_disconnect(request: Request):
    _require_gateway_token(request)
    return gateway_disconnect()
