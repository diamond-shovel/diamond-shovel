import multiprocessing
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel
from websocket import WebSocket

from diamond_shovel.function.task import WorkerPool, TaskContext
from diamond_shovel.utils import async_helper

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
        "state": "created",
        "log_condition": multiprocessing.Condition()
    }

    ctx['scan_id'] = scan_id

    ctx['target_companies'] = target.companies
    ctx['target_domains'] = target.domains
    ctx['target_ips'] = target.ips

    return {"scan_id": scan_id}

@router.get('/{scan_id}')
async def get_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")

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
        raise HTTPException(status_code=404, detail="Scan session not found")

    for key, value in params.items():
        scan_session[scan_id]["ctx"][key] = value

@router.get('/{scan_id}/start')
def start_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    def log_hook(log):
        scan_session[scan_id]["last_line"] = log
        scan_session[scan_id]["log_condition"].acquire()
        scan_session[scan_id]["log_condition"].notify()
        scan_session[scan_id]["log_condition"].release()

    async def task_runner():
        await workers.run_worker(scan_session[scan_id]["ctx"], loguru_handler=log_hook)
        scan_session[scan_id]["state"] = "finished"
    loop = async_helper.threaded_async_run(task_runner())
    scan_session[scan_id]["loop"] = loop
    scan_session[scan_id]["state"] = "running"

@router.websocket('/ws/{scan_id}')
def poll_logs(scan_id: uuid.UUID, websocket: WebSocket):
    if scan_id not in scan_session:
        raise HTTPException(status_code=404, detail="Scan session not found")

    while scan_session[scan_id]["state"] == "running":
        scan_session[scan_id]["log_condition"].acquire()
        scan_session[scan_id]["log_condition"].wait()
        scan_session[scan_id]["log_condition"].release()

        websocket.send_text(f'{{"action":"log", "body":"{scan_session[scan_id]["last_line"]}"}}')
    websocket.send_text('{"action":"finished"}')
    websocket.close()

@router.get('/')
def all_tasks():
    return list(scan_session.keys())
