import contextlib
import datetime
import inspect
import logging
import pathlib
import re
import tarfile
import threading
from configparser import ConfigParser
from typing import Mapping

from colorlog import ColoredFormatter
from kink import inject

from diamond_shovel.function.task import current_task_context
from diamond_shovel.plugins.manage import plugin_table

default_config = ConfigParser()
default_config.add_section('logging')
default_config.set('logging', 'directory', '.')
default_config.set('logging', 'level', '10')
default_config.set('logging', 'color', 'true')

target_file = None


class LenientFormatLogRecord(logging.LogRecord):
    def getMessage(self):
        msg = str(self.msg)
        if self.args:
            msg = re.sub(r'%(\((.+?)\))?[A-Za-z]', r"{\2}", msg)
            if isinstance(self.args, Mapping):
                msg = msg.format(**self.args)
            else:
                msg = msg.format(*self.args)
        return msg


class ThreadedTaskContextLogHandler(logging.Handler):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._target_thread = threading.current_thread()

    def filter(self, record):
        return record.thread == self._target_thread.ident

    def emit(self, record):
        self.ctx.log(self.format(record))


class TaskContextLogHandler(logging.Handler):
    def emit(self, record):
        ctx = current_task_context()
        if ctx is None:
            return
        ctx.log(self.format(record))


def find_issuing_plugin():
    for f in inspect.stack():
        if f.frame.f_globals['__package__'] in plugin_table:
            return f.frame.f_globals['__package__']
    return 'diamond_shovel'


def format_running_logger(*args, **kwargs):
    rec = LenientFormatLogRecord(*args, **kwargs)
    rec.runner = find_issuing_plugin()
    return rec


def wipe_old_handler(logger):
    for handler in logger.handlers:
        if hasattr(handler, 'shovel_attached'):
            logger.removeHandler(handler)


def archive_legacy(directory):
    global target_file

    today = datetime.datetime.today()
    i = 0
    while True:
        log_file = pathlib.Path(directory).joinpath(f'{today.strftime("%Y-%m-%d")}-{i}.log')
        compressed_log_file = log_file.with_suffix('.log.tar.gz')
        i += 1
        if not log_file.exists(follow_symlinks=True) and not compressed_log_file.exists(follow_symlinks=True):
            return i
        if not compressed_log_file.exists(follow_symlinks=True):
            with tarfile.open(compressed_log_file, 'w:gz') as f:
                f.add(log_file)
            log_file.unlink(missing_ok=True)


def new_log(directory, idx):
    global target_file
    today = datetime.datetime.today()
    target_file = pathlib.Path(directory).joinpath(f'{today.strftime("%Y-%m-%d")}-{idx}.log')
    return target_file

_config = {}


@inject
def setup_logger(config: ConfigParser = default_config):
    wipe_old_handler(logging.root)

    logging.setLogRecordFactory(format_running_logger)

    fmt = '[%(asctime)s][%(runner)s/%(levelname)s]: %(message)s'
    color_fmt = '[%(cyan)s%(asctime)s%(reset)s][%(runner)s/%(log_color)s%(levelname)s%(reset)s]: %(log_color)s%(message)s'
    log_dir = config.get('logging', 'directory')
    level = config.getint('logging', 'level')
    datefmt = "%H:%M:%S"

    _config['color_fmt'] = color_fmt
    _config['config'] = config
    _config['datefmt'] = datefmt
    _config['level'] = level

    idx = archive_legacy(log_dir)

    logging.basicConfig(level=level, filename=new_log(log_dir, idx), filemode='w',
                        format=fmt, datefmt=datefmt)

    put_handler(logging.StreamHandler())
    put_handler(TaskContextLogHandler())


def put_handler(handler):
    handler.setLevel(_config['level'])
    setattr(handler, 'shovel_attached', True)
    color_formatter = ColoredFormatter(
        _config['color_fmt'],
        datefmt=_config['datefmt'],
        reset=True,
        log_colors={
            'DEBUG': 'green',
            'INFO': 'blue',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        },
        secondary_log_colors={},
        style='%',
        no_color=not _config['config'].getboolean('logging', 'color')
    )
    handler.setFormatter(color_formatter)
    logging.root.addHandler(handler)


def remove_handler(handler):
    logging.root.removeHandler(handler)


@contextlib.contextmanager
def threaded_context_handler(ctx):
    handler = None
    if ctx is not None:
        handler = ThreadedTaskContextLogHandler(ctx)
        put_handler(handler)

    try:
        yield
    finally:
        if handler is not None:
            remove_handler(handler)


@contextlib.contextmanager
def duplicate_threaded_context_handler(prev):
    handler = None
    if prev is not None:
        handler = ThreadedTaskContextLogHandler(prev.ctx)
        put_handler(handler)

    try:
        yield
    finally:
        if handler is not None:
            remove_handler(handler)


def get_current_thread_handler():
    for handler in logging.root.handlers:
        if isinstance(handler, ThreadedTaskContextLogHandler):
            if handler._target_thread == threading.current_thread():
                return handler
