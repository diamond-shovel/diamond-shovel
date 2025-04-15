import logging
import urllib.parse

import uvicorn
from fastapi import FastAPI


app = FastAPI()

def start_api_slave(url):
    parsed = urllib.parse.urlparse(url)
    if 'unix' in parsed.scheme or 'file' in parsed.scheme:
        uvicorn.run(app, uds=parsed.path)
    else:
        uvicorn.run(app, host=parsed.hostname, port=parsed.port)
