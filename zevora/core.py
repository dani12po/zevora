import asyncio, json
import sys
from datetime import datetime, timezone
from pathlib import Path
from fastapi import HTTPException
from agent.config import ROOT
from agent.storage.context_compressor import compress_context

def session_id(): return f"zv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
def save_session(session, messages):
    target=ROOT/'data'/'memory'/'sessions'; target.mkdir(parents=True,exist_ok=True)
    (target/f'{session}.json').write_text(json.dumps({'session_id':session,'updated_at':datetime.now(timezone.utc).isoformat(),'messages':messages[-20:]},ensure_ascii=False),encoding='utf-8')
def compact(messages): return compress_context([f"{role}: {text}" for role,text in messages],max_chars=6000)
async def execute(prompt, project=None):
    # Reuses the FastAPI Agent Core directly; no provider-specific CLI code exists here.
    if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
    from main import TaskRequest, task
    try: return await task(TaskRequest(prompt=prompt,project=project))
    except HTTPException as error: return {'error':str(error.detail)}
def run(prompt, project=None): return asyncio.run(execute(prompt,project))
