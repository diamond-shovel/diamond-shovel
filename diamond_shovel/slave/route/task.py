import multiprocessing
import uuid
from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel
from websocket import WebSocket

from diamond_shovel.function.task import WorkerPool, TaskContext
from diamond_shovel.plugins.events import TaskLogEvent, TaskWorkerStateChangedEvent, wait_event, TaskEvent, \
    TaskFinishedEvent
from diamond_shovel.utils.func import async_helper

router = APIRouter(prefix="/task", tags=["task"])

scan_session = {}
workers = WorkerPool()


class TargetRequest(BaseModel):
    companies: list[str] = []
    domains: list[str] = []
    ips: list[str] = []

@router.put('/')
def new_task(target: Annotated[TargetRequest, Body(embed=True)]):
    scan_id = uuid.uuid4()
    ctx = TaskContext()

    scan_session[scan_id] = {
        "ctx": ctx,
        "state": "created"
    }

    ctx['scan_id'] = scan_id

    ctx['target_companies'] = target.companies
    ctx['target_domains'] = target.domains
    ctx['target_ips'] = target.ips

    return {"scan_id": scan_id}

@router.get('/{scan_id}')
async def get_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        return {"error": "Scan not found"}

    return {
        "state": scan_session[scan_id]["state"],
        "result": await scan_session[scan_id]["ctx"].get_all_results(),
        "log": await scan_session[scan_id]["ctx"].get_log()
    }

@router.delete('/{scan_id}')
def delete_task(scan_id: uuid.UUID):
    if scan_id in scan_session:
        if scan_session[scan_id]["state"] == "running":
            scan_session[scan_id]["loop"].stop()

        del scan_session[scan_id]

@router.post('/{scan_id}')
def update_task_args(params: dict, scan_id: uuid.UUID):
    if scan_id not in scan_session:
        return {"error": "Scan not found"}

    for key, value in params.items():
        scan_session[scan_id]["ctx"][key] = value

@router.get('/{scan_id}/start')
def start_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        return {"error": "Scan session not found"}

    async def task_runner():
        await workers.run_worker(scan_session[scan_id]["ctx"])
        scan_session[scan_id]["state"] = "finished"
    loop = async_helper.threaded_async_run(task_runner())
    scan_session[scan_id]["loop"] = loop
    scan_session[scan_id]["state"] = "running"

@router.websocket('/ws/{scan_id}')
def update_task_events(scan_id: uuid.UUID, websocket: WebSocket):
    while scan_session[scan_id]["state"] == "running":
        dispatch_monitored_task_events(websocket, scan_session[scan_id])
    websocket.close()

def dispatch_monitored_task_events(ws, scan_session):
    handlers = {
        TaskLogEvent: send_log_notification,
        TaskWorkerStateChangedEvent: send_task_progress,
        TaskFinishedEvent: send_task_finish
    }
    event = wait_event(TaskEvent, lambda evt: evt.__class__ in handlers and evt.task_context == scan_session["ctx"])
    handlers[event.__class__](ws, event, scan_session)

def send_log_notification(ws: WebSocket, event: TaskLogEvent, _):
    ws.send_text(f'{{"action":"log", "body":"{event.log_line}"}}')

def send_task_progress(ws: WebSocket, event: TaskWorkerStateChangedEvent, _):
    finished_tasks = len([task for task, state in event.handler_states.items() if state["state"] == "done" or state["state"] == "cancelled"])
    all_tasks = len(event.handler_states)
    ws.send_text(f'{{"action":"state", "finished": {finished_tasks}, "all": {all_tasks}}}')

def send_task_finish(ws: WebSocket, event: TaskFinishedEvent, session):
    ws.send_text(f'{{"action":"finished"}}')
    session["state"] = "finished"

@router.get('/')
def all_tasks():
    return list(scan_session.keys())
