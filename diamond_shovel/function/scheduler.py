import asyncio
import contextlib
import logging
import threading
import time
import traceback
import typing
from asyncio import TaskGroup
from contextlib import asynccontextmanager
from queue import PriorityQueue
from typing import Callable

from diamond_shovel.plugins import events
from diamond_shovel.utils.func import async_helper


class ShovelCoroutine:
    def __init__(self, plugin_ctx, coro: Callable[[typing.Any], typing.Coroutine], ctx, task_group: TaskGroup,
                 nice: int):
        self.ctx = ctx
        self._coro = coro
        self._name = (plugin_ctx.plugin_name if plugin_ctx else "unknown") + ":" + '.'.join(str(coro.__module__).split('.')[1:]) + '.' + coro.__qualname__
        self._owner = plugin_ctx
        self._park_reason = None
        self._result = None
        self._task = None
        self._nice = nice
        self._task_group = task_group
        self._running_schedulers = []

    def __str__(self):
        if not self._task:
            return f"ShovelCoroutine({self._name}) {{Not started yet}}"
        return f"ShovelCoroutine({self._name}) {{waiting={self._park_reason}, done={self._task.done()}, cancelled={self._task.cancelled()}, addr={hex(id(self._task))}}}"

    __repr__ = __str__

    @property
    def waiting(self):
        return self._park_reason is not None

    @contextlib.contextmanager
    def _attach(self):
        try:
            self._owner.override_config(self.ctx.get_plugin_config(self._owner.plugin_name))
            if self._owner is None:
                yield
            else:
                with self._owner.attach(self.ctx):
                    yield
        finally:
            self._owner.restore_config()

    def as_task(self, on_complete, scheduler):
        if self._task is None:
            logging.info(f"Starting {self._name}")

            async def run():
                if self._result is None:
                    self._result = asyncio.get_running_loop().create_future()

                try:
                    self._running_schedulers.append(scheduler)
                    with self._attach():
                        self._result.set_result(await self._coro(self.ctx))
                    logging.info(f"{self._name} has finished running")
                    on_complete(self)
                    self._running_schedulers.remove(scheduler)
                except Exception as e:
                    self._result.set_exception(e)
                    self._running_schedulers.remove(scheduler)
                    logging.error(f"Error running {self._name}: {''.join(traceback.format_exception(e))}")

            self._task = self._task_group.create_task(run(), name=self._name)
            coroutine_wrapper_mapping[self._task] = self

        return self._task

    @asynccontextmanager
    async def park(self, reason):
        if self._park_reason is not None:
            raise RuntimeError(f"{self._name} is already parked")
        self._park_reason = reason

        try:
            yield
        finally:
            self._park_reason = None

    async def wake_watchdog(self):
        for scheduler in self._running_schedulers:
            await scheduler.alarm_watchdog()

    @asynccontextmanager
    async def unpark(self):
        if self._park_reason is None:
            raise RuntimeError(f"{self._name} is not parked")
        original_reason = self._park_reason
        self._park_reason = None
        try:
            yield
        finally:
            self._park_reason = original_reason

    def __lt__(self, other):
        return self._nice < other._nice

    def __gt__(self, other):
        return self._nice > other._nice

    @property
    def running(self):
        if self._task is None:
            return False
        return (not self._task.done()) and (not self._task.cancelled())

    @property
    def done(self):
        if self._task is None:
            return False
        return self._task.done()

    async def get_result(self):
        if self._result is None:
            self._result = asyncio.get_running_loop().create_future()

        return await self._result


coroutine_wrapper_mapping: [typing.Coroutine, ShovelCoroutine] = {}


async def dummy(_):
    pass


dummy_coroutine = ShovelCoroutine(None, dummy, None, TaskGroup(), 0)
dummy_task_group = TaskGroup()


def current_coroutine(loop=None) -> ShovelCoroutine:
    return coroutine_wrapper_mapping.get(asyncio.current_task(loop), dummy_coroutine)


class CoroutineQueue:
    def __init__(self):
        self._queue_: PriorityQueue[tuple[int, ShovelCoroutine]] = PriorityQueue()
        self._name_map_: dict[str, ShovelCoroutine] = {}
        self._task_group = TaskGroup()
        self._watchdog_alarm = threading.Event()
        self._task_to_interrupt = []

    def put(self, item: ShovelCoroutine, nice=0):
        self._queue_.put_nowait((nice, item))
        self._name_map_[item._name] = item

    async def run(self):
        task_set = []

        def complete(coro):
            events.call_event(events.TaskWorkerStateChangedEvent(coro.ctx,
                                                                 {
                                                                name: {
                                                                    "state": "waiting" if target_coro.waiting else (
                                                                        "done" if target_coro.done else
                                                                        ("cancelled" if target_coro.cancelled else
                                                                         "running")),
                                                                    "wait_reason": target_coro._park_reason
                                                                } for name, target_coro in self._name_map_
                                                            },
                                                                 {
                                                                coro._name: {
                                                                    "state": "waiting" if coro.waiting else (
                                                                        "done" if coro.done else
                                                                        ("cancelled" if coro.cancelled else
                                                                         "running")),
                                                                    "wait_reason": coro._park_reason
                                                                }
                                                            }))

        while not self._queue_.empty():
            _, item = self._queue_.get_nowait()
            task_set.append(item.as_task(complete, self))
        threading.Thread(target=self.watchdog, args=(task_set, asyncio.get_running_loop())).start()
        await asyncio.gather(self.check_interrupt(task_set), *task_set)

        async def collect(task):
            try:
                return await task._result
            except Exception as e:
                return e

        return {item._name: await collect(item) for item in self._name_map_.values()}

    async def alarm_watchdog(self):
        self._watchdog_alarm.set()

    async def check_interrupt(self, task_set):
        while any([not task.done() for task in task_set]):
            await asyncio.sleep(1)
            if self._task_to_interrupt:
                for task in self._task_to_interrupt:
                    task.cancel()
                    await asyncio.sleep(0.1)
                    task.uncancel()
                self._task_to_interrupt.clear()

    def set_nice(self, name, nice):
        item = self._name_map_[name]
        for qitem in self._queue_.queue:
            if qitem[1] == item:
                self._queue_.queue.remove(qitem)
                self._queue_.put_nowait((nice, item))
                return
        self.put(item, nice)

    def watchdog(self, task_set, loop):
        logging.debug("Watchdog started.")
        while any([not task.done() for task in task_set]):
            try:
                self._watchdog_alarm.wait(timeout=60)
                time.sleep(10) # pass the event waiting.
            except:
                pass

            logging.debug("Dumping all tasks")
            for task in task_set:
                logging.debug(f"{coroutine_wrapper_mapping[task]._name}: {coroutine_wrapper_mapping[task]}")
                ctx = coroutine_wrapper_mapping[task].ctx
            logging.debug("-" * 50)
            remaining = async_helper.run_async(ctx.get_remaining_workers(ignore_self=True))
            logging.debug(f"Running tasks ({len(remaining)} remains)")
            logging.debug("-" * 50)
            [logging.debug(f"{name}: {self._name_map_[name]}") for name in remaining]
            logging.debug("-" * 50)
            curr = asyncio.current_task(loop)

            if curr is None:
                logging.debug(f"Nothing is running now.")
            else:
                logging.debug(f"Current task: {str(curr)}")
                logging.debug("-" * 50)
                stack = curr.get_stack()
                [logging.debug(f"{frame}") for frame in stack]

            if not all([coroutine_wrapper_mapping[task].waiting for task in task_set if not task.done()]):
                continue
            for item in task_set: # they are already sorted.
                if item.done():
                    continue
                logging.debug(f"Waking {coroutine_wrapper_mapping[item]}")
                self._task_to_interrupt.append(item)
                break

    def get_nice(self, name):
        item = self._name_map_[name]
        for qitem in self._queue_.queue:
            if qitem[1] == item:
                return qitem[0]
        return None

    def remove(self, name):
        item = self._name_map_[name]
        if item is None:
            raise ValueError("item not found")
        for qitem in self._queue_.queue:
            if qitem[1] == item:
                self._queue_.queue.remove(qitem)
                return
        self._name_map_.pop(name)
        raise ValueError("item not found")

    def size(self):
        return self._queue_.qsize()

    def items(self):
        return self._name_map_.items()

    def values(self):
        return self._name_map_.values()

    def __getitem__(self, item):
        return self._name_map_[item]

    def __len__(self):
        return len(self._name_map_)
