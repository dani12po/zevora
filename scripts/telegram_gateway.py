"""Standalone Telegram channel gateway for ZEVORA.

Run it next to the FastAPI app:

    ZEVORA_TELEGRAM_BOT_TOKEN=<token> \
    ZEVORA_GATEWAY_URL=http://127.0.0.1:7432 \
    .venv/bin/python scripts/telegram_gateway.py

The process long-polls the Telegram Bot API (stdlib urllib only) and, for each
private text message, calls ZEVORA's local ``POST /api/chat`` endpoint, then
sends the response back to the chat. Chat identity is kept per Telegram chat so
conversations continue across messages. Zero changes to the core chat loop.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TELEGRAM_API = 'https://api.telegram.org'
POLL_TIMEOUT_SECONDS = 30
ERROR_BACKOFF_SECONDS = 5

ZEVORA_GATEWAY_URL = os.environ.get('ZEVORA_GATEWAY_URL', 'http://127.0.0.1:7432')
TELEGRAM_TOKEN = os.environ.get('ZEVORA_TELEGRAM_BOT_TOKEN', '')
GATEWAY_TOKEN = os.environ.get('ZEVORA_TELEGRAM_GATEWAY_TOKEN', '')


def log(message: str) -> None:
    print(f'[telegram-gateway] {message}', flush=True)


def http_json(url: str, payload: dict | None = None, headers: dict | None = None,
              timeout: int = 60) -> dict:
    """POST JSON (or GET when payload is None) and parse the JSON response."""
    data = None
    request_headers = {'Content-Type': 'application/json', **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=request_headers, method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def telegram(method: str, **params) -> dict:
    url = f'{TELEGRAM_API}/bot{TELEGRAM_TOKEN}/{method}'
    return http_json(url, payload=params, timeout=POLL_TIMEOUT_SECONDS + 15)


def send_message(chat_id: int | str, text: str) -> None:
    # Telegram's hard message cap; chunk long answers.
    for offset in range(0, len(text), 4096):
        telegram('sendMessage', chat_id=chat_id, text=text[offset:offset + 4096])


def zevora_chat(chat_id: int | str, message: str) -> str:
    """Send one turn to ZEVORA's local chat API and return the reply text."""
    request_id = f'tg-{chat_id}-{int(time.time() * 1000)}'
    result = http_json(
        f'{ZEVORA_GATEWAY_URL}/api/chat',
        payload={'message': message, 'conversation_id': f'telegram-{chat_id}',
                 'request_id': request_id},
        headers={'X-ZEVORA-Telegram-Token': GATEWAY_TOKEN} if GATEWAY_TOKEN else None,
    )
    return str(result.get('response') or 'No response was produced.')


def handle_update(update: dict, conversations: dict[int, str]) -> None:
    message = update.get('message')
    if not message or message.get('chat', {}).get('type') != 'private':
        return
    text = (message.get('text') or '').strip()
    chat_id = message['chat']['id']
    if not text:
        return
    if text.startswith('/start'):
        send_message(chat_id, 'ZEVORA gateway connected. Send me a message.')
        return
    try:
        reply = zevora_chat(chat_id, text)
    except Exception as error:  # never let one bad turn kill the poll loop
        log(f'chat turn failed for chat {chat_id}: {error}')
        reply = 'Sorry — ZEVORA could not process that message. Please try again.'
    conversations[chat_id] = f'telegram-{chat_id}'
    send_message(chat_id, reply)


def heartbeat() -> None:
    if GATEWAY_TOKEN:
        try:
            http_json(f'{ZEVORA_GATEWAY_URL}/api/telegram/gateway/heartbeat',
                      payload={}, headers={'X-ZEVORA-Telegram-Token': GATEWAY_TOKEN})
        except Exception as error:
            log(f'heartbeat failed: {error}')


def poll_once(conversations: dict[int, str], offset: int | None = None) -> int | None:
    """One long poll cycle; returns the next update offset."""
    params: dict = {'timeout': POLL_TIMEOUT_SECONDS, 'allowed_updates': ['message']}
    if offset is not None:
        params['offset'] = offset
    payload = telegram('getUpdates', **params)
    for update in payload.get('result', []):
        offset = max(offset or 0, update['update_id']) + 1
        handle_update(update, conversations)
    return offset


def run() -> None:
    if not TELEGRAM_TOKEN:
        print('ZEVORA_TELEGRAM_BOT_TOKEN is required.', file=sys.stderr)
        raise SystemExit(2)
    conversations: dict[int, str] = {}
    offset: int | None = None
    log(f'started; ZEVORA gateway at {ZEVORA_GATEWAY_URL}')
    heartbeat()
    last_beat = time.monotonic()
    while True:
        try:
            offset = poll_once(conversations, offset)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            log(f'poll error: {error}; retrying in {ERROR_BACKOFF_SECONDS}s')
            time.sleep(ERROR_BACKOFF_SECONDS)
        if time.monotonic() - last_beat > 60:
            heartbeat()
            last_beat = time.monotonic()


if __name__ == '__main__':
    run()
