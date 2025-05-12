import hashlib
import logging
import marshal
import multiprocessing.connection
import os
import traceback
import dill

privileged_queue: multiprocessing.Queue = None
key = None
parent_pipe: multiprocessing.connection.Connection = None

def run(queue, child_pipe: multiprocessing.connection.Connection):
    """
    Root daemon method, provides service to access root
    """
    if os.geteuid() != 0:
        raise PermissionError("Privilege mode must be run as root")
    while True:
        try:
            command, client_key, *args = queue.get()
            if hashlib.sha256(dill.dumps((command, key, *args))).digest() != client_key:
                continue

            if command == "eval_code":
                python_bytecode, function_name = args
                exec(marshal.loads(python_bytecode))
                child_pipe.send(dill.dumps(locals()[function_name]()))
            elif command == "load_plugin":
                plugin_path, = args
                exec(open(plugin_path).read())
            elif command == "invoke_method":
                invoke_obj, method_name, args = args
                if invoke_obj is None:
                    child_pipe.send(dill.dumps(globals()[method_name](*dill.loads(args))))
                else:
                    child_pipe.send(dill.dumps(getattr(dill.loads(invoke_obj), method_name)(*dill.loads(args))))
            elif command == "terminate":
                break
        except Exception as e:
            logging.error(f"Error while processing privileged requests {traceback.format_exc()}")
            child_pipe.send(e)

def ensure_privileged():
    """
    Makes sure privileged daemon is enabled
    """
    if not privileged_queue or not parent_pipe:
        raise RuntimeError("Privileged queue not set")

def request_execution(python_bytecode: bytes, function_name: str):
    """
    Requests a python execution on root user
    :params python_bytecode: python bytecode to execute
    :params function_name: function to call
    """
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("eval_code", key, python_bytecode, function_name))).digest()
    privileged_queue.put(("eval_code", hash_key, python_bytecode, function_name))
    result = dill.loads(parent_pipe.recv())
    if isinstance(result, Exception):
        raise result
    return result

def load_privileged_plugin(plugin_path: str):
    """
    Requests a plugin loading on root user
    :params plugin_path: path to target plugin
    """
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("load_plugin", key, plugin_path)))
    privileged_queue.put(("load_plugin", hash_key, plugin_path))

def invoke_method(invoke_obj, method_name: str, *args):
    """
    Requests a python method invocation on target object
    :params invoke_obj: the object to invoke on, None is a static invocation
    :params method_name: the method to be invoked
    :params args: method arguments
    """
    ensure_privileged()
    hash_key = hashlib.sha256(dill.dumps(("invoke_method", key, dill.dumps(invoke_obj) if invoke_obj else None, method_name, dill.dumps(args)))).digest()
    privileged_queue.put(("invoke_method", hash_key, dill.dumps(invoke_obj) if invoke_obj else None, method_name, dill.dumps(args)))
    result = dill.loads(parent_pipe.recv())
    if isinstance(result, Exception):
        raise result
    return result

def terminate():
    """
    Terminate the root daemon
    """
    if not privileged_queue:
        return
    hash_key = hashlib.sha256(dill.dumps(("terminate", key))).digest()
    privileged_queue.put(("terminate", hash_key))
