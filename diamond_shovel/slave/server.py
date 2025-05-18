import logging
import urllib.parse

import uvicorn
from fastapi import FastAPI

from diamond_shovel.slave.route import plugin, task
from diamond_shovel.utils.func import json_util

app = FastAPI(json_encoder=json_util.get_encoder())

app.include_router(plugin.router)
app.include_router(task.router)

def start_api_slave(url):
    parsed = urllib.parse.urlparse(url)
    if 'unix' in parsed.scheme or 'file' in parsed.scheme:
        uvicorn.run(app, uds=parsed.path)
    else:
        uvicorn.run(app, host=parsed.hostname, port=parsed.port)
