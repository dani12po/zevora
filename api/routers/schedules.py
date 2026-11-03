"""Scheduled tasks API — CRUD plus run history for ZEVORA's built-in scheduler."""
from fastapi import HTTPException, Query
from pydantic import BaseModel, Field

from agent.core.scheduler import SCHEDULE_KINDS
import main
from main import app


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8_000)
    schedule_kind: str
    schedule_value: str = Field(default='', max_length=40)
    project_path: str = Field(default='', max_length=1_000)


class ScheduleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1, max_length=8_000)
    schedule_kind: str | None = None
    schedule_value: str | None = Field(default=None, max_length=40)
    project_path: str | None = Field(default=None, max_length=1_000)
    enabled: bool | None = None


def _validation_error(error: ValueError):
    return HTTPException(422, {'code': 'INVALID_SCHEDULE', 'message': str(error)})


@app.get('/api/schedules')
def list_schedules():
    return main.scheduled_task_store.list_tasks()


@app.post('/api/schedules')
def create_schedule(body: ScheduleCreateRequest):
    if body.schedule_kind not in SCHEDULE_KINDS:
        raise HTTPException(
            422, {'code': 'INVALID_SCHEDULE',
                  'message': f'schedule_kind must be one of {list(SCHEDULE_KINDS)}'},
        )
    try:
        return main.scheduled_task_store.create_task(
            body.name, body.prompt, body.schedule_kind,
            body.schedule_value, body.project_path,
        )
    except ValueError as error:
        raise _validation_error(error) from error


@app.get('/api/schedules/{task_id}')
def get_schedule(task_id: int):
    task = main.scheduled_task_store.get_task(task_id)
    if not task:
        raise HTTPException(404, 'Scheduled task not found')
    return task


@app.patch('/api/schedules/{task_id}')
def update_schedule(task_id: int, body: ScheduleUpdateRequest):
    if not main.scheduled_task_store.get_task(task_id):
        raise HTTPException(404, 'Scheduled task not found')
    updates = body.model_dump(exclude_none=True)
    if 'schedule_kind' in updates and updates['schedule_kind'] not in SCHEDULE_KINDS:
        raise HTTPException(
            422, {'code': 'INVALID_SCHEDULE',
                  'message': f'schedule_kind must be one of {list(SCHEDULE_KINDS)}'},
        )
    try:
        return main.scheduled_task_store.update_task(task_id, **updates)
    except ValueError as error:
        raise _validation_error(error) from error


@app.delete('/api/schedules/{task_id}')
def delete_schedule(task_id: int):
    if not main.scheduled_task_store.delete_task(task_id):
        raise HTTPException(404, 'Scheduled task not found')
    return {'ok': True, 'deleted': task_id}


@app.get('/api/schedules/{task_id}/runs')
def schedule_runs(task_id: int, limit: int = Query(default=20, ge=1, le=100)):
    if not main.scheduled_task_store.get_task(task_id):
        raise HTTPException(404, 'Scheduled task not found')
    return main.scheduled_task_store.run_history(task_id, limit)


@app.post('/api/schedules/{task_id}/run-now')
def run_schedule_now(task_id: int):
    """Fire one scheduled task immediately, bypassing its schedule."""
    task = main.scheduled_task_store.get_task(task_id)
    if not task:
        raise HTTPException(404, 'Scheduled task not found')
    from agent.core.scheduler import _now
    from main import scheduler
    try:
        result = scheduler.runner(task)
        main.scheduled_task_store.record_run(
            task_id, 'success', result, _now().isoformat(), _now().isoformat(),
        )
        return {'ok': True, 'status': 'success', 'result': result}
    except Exception as error:
        main.scheduled_task_store.record_run(
            task_id, 'failed', f'{type(error).__name__}: {error}',
            _now().isoformat(), _now().isoformat(),
        )
        return {'ok': False, 'status': 'failed',
                'result': f'{type(error).__name__}: {error}'}
