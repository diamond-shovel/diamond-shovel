import hashlib
import marshal
import multiprocessing.connection
import os
import traceback
import dill

privileged_queue: multiprocessing.Queue = None
key = None
parent_pipe: multiprocessing.connection.Connection = None

def run(queue, child_pipe: multiprocessing.connection.Connection):
    if os.geteuid() != 0:
        raise PermissionError("Privilege mode must be run as root")
    while True:
        try:
            command, client_key, *args = queue.get()
            if hashlib.sha256(dill.dumps((command, key, *args))) != client_key:
                continue

            if command == "eval_code":
                python_bytecode, function_name = args
                exec(marshal.loads(python_bytecode))
                child_pipe.send(locals()[function_name]())
            elif command == "load_plugin":
                plugin_path, = args
                exec(open(plugin_path).read())
            elif command == "invoke_method":
                invoke_obj, method_name, args = args
                if invoke_obj is None:
                    child_pipe.send(globals()[method_name](*dill.loads(args)))
                else:
                    child_pipe.send(getattr(dill.loads(invoke_obj), method_name)(*dill.loads(args)))
            elif command == "terminate":
                break
        except Exception as e:
            traceback.print_exc()

def ensure_privileged():
    if not privileged_queue or not parent_pipe:
        raise RuntimeError("Privileged queue not set")

def request_execution(python_bytecode: bytes, function_name: str):
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("eval_code", key, python_bytecode, function_name)))
    privileged_queue.put(("eval_code", hash_key, python_bytecode, function_name))
    return parent_pipe.recv()

def load_privileged_plugin(plugin_path: str):
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("load_plugin", key, plugin_path)))
    privileged_queue.put(("load_plugin", hash_key, plugin_path))

def invoke_method(invoke_obj, method_name: str, *args):
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("invoke_method", key, dill.dumps(invoke_obj) if invoke_obj else None, method_name, dill.dumps(args))))
    privileged_queue.put(("invoke_method", hash_key, dill.dumps(invoke_obj) if invoke_obj else None, method_name, dill.dumps(args)))
    return parent_pipe.recv()

def terminate():
    if not privileged_queue:
        return
    hash_key = hashlib.sha256(dill.dumps(("terminate", key)))
    privileged_queue.put(("terminate", hash_key))
