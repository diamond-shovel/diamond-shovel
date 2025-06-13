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
        """
        Checks if current worker coroutine is waiting
        :returns: True if waiting
        """
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

    def as_task(self, scheduler):
        """
        Starts the coroutine as an async task
        :params scheduler: the scheduler
        """
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
        """
        Engage a waiting situation
        :params reason: reason of waiting
        """
        if self._park_reason is not None:
            raise RuntimeError(f"{self._name} is already parked")
        self._park_reason = reason

        try:
            yield
        finally:
            self._park_reason = None

    async def wake_watchdog(self):
        """
        Wakes up the watchdog thread, interrupt the waiting chain
        """
        for scheduler in self._running_schedulers:
            await scheduler.alarm_watchdog()

    @asynccontextmanager
    async def unpark(self):
        """
        Temporary leaves the waiting mode, usually for doing scheduler related things
        """
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
        """
        Checks if current coroutine is running
        :returns: True if still running
        """
        if self._task is None:
            return False
        return (not self._task.done()) and (not self._task.cancelled())

    @property
    def done(self):
        """
        Checks if current coroutine is finished
        :returns: True if finished
        """
        if self._task is None:
            return False
        return self._task.done()

    @property
    def park_reason(self):
        return self._park_reason

    @property
    def cancelled(self):
        if self._task is None:
            return False
        return self._task.cancelled()

    async def get_result(self):
        """
        Reads result of current coroutine
        :returns: the result
        """
        if self._result is None:
            self._result = asyncio.get_running_loop().create_future()

        return await self._result


coroutine_wrapper_mapping: [typing.Coroutine, ShovelCoroutine] = {}


async def dummy(_):
    """
    A dummy coroutine that doing nothing
    """
    pass


dummy_coroutine = ShovelCoroutine(None, dummy, None, TaskGroup(), 0)
dummy_task_group = TaskGroup()


def current_coroutine(loop=None) -> ShovelCoroutine:
    """
    Gets current coroutine
    :returns: current coroutine
    """
    return coroutine_wrapper_mapping.get(asyncio.current_task(loop), dummy_coroutine)


class CoroutineQueue:
    def __init__(self):
        self._queue: PriorityQueue[tuple[int, ShovelCoroutine]] = PriorityQueue()
        self._name_map: dict[str, ShovelCoroutine] = {}
        self._task_group = TaskGroup()
        self._watchdog_alarm = threading.Event()
        self._task_to_interrupt = []

    def put(self, item: ShovelCoroutine, nice=0):
        """
        Put a coroutine to queue
        :params item: the coroutine
        :params nice: the nice value
        """
        self._queue.put_nowait((nice, item))
        self._name_map[item._name] = item

    async def run(self):
        """
        Launches all queued coroutine, and waits for the result
        :returns: all result of coroutines
        """
        task_set = []

        while not self._queue.empty():
            _, item = self._queue.get_nowait()
            task_set.append(item.as_task(self))
        threading.Thread(target=self.watchdog, args=(task_set, asyncio.get_running_loop())).start()
        await asyncio.gather(self.check_interrupt(task_set), *task_set)

        async def collect(task):
            try:
                return await task._result
            except Exception as e:
                return e

        return {item._name: await collect(item) for item in self._name_map.values()}

    async def alarm_watchdog(self):
        """
        Wakes the watchdog, to check if there's anyone to interrupt
        """
        self._watchdog_alarm.set()

    async def check_interrupt(self, task_set):
        """
        The loop of interrupting, checks everyone that not done
        :params task_set: the task list
        """
        while any([not task.done() for task in task_set]):
            await asyncio.sleep(1)
            if self._task_to_interrupt:
                for task in self._task_to_interrupt:
                    logging.debug(f'Executing interruption on task {task}')
                    task.cancel()
                    await asyncio.sleep(0.001)
                    task.uncancel()
                    logging.debug(f'Interruption for task {task} finished')
                self._task_to_interrupt.clear()

    def set_nice(self, name, nice):
        """
        Sets the nice value of specified coroutine
        :params name: target coroutine
        :params nice: new nice value
        """
        item = self._name_map[name]
        for qitem in self._queue.queue:
            if qitem[1] == item:
                self._queue.queue.remove(qitem)
                self._queue.put_nowait((nice, item))
                return
        self.put(item, nice)

    def watchdog(self, task_set, loop):
        """
        The watchdog method, that wakes waiting task from waiting infinitely
        :params task_set: async tasks to minitor
        :params loop: current async eventloop
        """
        logging.debug("Watchdog started.")
        while any([not task.done() for task in task_set]):
            try:
                self._watchdog_alarm.wait(timeout=60)
                time.sleep(10) # pass the event waiting.
            except:
                pass

            self.debug_dump_tasks(loop, task_set)

            if not all([coroutine_wrapper_mapping[task].waiting for task in task_set if not task.done()]):
                continue
            for item in task_set: # they are already sorted.
                if item.done():
                    continue
                logging.debug(f"Waking {coroutine_wrapper_mapping[item]}")
                self._task_to_interrupt.append(item)
                break

    def debug_dump_tasks(self, loop, task_set):
        """
        Dump all the tasks, to check who is the source of deadlock
        :params loop: current async eventloop
        :params task_set: tasks to monitor
        """
        logging.debug("Dumping all tasks")
        for task in task_set:
            logging.debug(f"{coroutine_wrapper_mapping[task]._name}: {coroutine_wrapper_mapping[task]}")
            ctx = coroutine_wrapper_mapping[task].ctx
        logging.debug("-" * 50)
        remaining = async_helper.run_async(ctx._get_remaining_workers(ignore_self=True))
        logging.debug(f"Running tasks ({len(remaining)} remains)")
        logging.debug("-" * 50)
        [logging.debug(f"{name}: {self._name_map[name]}") for name in remaining]
        logging.debug("-" * 50)
        curr = asyncio.current_task(loop)
        if curr is None:
            logging.debug(f"Nothing is running now.")
        else:
            logging.debug(f"Current task: {str(curr)}")
            logging.debug("-" * 50)
            stack = curr.get_stack()
            [logging.debug(f"{frame}") for frame in stack]

    def get_nice(self, name):
        """
        Gets nice value of a coroutine
        :params name: target coroutine
        :returns: the nice value, None if not found
        """
        item = self._name_map[name]
        for qitem in self._queue.queue:
            if qitem[1] == item:
                return qitem[0]
        return None

    def remove(self, name):
        """
        Removes a coroutine from queue
        :params name: target coroutine
        """
        item = self._name_map[name]
        if item is None:
            raise ValueError("item not found")
        for qitem in self._queue.queue:
            if qitem[1] == item:
                self._queue.queue.remove(qitem)
                return
        self._name_map.pop(name)
        raise ValueError("item not found")

    def size(self):
        """
        Gets the queue size
        :returns: the queue size
        """
        return self._queue.qsize()

    def items(self):
        """
        Gets everything from the queue
        :returns: the list tuples of name, coroutine
        """
        return self._name_map.items()

    def values(self):
        """
        Gets every coroutine from the queue
        :returns: the coroutine list
        """
        return self._name_map.values()

    def __getitem__(self, item):
        return self._name_map[item]

    def __len__(self):
        return len(self._name_map)
