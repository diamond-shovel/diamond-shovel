import asyncio
import copy
import logging
import random
import threading
from asyncio import Future, current_task
from typing import Callable, Any, Coroutine

import loguru

import diamond_shovel.plugins.load
import diamond_shovel.plugins.manage
from . import scheduler
from .scheduler import CoroutineQueue, ShovelCoroutine
from ..plugins import events, PluginInitContext, manage
from ..utils.func import async_helper
from ..utils.func.async_helper import call_async


class WorkerException(Exception):
    pass


class UnsatisfiedDependencyException(Exception):
    def __init__(self, plugin_name, worker_name):
        self.plugin_name = plugin_name
        self.worker_name = worker_name

    def __str__(self):
        return f"Unsatisfied dependency for {self.plugin_name}:{self.worker_name}"

    def __repr__(self):
        return f"UnsatisfiedDependencyException(plugin_name={self.plugin_name}, worker_name={self.worker_name})"

    def __eq__(self, other):
        return isinstance(other,
                          UnsatisfiedDependencyException) and self.plugin_name == other.plugin_name and self.worker_name == other.worker_name


def concat_worker_name(plugin_name, worker_name):
    return f"{plugin_name}:{worker_name}"


class TaskContext:
    def __init__(self):
        self.__futures__: dict[str, Future[Any]] = {}
        self.__finished_plugins__: dict[str, Future[Any]] = {}
        self.__worker_tasks__: CoroutineQueue | None = None
        self.__plugin_config__ = {}
        self.__log__ = []

    def start(self, workers):
        """
        Bootstraps task context with workers
        :params workers: workers to bootstrap with
        """
        if self.__worker_tasks__ is not None:
            raise Exception("Task already started.")
        self.__worker_tasks__ = workers

    def __list__(self):
        return self.__futures__.keys()

    async def get(self, name: str):
        """
        Fetches value in a context
        Fires a `TaskReadTriggerEvent` and the result can be altered.
        :params name: key name
        """
        if name not in self.__futures__ or (self.__futures__[name].done() and await self.__futures__[name] is None):
            logging.debug(f"Reset {name} for {current_task(asyncio.get_running_loop())}")
            loop = asyncio.get_running_loop()
            self.__futures__[name] = loop.create_future()

        # Avoid accidentally uncontrolled modification. Their modification must fire an event.
        if scheduler.current_coroutine().waiting:
            value = copy.deepcopy(await self.__futures__[name])
        else:
            async with scheduler.current_coroutine().park(f"ctx[{name}]"):
                value = copy.deepcopy(await self.__futures__[name])
        evt = events.TaskReadTriggerEvent(self, name, value)
        await async_helper.call_sync(events.call_event, evt)

        return evt.value

    async def set(self, name: str, result: Any):
        """
        Sets value in a context
        Fires a `TaskWriteTriggerEvent` and the result can be altered
        :params name: key name
        :params result: the value to be set
        """
        loop = asyncio.get_running_loop()

        old_value = None
        if name in self.__futures__ and self.__futures__[name].done():
            old_value = self.__futures__[name].result()

        evt = events.TaskWriteTriggerEvent(self, name, result, old_value)
        await async_helper.call_sync(events.call_event, evt)
        if name not in self.__futures__ or self.__futures__[name].done():
            self.__futures__[name] = loop.create_future()
        if evt.value is None:
            raise ValueError(f"Cannot set {name} to None")

        self.__futures__[name].set_result(evt.value)

    @async_helper.disallows_direct_async
    def __getitem__(self, item):
        return call_async(self.get, item)

    @async_helper.disallows_direct_async
    def __setitem__(self, key, value):
        call_async(self.set, key, value)

    def items(self):
        """
        Fetches a copy of context values
        :returns: a list of tuples that formatted with key and value.
        """
        return [(key, values) for key, values in self.__futures__.items() if values.done()]

    def __iter__(self):
        for key, values in self.items():
            yield key, values

    def __contains__(self, item):
        return (item in self.__futures__ and self.__futures__[item].done() and
                self.__futures__[item].result() is not None)

    async def operate(self, key, func, *args, **kwargs):
        """
        Perform operations on the value, and set the new result back to context.
        Events will be fired at following order:
          - TaskReadTriggerEvent
          - *callback function*
          - TaskWriteTriggerEvent
          - TaskReadTriggerEvent
        :params key: context key to operate
        :params func: callback function to map the original value to a new value
        :params args: positional arguments to callback function
        :params kwargs: keyword arguments to callback function
        :returns: transformed context value, usually the return value of `func` parameter
        """
        tmp = await self.get(key)
        await self.set(key, func(tmp, *args, **kwargs))
        return await self.get(key)

    async def get_worker_result(self, plugin_name, worker_name):
        """
        Reads result of workers
        Result of workers isn't stored like how a key-value context did, they've been isolated to avoid accidental modification
        :params plugin_name: source plugin
        :params worker_name: source worker
        :returns: None if source plugin isn't found, otherwise we'll try to fetch the result, and wait when the target is not done
        """
        if plugin_name not in diamond_shovel.plugins.manage.plugin_table:
            return None

        if concat_worker_name(plugin_name, worker_name) not in self.__finished_plugins__:
            loop = asyncio.get_running_loop()
            self.__finished_plugins__[concat_worker_name(plugin_name, worker_name)] = loop.create_future()

        async with scheduler.current_coroutine().park(f"ctx.get_worker_result({plugin_name}, {worker_name})"):
            try:
                return await self.__worker_tasks__[concat_worker_name(plugin_name, worker_name)].get_result()
            except Exception as e:
                raise UnsatisfiedDependencyException(plugin_name, worker_name) from e

        return None

    async def get_all_results(self):
        """
        Triggers the worker execution and gets all the results from workers
        Should not be called from a plugin, it will be called internally
        :returns: all results, but None if not even started
        """
        if self.__worker_tasks__ is None:
            return None

        return await self.__worker_tasks__.run()

    async def get_remaining_workers(self, ignore_self=False):
        """
        Fetches workers that haven't done their jobs, usually used internally for worker communication
        :params ignore_self: whether to ignore the caller worker.
        :returns: all the workers that haven't done their jobs
        """
        return [name for name, worker in self.__worker_tasks__.items() if
                worker.running and (not ignore_self or worker != scheduler.current_coroutine())]

    async def collect(self, key, size=10):
        """
        Collects everything from a list value, and tries to wait for more result
        Yields results are collected in chunks, which is also a list that contains the result
        :params key: the key to collect
        :params size: the size of yielded chunks
        """
        results = []
        selected = []
        retry_times = 0
        try:
            async with scheduler.current_coroutine().park(f"ctx.collect({key})"):
                logging.debug(f"Checking remaining workers: {await self.get_remaining_workers(ignore_self=True)}")
                while len(await self.get_remaining_workers(ignore_self=True)) > 0:
                    logging.debug(f"Collecting {key} for {retry_times} times, {scheduler.current_coroutine()}")
                    retry_times += 1

                    async with scheduler.current_coroutine().unpark():
                        await scheduler.current_coroutine().wake_watchdog()

                    if await events.wait_event(events.TaskWriteTriggerEvent,
                                               lambda evt: evt.key == key and evt.task_context == self, timeout=random.random() * 2 + 2) is None:
                        continue
                    await asyncio.sleep(random.random() * 2 + 2)
                    for item in await self.get(key):
                        if item not in selected:
                            selected.append(item)
                            results.append(item)
                            if len(results) >= size:
                                async with scheduler.current_coroutine().unpark():
                                    yield results
                                results = []
                    retry_times = 0

                for item in await self.get(key):
                    if item not in selected:
                        selected.append(item)
                        results.append(item)
                        if len(results) < size:
                            continue
                        async with scheduler.current_coroutine().unpark():
                            yield results
                        retry_times = 0
                        results = []

                for item in await self.get(key):
                    if item in selected:
                        continue
                    selected.append(item)
                    results.append(item)
                if len(results) > 0:
                    async with scheduler.current_coroutine().unpark():
                        yield results
                retry_times += 1
                results = []
        except asyncio.exceptions.CancelledError:
            logging.debug(f"Got interrupted. exiting. already discovered {selected}")
            for item in await self.get(key):
                if item not in selected:
                    selected.append(item)
                    results.append(item)
            if len(results) > 0:
                yield results

        logging.debug(f"Finished collecting {key}")

    def __repr__(self):
        return f"TaskContext(futures={{{self.__futures__}}}, finished_plugins={{{self.__finished_plugins__}}})"

    def get_plugin_config(self, plugin_name):
        """
        Reads config of a plugin, espically set for current task
        :params plugin_name: name of plugin
        """
        if plugin_name not in self.__plugin_config__:
            self.__plugin_config__[plugin_name] = {}

        return self.__plugin_config__[plugin_name]

    def set_plugin_config(self, plugin_name, config):
        if plugin_name not in self.__plugin_config__:
            self.__plugin_config__[plugin_name] = {}

        self.__plugin_config__[plugin_name].update(config)

    def log(self, msg):
        """
        Logs a message to current context
        :params msg: log message
        """
        self.__log__.append(msg)

    def get_log(self):
        """
        Reads all the log in current context
        :returns: the log
        """
        return self.__log__


class ThreadLoguruHook(logging.Handler):
    def __init__(self, target_thread, cb):
        super().__init__()
        self._target_thread = target_thread
        self._cb = cb

    def filter(self, record):
        return record.thread == self._target_thread

    def emit(self, record):
        self._cb(self.format(record))


class WorkerPool:
    def __init__(self):
        self.__workers__: dict[
            PluginInitContext, list[tuple[Callable[[TaskContext], Coroutine[Any, Any, Any]]], int]] = {}

    def register_worker(self, plugin_ctx: PluginInitContext, worker: Callable[[TaskContext], Coroutine[Any, Any, Any]],
                        nice=0):
        """
        Registers a worker to worker pool
        :params plugin_ctx: which plugin
        :params worker: which worker
        :params nice: the nice value, affects how things will be scheduled
        """
        if plugin_ctx not in self.__workers__:
            self.__workers__[plugin_ctx] = []
        self.__workers__[plugin_ctx].append((worker, nice))

    def get_docs(self):
        """
        Fetch all documents from plugin
        :returns: a tuple with plugin name, worker name and document
        """
        def extract_doc(plugin, name):
            try:
                with plugin.open_resource(name + ".txt") as f:
                    return f.read().decode('utf-8')
            except KeyError:
                return "No doc available for this worker."

        return [(plugin_ctx.plugin_name, worker.__qualname__,
                 worker.__doc__ if worker.__doc__ and worker.__doc__.startswith("#worker_entry#") else extract_doc(
                     plugin_ctx, worker.__qualname__))
                for plugin_ctx, workers in self.__workers__.items()
                for worker in workers]

    async def run_worker(self, ctx_target_companies: TaskContext | list[str], target_domains: list[str] = None,
                         target_ips: list[str] = None, loguru_handler: Callable[[str], None] | None = None):
        """
        Fire a task execution to target
        :params ctx_target_companies: context or target companies
        :params target_domains: target domains
        :params target_ips: target ips
        :params loguru_handler: handler of logging, will be called on every log
        """
        ctx = ctx_target_companies \
            if isinstance(ctx_target_companies, TaskContext) \
            else await initialize_task_context(ctx_target_companies, target_domains, target_ips)

        with loguru.logger.contextualize():
            loguru_handler_id = None
            if loguru_handler is not None:
                current_thread = threading.current_thread()

                loguru_handler_id = loguru.logger.add(sink=ThreadLoguruHook(current_thread, loguru_handler))

            try:
                async with asyncio.TaskGroup() as tg:
                    await async_helper.call_sync(events.call_event, events.TaskDispatchEvent(ctx))
                    all_tasks = CoroutineQueue()
                    for plugin_ctx, workers in self.__workers__.items():
                        if not manage.is_plugin_enabled(plugin_ctx.plugin_name):
                            continue
                        for worker, nice in workers:
                            logging.info(f"Dispatched worker {worker.__qualname__} for {plugin_ctx.plugin_name}")
                            task = ShovelCoroutine(plugin_ctx, worker, ctx, tg, nice)
                            all_tasks.put(task)
                    ctx.start(all_tasks)

                    if all_tasks.size() == 0:
                        logging.warning("No workers available.")
                        return "No worker to run."

                    return await ctx.get_all_results()
            finally:
                if loguru_handler_id is not None:
                    loguru.logger.remove(loguru_handler_id)


worker_pool = WorkerPool()


async def initialize_task_context(target_companies=None, target_domains=None, target_ips=None):
    """
    Create a task context from following target information
    :params target_companies: target companies
    :params target_domains: target domains
    :params target_ips: target ips
    """
    if target_ips is None:
        target_ips = []
    if target_companies is None:
        target_companies = []
    if target_domains is None:
        target_domains = []

    ctx = TaskContext()
    ctx["target_companies"] = target_companies
    ctx["target_domains"] = target_domains
    ctx["target_ips"] = target_ips
    return ctx


async def run_full_scan(target_companies=None, target_domains=None, target_ips=None):
    """
    Runs a full scan on target
    :params target_companies: target companies
    :params target_domains: target domains
    :params target_ips: target ips
    """
    if target_domains is None:
        target_domains = []
    if target_ips is None:
        target_ips = []
    if target_companies is None:
        target_companies = []

    if isinstance(target_companies, TaskContext):
        ctx = target_companies
    else:
        ctx = await initialize_task_context(target_companies, target_domains, target_ips)

    return await worker_pool.run_worker(ctx)


def init():
    """
    Initializes the worker, and fires a initialize event
    """
    events.call_event(events.WorkerPoolInitEvent(worker_pool))
