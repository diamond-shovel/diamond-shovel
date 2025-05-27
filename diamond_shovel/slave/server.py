import urllib.parse

import uvicorn
from fastapi import FastAPI, Depends

from diamond_shovel.slave.route import plugin, task, management
from diamond_shovel.slave import security

security.init()

app = FastAPI(dependencies=[
    Depends(security.validate_peer_signature),
    Depends(security.sign_response)
])

app.include_router(plugin.router)
app.include_router(task.router)
app.include_router(management.router)

def start_api_slave(url):
    parsed = urllib.parse.urlparse(url)
    if 'unix' in parsed.scheme or 'file' in parsed.scheme:
        uvicorn.run(app, uds=parsed.path)
    else:
        uvicorn.run(app, host=parsed.hostname, port=parsed.port)
