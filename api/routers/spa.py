"""SPA catch-all fallback — must be registered LAST."""
from fastapi import HTTPException
from main import app

from api.routers.core import _dashboard_response

# ── SPA fallback — MUST be the very last route registered ───────────────────
# Any GET that isn't /api/... or /static/... serves index.html so the
# client-side router handles /settings, /providers, /chats, etc.
@app.get('/{full_path:path}')
def spa_fallback(full_path: str):
    if full_path.startswith('api/') or full_path.startswith('static/'):
        raise HTTPException(404, 'Not found')
    return _dashboard_response()
