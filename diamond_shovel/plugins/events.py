_event_handlers = {}
__event_futures__ = {}

import asyncio

from diamond_shovel.plugins.manage import is_plugin_enabled
from diamond_shovel.utils.func import async_helper
from diamond_shovel.utils.func.async_helper import timed_await


class Event:
    pass


class DiamondShovelInitEvent(Event):
    """
    DiamondShovel初始化事件，在整个DiamondShovel项目启动时触发
    """
    def __init__(self, config, daemon):
        """
        :param ConfigParser config: 配置文件
        :param bool daemon: 是否以守护进程运行
        """
        self.config = config
        self.daemon = daemon


class WorkerPoolInitEvent(Event):
    """
    WorkerPool初始化事件
    """
    def __init__(self, pool):
        """
        :param WorkerPool pool: Worker pool实例
        """
        self.pool = pool


class WorkerEvent(Event):
    def __init__(self, plugin_name, worker_name):
        """
        :param str plugin_name: 插件名称
        :param str worker_name: worker名称
        """
        self.plugin_name = plugin_name
        self.worker_name = worker_name


class WorkerFinishEvent(WorkerEvent):
    def __init__(self, plugin_name, worker_name, error):
        """
        :param str plugin_name: 插件名称
        :param str worker_name: worker名称
        :param Any result: worker的执行结果
        """
        super().__init__(plugin_name, worker_name)
        self.error = error


class TaskEvent(Event):
    def __init__(self, task_context):
        """
        :param TaskContext task_context: 任务上下文
        """
        self.task_context = task_context


class TaskDispatchEvent(TaskEvent):
    """
    Task dispatching event, fired when the task is dispatched to workers
    """
    def __init__(self, task_context):
        """
        :param TaskContext task_context: 任务上下文
        """
        super().__init__(task_context)


class TaskReadTriggerEvent(TaskEvent):
    """
    Task reading event, fired when someone trying to read something from the task
    """
    def __init__(self, task_context, key, value):
        super().__init__(task_context)
        self.key = key
        self.value = value


class TaskWriteTriggerEvent(TaskEvent):
    """
    Task writing event, fired when someone trying to write something to the task
    """
    def __init__(self, task_context, key, value, old_value):
        super().__init__(task_context)
        self.key = key
        self.value = value
        self.old_value = old_value


def register_event(init_ctx, evt_class, handler):
    """
    register an event handler
    :param PluginInitContext init_ctx: the plugin init context
    :param type evt_class: the subclass of Event
    :param Callable handler: the event handler
    """
    if not issubclass(evt_class, Event):
        raise TypeError("evt_class must be a subclass of Event")
    if evt_class not in _event_handlers:
        _event_handlers[evt_class] = {}
    if init_ctx not in _event_handlers[evt_class]:
        _event_handlers[evt_class][init_ctx] = []
    _event_handlers[evt_class][init_ctx].append(handler)


@async_helper.disallows_direct_async
def call_event(evt):
    """
    invokes all event handlers that is related to the event
    :params evt: the event
    """
    if not isinstance(evt, Event):
        raise TypeError("evt must be an instance of Event")
    if evt.__class__ not in _event_handlers:
        return
    for init_ctx, handlers in _event_handlers[evt.__class__].items():
        if not is_plugin_enabled(init_ctx.plugin_name):
            continue
        with init_ctx.attach():
            for handler in handlers:
                handle_result = handler(evt)
                if asyncio.iscoroutine(handle_result):
                    async_helper.call_async(handle_result)

    if evt.__class__ in __event_futures__:
        for future in __event_futures__[evt.__class__]:
            future.set_result(evt)


async def wait_event(evt_class, evt_filter = lambda evt: True, timeout = 2147483647):
    """
    wait for an event
    :param Type[Event] evt_class: the class of event
    :param Callable evt_filter: the event filter
    :return: the event
    """
    loop = asyncio.get_running_loop()

    while True:
        future = loop.create_future()
        if evt_class not in __event_futures__:
            __event_futures__[evt_class] = []

        __event_futures__[evt_class].append(future)
        evt = await timed_await(future, timeout)
        __event_futures__[evt_class].remove(future)
        if evt is None or evt_filter(evt):
            return evt
