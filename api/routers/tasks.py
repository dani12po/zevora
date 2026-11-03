"""Task execution endpoint."""
from main import app
from api.orchestrators import task
from api.schemas import TaskRequest

@app.post('/api/task')
async def task_endpoint(body: TaskRequest):
    return await task(body)

