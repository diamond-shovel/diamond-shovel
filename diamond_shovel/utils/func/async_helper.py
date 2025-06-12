import asyncio
import functools
import logging
import threading
import traceback
from concurrent.futures.thread import ThreadPoolExecutor
from threading import Condition
from typing import Coroutine

pool = ThreadPoolExecutor()
local = threading.local()


async def call_sync(func, *args, **kwargs):
    if not is_current_async():
        raise RuntimeError("Just call it directly.")
    def sync_wrapper():
        local.from_async = True
        result = func(*args, **kwargs)
        local.from_async = False
        return result

    return await asyncio.get_running_loop().run_in_executor(pool, sync_wrapper)

def call_async(func, *args, **kwargs):
    if is_current_async():
        raise RuntimeError("Why not use `await` directly?")

    coro = func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func
    if getattr(local, 'from_async', False):
        blocker = Condition()
        future = asyncio.ensure_future(coro, loop=asyncio.get_event_loop())
        def callback(*_):
            blocker.acquire()
            blocker.notify_all()
            blocker.release()

        future.add_done_callback(callback)
        blocker.acquire()
        blocker.wait()
        blocker.release()
        return future.result()
    else:
        return asyncio.run(coro)


def run_async(coro: Coroutine):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    else:
        return asyncio.run(coro)

def start_async(coro: Coroutine):
    pool.submit(run_async, coro)

def is_current_async():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return loop and loop.is_running()

async def timed_await(coro, timeout):
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        return None
    except asyncio.CancelledError:
        logging.debug("Got interrupted.")
        raise

def is_coroutine(coro):
    return asyncio.iscoroutine(coro) or asyncio.iscoroutinefunction(coro) or asyncio.isfuture(coro)


def disallows_direct_async(func):
    func._disallow_direct_async = True
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if is_current_async() and not getattr(local, 'from_async', False):
            raise RuntimeError(f"Function {func.__name__} cannot be called directly from an async context. Please use `async_helper.call_sync` instead.")
        return func(*args, **kwargs)
    return wrapper

def threaded_async_run(coro):
    loop = asyncio.new_event_loop()
    def new_threaded_event_loop():
        try:
            asyncio.set_event_loop(loop)
            asyncio.run(coro)
        except RuntimeError:
            logging.warning(f"Exception during running coroutine: {traceback.format_exc()}")

    pool.submit(new_threaded_event_loop)
    return loop
