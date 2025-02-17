from .privileged_main import run, request_execution, load_privileged_plugin, terminate, invoke_method
from . import privileged_main

def set_privileged_context(queue, pipe):
    privileged_main.privileged_queue = queue
    privileged_main.parent_pipe = pipe

