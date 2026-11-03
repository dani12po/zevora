"""Telegram channel gateway management endpoints.

The gateway itself is a standalone process (scripts/telegram_gateway.py) that
long-polls the Telegram Bot API and talks to ZEVORA over local HTTP. These
endpoints expose its status and lifecycle to the dashboard and let the gateway
register a heartbeat, guarded by a shared token so only the local gateway
process can mark itself connected.

Configuration is persisted to config/telegram.json so users never need to
touch .env — everything is settable from the dashboard.
"""
import json
import os
import secrets
import time
from pathlib import Path
from threading import Lock

from fastapi import HTTPException, Request
from pydantic import BaseModel

import main
from main import app

# ── Config persistence ────────────────────────────────────────────────────────
_TELEGRAM_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'config' / 'telegram.json'
_config_lock = Lock()


def _load_config() -> dict:
    """Load telegram config from file, falling back to environment variables."""
    try:
        if _TELEGRAM_CONFIG_FILE.exists():
            data = json.loads(_TELEGRAM_CONFIG_FILE.read_text(encoding='utf-8'))
        else:
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    # Env vars are the fallback if no config file exists yet
    return {
        'bot_token':     data.get('bot_token')     or os.environ.get('ZEVORA_TELEGRAM_BOT_TOKEN', ''),
        'gateway_token': data.get('gateway_token') or os.environ.get('ZEVORA_TELEGRAM_GATEWAY_TOKEN', ''),
        'gateway_url':   data.get('gateway_url')   or os.environ.get('ZEVORA_GATEWAY_URL', 'http://127.0.0.1:7432'),
        'allowed_users': data.get('allowed_users', []),
        'enabled':       data.get('enabled', False),
    }


def _save_config(cfg: dict) -> None:
    _TELEGRAM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TELEGRAM_CONFIG_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
    tmp.replace(_TELEGRAM_CONFIG_FILE)
    # Inject into running process environment so the gateway process picks up
    # the values without a restart
    if cfg.get('bot_token'):
        os.environ['ZEVORA_TELEGRAM_BOT_TOKEN'] = cfg['bot_token']
    if cfg.get('gateway_token'):
        os.environ['ZEVORA_TELEGRAM_GATEWAY_TOKEN'] = cfg['gateway_token']
    if cfg.get('gateway_url'):
        os.environ['ZEVORA_GATEWAY_URL'] = cfg['gateway_url']

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


# ── Dashboard config endpoints ────────────────────────────────────────────────

class TelegramConfigRequest(BaseModel):
    bot_token:     str | None = None
    gateway_token: str | None = None
    gateway_url:   str | None = None
    allowed_users: list[str] | None = None
    enabled:       bool | None = None
    generate_token: bool = False  # auto-generate a gateway token


@app.get('/api/telegram/config')
def get_telegram_config():
    """Return current Telegram config — bot token is masked for display."""
    with _config_lock:
        cfg = _load_config()
    bot = cfg.get('bot_token', '')
    masked_bot = ('*' * (len(bot) - 6) + bot[-6:]) if len(bot) > 6 else ('*' * len(bot))
    gw = cfg.get('gateway_token', '')
    masked_gw = ('*' * (len(gw) - 4) + gw[-4:]) if len(gw) > 4 else ('*' * len(gw))
    return {
        'ok': True,
        'enabled':               cfg.get('enabled', False),
        'bot_token_set':         bool(bot),
        'bot_token_masked':      masked_bot,
        'gateway_token_set':     bool(gw),
        'gateway_token_masked':  masked_gw,
        'gateway_url':           cfg.get('gateway_url', 'http://127.0.0.1:7432'),
        'allowed_users':         cfg.get('allowed_users', []),
    }


@app.post('/api/telegram/config')
def update_telegram_config(body: TelegramConfigRequest):
    """Save Telegram config from the dashboard — no .env editing required."""
    with _config_lock:
        cfg = _load_config()

        if body.generate_token:
            cfg['gateway_token'] = secrets.token_hex(24)
        elif body.gateway_token is not None:
            cfg['gateway_token'] = body.gateway_token.strip()

        if body.bot_token is not None:
            t = body.bot_token.strip()
            if t and ':' not in t:
                raise HTTPException(400, {
                    'code': 'INVALID_BOT_TOKEN',
                    'message': 'Bot token should look like 123456:ABC-... (get it from @BotFather).',
                })
            cfg['bot_token'] = t

        if body.gateway_url is not None:
            u = body.gateway_url.strip().rstrip('/')
            if u and not u.startswith(('http://', 'https://')):
                raise HTTPException(400, {
                    'code': 'INVALID_GATEWAY_URL',
                    'message': 'Gateway URL must start with http:// or https://',
                })
            cfg['gateway_url'] = u or 'http://127.0.0.1:7432'

        if body.allowed_users is not None:
            cfg['allowed_users'] = [u.strip().lstrip('@') for u in body.allowed_users if u.strip()]

        if body.enabled is not None:
            cfg['enabled'] = body.enabled

        _save_config(cfg)

    return {
        'ok': True,
        'enabled':           cfg.get('enabled', False),
        'bot_token_set':     bool(cfg.get('bot_token')),
        'gateway_token_set': bool(cfg.get('gateway_token')),
        'gateway_token':     cfg.get('gateway_token', ''),  # returned once so user can copy
        'gateway_url':       cfg.get('gateway_url'),
        'allowed_users':     cfg.get('allowed_users', []),
    }


@app.delete('/api/telegram/config')
def reset_telegram_config():
    """Clear all saved Telegram config."""
    with _config_lock:
        if _TELEGRAM_CONFIG_FILE.exists():
            _TELEGRAM_CONFIG_FILE.unlink()
    for key in ('ZEVORA_TELEGRAM_BOT_TOKEN', 'ZEVORA_TELEGRAM_GATEWAY_TOKEN'):
        os.environ.pop(key, None)
    return {'ok': True, 'cleared': True}
