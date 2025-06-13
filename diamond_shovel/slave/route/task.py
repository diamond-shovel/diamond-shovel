import asyncio
import logging
import traceback
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Body, WebSocket, HTTPException
from pydantic import BaseModel

from diamond_shovel.function.task import TaskContext
from diamond_shovel.function.task import worker_pool as workers
from diamond_shovel.utils.func import async_helper

router = APIRouter(prefix="/task", tags=["task"])

scan_session = {}


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
        "log_lines": asyncio.Queue(),
    }

    ctx['scan_id'] = scan_id

    ctx['target_companies'] = target.companies or []
    ctx['target_domains'] = target.domains or []
    ctx['target_ips'] = target.ips or []

    return {"scan_id": scan_id}

@router.get('/{scan_id}')
async def get_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    return {
        "state": scan_session[scan_id]["state"],
        "result": await scan_session[scan_id]["ctx"].get_all_results(),
        "log": scan_session[scan_id]["ctx"].get_log()
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
        raise HTTPException(404, "Scan session not found")

    for key, value in params.items():
        scan_session[scan_id]["ctx"][key] = value

@router.post('/{scan_id}/blacklist')
def block_task_plugins(plugins: list[str], scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    scan_session[scan_id]["ctx"].add_worker_filter(lambda plugin, worker: plugin.plugin_name not in plugins)

@router.post('/{scan_id}/whitelist')
def whitelist_task_plugins(plugins: list[str], scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    scan_session[scan_id]["ctx"].add_worker_filter(lambda plugin, worker: plugin.plugin_name in plugins)

@router.post('/{scan_id}/plugins')
def update_task_plugin_config(params: dict, scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    for plugin_name, plugin_config in params.items():
        scan_session[scan_id]["ctx"].set_plugin_config(plugin_name, plugin_config)

@router.get('/{scan_id}/start')
def start_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    def log_hook(log_line):
        coroutine_data = {
            name: {
                'waiting': coro.park_reason,
                'done': coro.done,
                'cancelled': coro.cancelled,
            } for name, coro in scan_session[scan_id]["ctx"].get_worker_queue().items()
        } if scan_session[scan_id]["ctx"].get_worker_queue() else {}

        scan_session[scan_id]["log_lines"].put_nowait({
            'log': log_line,
            'coroutines': coroutine_data
        })

    async def task_runner():
        try:
            scan_session[scan_id]['ctx']._log_hooks.append(log_hook)
            await workers.run_worker(scan_session[scan_id]["ctx"])
            scan_session[scan_id]["state"] = "finished"
            scan_session[scan_id]['log_lines'].shutdown(immediate=True)
        except:
            logging.error(f"Error while processing task {scan_id}: {traceback.format_exc()}")

    scan_session[scan_id]["state"] = "running"
    loop = async_helper.threaded_async_run(task_runner())
    scan_session[scan_id]["loop"] = loop

@router.websocket('/ws/{scan_id}')
async def poll_logs(scan_id: uuid.UUID, websocket: WebSocket):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    await websocket.accept()

    while scan_session[scan_id]["state"] == "running":
        try:
            log_data = await scan_session[scan_id]["log_lines"].get()
            await websocket.send_json({'action': 'log', 'body': log_data['log'], 'coroutines': log_data['coroutines']})
        except asyncio.queues.QueueShutDown:
            pass

    await websocket.send_json({'action': 'finished'})
    await asyncio.sleep(1) # allow client to react to our message before connection close

    await websocket.close()

@router.get('/')
def all_tasks():
    return list(scan_session.keys())

@router.get('/{scan_id}/stop')
def stop_task(scan_id: uuid.UUID):
    if scan_id not in scan_session:
        raise HTTPException(404, "Scan session not found")

    scan_session[scan_id]["state"] = "finished"
    scan_session[scan_id]['loop'].stop()
    scan_session[scan_id]['log_lines'].shutdown(immediate=True)
