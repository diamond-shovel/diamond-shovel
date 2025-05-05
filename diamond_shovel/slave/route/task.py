import multiprocessing
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Body, WebSocket
from pydantic import BaseModel

from diamond_shovel.function.task import WorkerPool, TaskContext
from diamond_shovel.utils.func import async_helper

router = APIRouter(prefix="/task", tags=["task"])

scan_session = {}
workers = WorkerPool()


class TargetRequest(BaseModel):
    companies: Optional[list[str]]
    domains: Optional[list[str]]
    ips: Optional[list[str]]

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

    ctx['target_companies'] = target.companies or []
    ctx['target_domains'] = target.domains or []
    ctx['target_ips'] = target.ips or []

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

@router.post('/{scan_id}/plugins')
def update_task_plugin_config(params: dict, scan_id: uuid.UUID):
    if scan_id not in scan_session:
        return {"error": "Scan not found"}

    for plugin_name, plugin_config in params.items():
        scan_session[scan_id]["ctx"].set_plugin_config(plugin_name, plugin_config)

@router.get('/{scan_id}/start')
def start_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        return {"error": "Scan session not found"}

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
