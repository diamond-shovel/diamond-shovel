import asyncio
import copy
import inspect
import logging
import random
import traceback
import uuid
from asyncio import Future
from typing import Callable, Any, Coroutine, Type, AsyncGenerator

import diamond_shovel.plugins.load
import diamond_shovel.plugins.manage
from . import scheduler
from .items import Asset, Loot, Company, Domain, Host, decode_asset, decode_loot
from .scheduler import CoroutineQueue, ShovelCoroutine
from ..plugins import events, PluginInitContext, manage
from ..utils.func import async_helper


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
        self._worker_tasks: CoroutineQueue | None = None
        self._plugin_config = {}
        self._worker_filters = []
        self._log_hooks = []
        self._finished_plugins: dict[str, Future[Any]] = {}
        self._log = []
        self._nodes: list[Asset] = []
        self._edges: dict[tuple[Asset, Asset], float] = {}
        self._loots: list[Loot] = []

    def init_workers(self, workers):
        """
        Bootstraps task context with workers
        :params workers: workers to bootstrap with
        """
        if self._worker_tasks is not None:
            raise Exception("Task already inited with workers.")
        self._worker_tasks = workers

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

        if concat_worker_name(plugin_name, worker_name) not in self._finished_plugins:
            loop = asyncio.get_running_loop()
            self._finished_plugins[concat_worker_name(plugin_name, worker_name)] = loop.create_future()

        async with scheduler.current_coroutine().park(f"ctx.get_worker_result({plugin_name}, {worker_name})"):
            try:
                return await self._worker_tasks[concat_worker_name(plugin_name, worker_name)].get_result()
            except Exception as e:
                raise UnsatisfiedDependencyException(plugin_name, worker_name) from e

    async def get_all_results(self):
        """
        Triggers the worker execution and gets all the results from workers
        Should not be called from a plugin, it will be called internally
        :returns: all results, but None if not even started
        """
        if self._worker_tasks is None:
            return None

        return {"task_results": await self._worker_tasks.run(), "graph": await self.as_graph(), "loot": self._loots}

    async def _get_remaining_workers(self, ignore_self=False):
        """
        Fetches workers that haven't done their jobs, usually used internally for worker communication
        :params ignore_self: whether to ignore the caller worker.
        :returns: all the workers that haven't done their jobs
        """
        return [name for name, worker in self._worker_tasks.items() if
                worker.running and (not ignore_self or worker != scheduler.current_coroutine())]

    def get_worker_queue(self):
        return self._worker_tasks

    def __repr__(self):
        return f"TaskContext(finished_plugins={{{self._finished_plugins}}}, hash={hash(self)})"

    def get_plugin_config(self, plugin_name):
        """
        Reads config of a plugin, espically set for current task
        :params plugin_name: name of plugin
        """
        if plugin_name not in self._plugin_config:
            self._plugin_config[plugin_name] = {}

        return self._plugin_config[plugin_name]

    def set_plugin_config(self, plugin_name, config):
        if plugin_name not in self._plugin_config:
            self._plugin_config[plugin_name] = {}

        self._plugin_config[plugin_name].update(config)

    def log(self, msg):
        """
        Logs a message to current context
        :params msg: log message
        """
        [hook(msg) for hook in self._log_hooks]
        self._log.append(msg)

    def get_log(self):
        """
        Reads all the log in current context
        :returns: the log
        """
        return self._log

    def add_worker_filter(self, predicate: Callable[[PluginInitContext,
                                               Callable[['TaskContext'], Coroutine[Any, Any, Any]]], bool]) -> None:
        """
        Append a filter to worker, only the worker passes all the filters can be applied to this task context
        :params predicate: predicate function, true if the worker is accepted
        """
        self._worker_filters.append(predicate)

    def filter_worker(self, owner: PluginInitContext, worker: Callable[['TaskContext'], Coroutine[Any, Any, Any]]) -> bool:
        """
        Checks if target worker passes filters
        :params owner: worker owner
        :params worker: worker function
        """
        return all([filter0(owner, worker) for filter0 in self._worker_filters])

    async def set_relativity(self, node_1: Asset, node_2: Asset, relativity: float):
        if node_1 not in self._nodes:
            raise ValueError(f'Node {node_1} not in the node graph. Please add it first.')
        if node_2 not in self._nodes:
            raise ValueError(f'Node {node_2} not in the node graph. Please add it first.')
        if relativity < 0 or relativity > 1:
            raise ValueError(f'Relativity {relativity} must be in range [0, 1].')
        if node_1 == node_2:
            raise ValueError(f'Cannot set relativity for the same node {node_1}.')

        evt = events.GraphNodeRelationUpdateEvent(self, node_1, node_2, relativity)
        await async_helper.call_sync(events.call_event, evt)
        relativity = evt.new_relation

        if (node_2, node_1) in self._edges:
            self._edges[(node_2, node_1)] = relativity
            return

        self._edges[(node_1, node_2)] = relativity

    async def add_node(self, node: Asset):
        """
        Add an asset node to task context
        :params node: the asset node to be added
        """
        if not isinstance(node, Asset):
            raise ValueError(f'Node {node} is not an asset.')

        evt = events.GraphNodeAddEvent(self, node)
        await async_helper.call_sync(events.call_event, evt)
        self._nodes.append(evt.node)

    @property
    def nodes(self) -> list[Asset]:
        """
        Fetches all the nodes in the task context
        Use `replace_node` to modify the nodes, as they are immutable
        """
        return copy.deepcopy(self._nodes)

    @property
    def loots(self) -> list[Loot]:
        """
        Fetches all the loots in the task context
        Use `add_loot` or `update_loot` to modify the loots, as they are immutable
        """
        return copy.deepcopy(self._loots)

    async def add_loot(self, loot: Loot):
        """
        Adds a loot to the task context
        :params loot: the loot to be added
        """
        if not isinstance(loot, Loot):
            raise ValueError(f'Loot {loot} is not a Loot instance.')

        evt = events.LootDiscoveryEvent(self, loot)
        await async_helper.call_sync(events.call_event, evt)
        self._loots.append(evt.loot)

    async def update_loot(self, old: Loot, new: Loot):
        """
        Updates a loot in the task context
        :params old: the old loot to be replaced
        :params new: the new loot to replace with
        """
        if old not in self._loots:
            raise ValueError(f'Loot {old} not in the loot list. Please add it first.')
        if new in self._loots:
            raise ValueError(f'Loot {new} already exists in the loot list.')

        evt = events.LootUpdateEvent(self, old, new)
        await async_helper.call_sync(events.call_event, evt)
        new = evt.loot
        index = self._loots.index(old)
        self._loots[index] = new

    async def replace_node(self, old: Asset, new: Asset):
        """
        Replaces an asset node with another one in the task context
        :params old: the old asset node to be replaced
        :params new: the new asset node to replace with
        """
        if old not in self._nodes:
            raise ValueError(f'Node {old} not in the node graph. Please add it first.')
        if new in self._nodes:
            raise ValueError(f'Node {new} already exists in the node graph.')

        evt = events.GraphNodeReplaceEvent(self, old, new)
        await async_helper.call_sync(events.call_event, evt)
        new = evt.node
        index = self._nodes.index(old)
        self._nodes[index] = new

        new_edges = {}
        for (node1, node2), rel in self._edges.items():
            if node1 == old:
                new_edges[(new, node2)] = rel
            elif node2 == old:
                new_edges[(node1, new)] = rel
            else:
                new_edges[(node1, node2)] = rel
        self._edges = new_edges

    def get_relationship(self, node_1: Asset, node_2: Asset) -> float:
        """
        Gets the relationship between two nodes in the task context
        :params node_1: the first node
        :params node_2: the second node
        :returns: the relationship between two nodes
        """
        if node_1 not in self._nodes:
            raise ValueError(f'Node {node_1} not in the node graph. Please add it first.')
        if node_2 not in self._nodes:
            raise ValueError(f'Node {node_2} not in the node graph. Please add it first.')

        # do a simple dijkstra algorithm to find max relationship
        dist = {}
        for node in self._nodes:
            dist[node] = float('-inf')
        dist[node_1] = 1
        visited = set()
        queue = [node_1]
        while queue:
            current_node = queue.pop(0)
            if current_node in visited:
                continue
            visited.add(current_node)

            for neighbor, rel in self.get_connections(current_node).items():
                if neighbor not in visited:
                    new_dist = dist[current_node] * rel
                    if new_dist > dist[neighbor]:
                        dist[neighbor] = new_dist
                        queue.append(neighbor)

        return dist[node_2] if dist[node_2] != float('-inf') else 0.0

    def get_connections(self, node: Asset) -> dict[Asset, float]:
        """
        Gets all the connections of a node in the task context
        :params node: the node to get connections for
        :returns: a dictionary of node and its relationship
        """
        return {
            **{node1: rel for (node1, node2), rel in self._edges.items() if node2 == node},
            **{node2: rel for (node1, node2), rel in self._edges.items() if node1 == node}
        }

    async def collect_nodes(self, predicate: Type | Callable[[Asset], bool] = None, size=10) \
            -> AsyncGenerator[list[Asset], Any]:
        """
        Collects all the nodes in the task context that matches the predicate
        Things are immutable, you may need to use `replace_node` to modify the nodes
        :params predicate: a callable that takes an Asset and returns a boolean, or a type to match
        :returns: a list of Asset that matches the predicate
        """
        async for item in  self._do_collect(lambda: self._nodes, events.GraphNodeEvent, predicate, size):
            yield item

    async def collect_loots(self, predicate: Type | Callable[[Loot], bool] = None, size=10) \
            -> AsyncGenerator[list[Loot], Any]:
        """
        Collects all the loots in the task context that matches the predicate
        Things are immutable, you may need to use `add_loot` to modify the loots
        :params predicate: a callable that takes a Loot and returns a boolean, or a type to match
        :returns: a list of Loot that matches the predicate
        """
        async for item in self._do_collect(lambda: self._loots, events.LootEvent, predicate, size):
            yield item

    async def _do_collect(self, list_fetch: Callable[[], list], event_type: Type[events.TaskEvent], predicate: Type | Callable[[Any], bool] = None, size=10) \
            -> AsyncGenerator[list[Any], Any]:
        """
        Collects everything yielded from `list_fetch` that matches the predicate
        :params list_fetch: a callable that returns a list of target to collect from
        :params event_type: the type of event to wait for, usually events.GraphNodeAddEvent or events.LootDiscoveryEvent
        :params predicate: a callable that takes an Asset and returns a boolean, or a type to match
        :params size: the size of each batch to yield
        :returns: a list of Asset that matches the predicate
        """
        results = []
        selected = []

        if predicate is None:
            predicate = lambda target: True
        if not isinstance(predicate, Callable):
            predicate = lambda target: isinstance(target, predicate)

        try:
            async with scheduler.current_coroutine().park(f"ctx.collect(node -> {predicate})"):
                logging.debug(f"Checking remaining workers: {await self._get_remaining_workers(ignore_self=True)}")
                while len(await self._get_remaining_workers(ignore_self=True)) > 0:
                    logging.debug(f"Collecting nodes with predicate {predicate}, {scheduler.current_coroutine()}")

                    async with scheduler.current_coroutine().unpark():
                        await scheduler.current_coroutine().wake_watchdog()

                    if await events.wait_event(event_type,
                                               lambda evt: evt.task_context == self,
                                               timeout=random.random() * 2 + 2) is None:
                        continue

                    # await for the put, and/or yield chances for other execution
                    await asyncio.sleep(random.random() * 2 + 2)

                    for item in list_fetch():
                        if item not in selected and predicate(item):
                            selected.append(item)
                            results.append(copy.deepcopy(item))
                            if len(results) >= size:
                                async with scheduler.current_coroutine().unpark():
                                    yield results
                                results = []

                for item in list_fetch():
                    if item not in selected and predicate(item):
                        selected.append(item)
                        results.append(copy.deepcopy(item))
                        if len(results) < size:
                            continue
                        async with scheduler.current_coroutine().unpark():
                            yield results
                        results = []

                # final reminders
                for item in list_fetch():
                    if item in selected or not predicate(item):
                        continue
                    selected.append(item)
                    results.append(copy.deepcopy(item))
                if len(results) > 0:
                    async with scheduler.current_coroutine().unpark():
                        yield results
                results = []
        except asyncio.exceptions.CancelledError:
            # wait for watchdog uncancels us
            await asyncio.sleep(0.1)
            logging.debug(f"Got interrupted. exiting. already discovered {selected}")
            if len(results) > 0:
                yield results

        logging.debug(f"Finished collecting nodes with predicate {predicate}")

    async def as_graph(self):
        return {
            'nodes': {str(node.id): node for node in self._nodes},
            'edges': [{'nodes': [str(node1.id), str(node2.id)], 'relativity': rel} for (node1, node2), rel in self._edges.items()],
            'loots': {str(loot.id): loot for loot in self._loots},
        }

    def from_json(self, data):
        """
        Initializes the task context from a JSON data
        :params data: the JSON data to initialize from
        """
        self._nodes = [decode_asset(node) for node in data['graph']['nodes']]
        self._edges = {(uuid.UUID(edge['nodes'][0]), uuid.UUID(edge['nodes'][1])): edge['relativity'] for edge in data['graph']['edges']}
        self._loots = [decode_loot(loot) for loot in data['loots']]
        self._finished_plugins.update({worker_name: asyncio.Future() for worker_name in data['task_results']})
        [self._finished_plugins[worker_name].set_result(result) for worker_name, result in data['task_results'].items()]


class WorkerPool:
    def __init__(self):
        self._workers: dict[
            PluginInitContext, list[tuple[Callable[[TaskContext], Coroutine[Any, Any, Any]]], int]] = {}

    def register_worker(self, plugin_ctx: PluginInitContext, worker: Callable[[TaskContext], Coroutine[Any, Any, Any]],
                        nice=0):
        """
        Registers a worker to worker pool
        :params plugin_ctx: which plugin
        :params worker: which worker
        :params nice: the nice value, affects how things will be scheduled
        """
        if plugin_ctx not in self._workers:
            self._workers[plugin_ctx] = []
        self._workers[plugin_ctx].append((worker, nice))

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
                for plugin_ctx, workers in self._workers.items()
                for worker in workers]

    async def run_worker(self, ctx_target_companies: TaskContext | list[str], target_domains: list[str] = None,
                         target_ips: list[str] = None):
        """
        Fire a task execution to target
        :params ctx_target_companies: context or target companies
        :params target_domains: target domains
        :params target_ips: target ips
        """
        ctx = ctx_target_companies \
            if isinstance(ctx_target_companies, TaskContext) \
            else await initialize_task_context(ctx_target_companies, target_domains, target_ips)

        try:
            await async_helper.call_sync(events.call_event, events.TaskDispatchEvent(ctx))
            all_tasks = CoroutineQueue()
            for plugin_ctx, workers in self._workers.items():
                if not manage.is_plugin_enabled(plugin_ctx.plugin_name):
                    continue
                for worker, nice in workers:
                    if not ctx.filter_worker(plugin_ctx, worker):
                        continue

                    logging.info(f"Dispatched worker {worker.__qualname__} for {plugin_ctx.plugin_name}")
                    task = ShovelCoroutine(plugin_ctx, worker, ctx, nice)
                    all_tasks.put(task)
            ctx.init_workers(all_tasks)

            if all_tasks.size() == 0:
                logging.warning("No workers available.")
                return "No worker to run."

            return await ctx.get_all_results()
        except Exception:
            logging.error(f"Error while running workers for context {ctx}: {traceback.format_exc()}")
            return "Errored"


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
    [ctx.add_node(Company(name_or_metadata=company)) for company in target_companies if isinstance(company, str)]
    [ctx.add_node(Domain(domain_or_metadata=domain)) for domain in target_domains if isinstance(domain, str)]
    [ctx.add_node(Host(hostname_or_metadata=ip)) for ip in target_ips if isinstance(ip, str)]
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


def current_task_context() -> TaskContext | None:
    stack = inspect.stack()
    for frame in stack:
        if frame.function == "run_worker":
            return frame.frame.f_locals['ctx']
        if frame.function == "run":
            # maybe at scheduler.py#L73
            if 'self' in frame.frame.f_locals:
                result = getattr(frame.frame.f_locals['self'], 'ctx', None)
                if result is not None:
                    return result
    return None
