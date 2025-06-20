import asyncio
import configparser
import csv
import importlib
import importlib.abc
import inspect
import io
import json
import logging
import os
import pathlib
import re
import sys
import tarfile
import threading
import types
import typing
from concurrent.futures import ThreadPoolExecutor
from configparser import ConfigParser
from contextlib import contextmanager

import kink
from kink import inject, di, Container

from diamond_shovel.function.binary_manager import BinaryManager
from diamond_shovel.plugins import library
from diamond_shovel.utils.func import async_helper


class PluginInitContext:
    """
    The context that describes a plugin, usually for initialization
    """
    @inject
    def __init__(self, plugin_name, archive: tarfile.TarFile, run_context: dict[str, typing.Any],
                 data_path: pathlib.Path):
        self.plugin_name = plugin_name
        self._data_folder = data_path / "plugins" / plugin_name
        self._config_overrider = []

        self._config_file = self._data_folder / "config.ini"
        self._run_context = run_context
        self._archive = archive

        self._plugin_dependency_container = {}

        self.setup_base_container()

        self._threaded_attached_modified_container = {}

        # trigger config extraction
        _ = self.config

    def setup_base_container(self):
        """
        Initializes the dependency container of current plugin
        """
        self._plugin_dependency_container[BinaryManager] = di[BinaryManager]
        self._plugin_dependency_container[ConfigParser] = self.config
        self._plugin_dependency_container["data_folder"] = self.data_folder
        self._plugin_dependency_container[PluginInitContext] = self
        self._plugin_dependency_container[ThreadPoolExecutor] = di[ThreadPoolExecutor]

    @property
    def config(self) -> configparser.ConfigParser:
        """
        Fetches the config of current plugin
        """
        config = configparser.ConfigParser(interpolation=configparser.Interpolation())

        if not self._config_file.exists():
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            if any([tarinfo for tarinfo in self._archive.getmembers() if tarinfo.name == 'config.ini']):
                self.extract_resource("config.ini")
        if self._config_file.exists():
            with open(self._config_file, "r") as f:
                config.read_file(f)

        for overrider in reversed(self._config_overrider):
            for section, values in overrider.items():
                if not config.has_section(section):
                    config.add_section(section)
                for key, value in values.items():
                    logging.debug(f"Overriding {section}.{key} with {value}")
                    config.set(section, key, str(value))

        return config

    def override_config(self, config):
        """
        Overrides default config with provided config
        :params config: config to override
        """
        logging.debug(f"{self.plugin_name}'s config overridden by {config}")
        self._config_overrider.append(config)
        self._plugin_dependency_container[ConfigParser] = self.config # we need a refresh.
        logging.debug(f"Current config: { {section: {key: value for key, value in self.config.items(section)} for section in self.config.sections()} }")

    def restore_config(self):
        """
        Restore all config to default
        """
        self._config_overrider = self._config_overrider[:-1]
        self._plugin_dependency_container[ConfigParser] = self.config

    @property
    def data_folder(self) -> pathlib.Path:
        """
        Gets data folder
        :returns: the path to data folder
        """
        if not self._data_folder.exists():
            self._data_folder.mkdir(parents=True)
        return self._data_folder

    @contextmanager
    def open_resource(self, name: str) -> typing.Generator[io.IOBase, None, None]:
        """
        Reads resource from plugin archive
        :params name: resource name
        :returns: stream of resource
        """
        f = None
        try:
            f = self._archive.extractfile(name)
            yield f
        finally:
            if f:
                f.close()

    def extract_resource(self, name: str, replace: bool = False):
        """
        Extracts a resource from plugin archive to file with same name, under the data folder
        :params name: resource name
        :params replace: whether to replace original resource
        """
        if not replace and (self.data_folder / name).exists():
            return

        with self.open_resource(name) as f:
            with open(str(self.data_folder / name), "wb") as dest:
                dest.write(f.read())
                dest.flush()
        logging.debug("Extracted resource %s to %s", name, self.data_folder / name)
        logging.debug("Existence check: %s", (self.data_folder / name).exists())

    def fetch_current_container(self, extras={}):
        """
        Gets the current dependency container on cureent thread or eventloop, for dependency injection
        :returns: current dependency container
        """
        if async_helper.is_current_async():
            current_thread = asyncio.get_running_loop()
            container = self._threaded_attached_modified_container.get(current_thread)
        else:
            current_thread = threading.current_thread()
            container = self._threaded_attached_modified_container.get(current_thread)

        if container is None:
            container = Container()
            for key, values in self._plugin_dependency_container.items():
                container[key] = values

        for key, values in extras.items():
            container[key] = values

        self._threaded_attached_modified_container[current_thread] = container

        return container

    # this seems to be still useful even diamond_shovel.plugins.injects.inject is there.
    # see its document.
    @contextmanager
    def attach(self, extras={}):
        """
        Attach to current container
        """
        old_di = kink.di
        setattr(kink, "di", self.fetch_current_container(extras))

        try:
            yield
        finally:
            setattr(kink, "di", old_di)


class PluginModuleLoader(importlib.abc.Loader):
    """
    Internal loader of plugins
    """
    def __init__(self, tar_file: tarfile.TarFile, plugin_name: str, plugin_ctx: PluginInitContext):
        self._tar_file = tar_file
        self._plugin_name = plugin_name
        self._ctx = plugin_ctx

        self._module_cache = {}

    def create_module(self, spec):
        if spec.name in self._module_cache:
            return self._module_cache[spec.name]

        module_path = self.find_module(spec.name)
        if module_path:
            logging.debug(f"Loading module {spec.name} from {module_path}")
            module = types.ModuleType(spec.name)
            module.__file__ = module_path
            module.__loader__ = self
            return module

    def find_module(self, fullname):
        extensions = [".py", ".pyc", ".pyo"]
        file_name = fullname.replace(".", "/").replace(self._plugin_name + "/", "")
        for ext in extensions:
            try:
                if self._tar_file.getmember(file_name + ext):
                    return file_name + ext
            except KeyError:
                pass

        return None

    def exec_module(self, module):
        find_module = self.find_module(module.__name__ + ".__init__")
        if not find_module:
            find_module = self.find_module(module.__name__)

        if find_module:
            with self._tar_file.extractfile(find_module) as f:
                code = f.read()
            with self._ctx.attach():
                module.__dict__.update(
                    {"plugin_context": self._ctx, "di": self._ctx._plugin_dependency_container})
                exec(code, module.__dict__)

    def load_module(self, fullname):
        module = self.create_module(importlib.machinery.ModuleSpec(self.plugin_name + "." + fullname, self,
                                                                   is_package=self.is_module_package(fullname)))
        if module:
            self.exec_module(module)
            return module
        else:
            raise ModuleNotFoundError(fullname + ":" + self._plugin_name)

    @property
    def plugin_name(self):
        """
        Gets current plugin name
        :returns: current plugin name
        """
        return self._plugin_name

    def is_module_package(self, fullname):
        """
        Checks if target is a python package
        :returns: True if target is a python package
        """
        mod = self.find_module(fullname + ".__init__")
        return mod is not None


class PluginModuleFinder(importlib.abc.MetaPathFinder):
    def __init__(self, loader: PluginModuleLoader):
        self._loader = loader

    def find_spec(self, fullname, path, target=None):
        # Make them under namespace of plugin. we don't want module conflicts
        if fullname == self._loader.plugin_name:
            return importlib.machinery.ModuleSpec(fullname, self._loader,
                                                  is_package=True)

        request_stack = inspect.stack()[4]
        requester = inspect.stack()[4].frame.f_globals['__name__'].split('.')[0]
        if request_stack.filename == '<string>' and requester != self._loader.plugin_name:
            return None

        if not fullname.startswith(self._loader.plugin_name):
            fullname = self._loader.plugin_name + "." + fullname

        module_path = self._loader.find_module(fullname)
        if module_path:
            return importlib.machinery.ModuleSpec(fullname, self._loader,
                                                  is_package=self._loader.is_module_package(fullname))


def load_plugin_tar(tar: tarfile.TarFile):
    """
    Load a plugin from tar file
    :params tar: target tar file
    """
    if "plugin.ini" not in tar.getnames():
        return

    reader = tar.extractfile(tar.getmember("plugin.ini"))
    config, dependencies, entrypoint, help, name, version = read_plugin_metadata(reader, tar)

    logging.info("Loading plugin %s v%s", name, version)

    check_plugin_python_dependencies(config)
    check_plugin_os_dependencies(config)
    return make_plugin(config, dependencies, entrypoint, help, name, tar, version)


def make_plugin(config, dependencies, entrypoint, help, name, tar, version):
    """
    Initializes a plugin context from provided information
    :params config: plugin metadata
    :params dependencies: plugin dependencies
    :params entrypoint: plugin entrypoint
    :params help: help information
    :params name: plugin name
    :params tar: plugin tar
    :params version: plugin version
    """
    ctx = PluginInitContext(name, tar)
    sys.meta_path.append(PluginModuleFinder(PluginModuleLoader(tar, name, ctx)))
    importlib.invalidate_caches()
    module = importlib.import_module("." + entrypoint, name)
    return name, {
        "module": module,
        "dependencies": dependencies,
        "init_context": ctx,
        "version": version,
        "help": help,
        "tags": config["plugin"].get("tags", "").split(" "),
        "description": config["plugin"].get("description")
    }


def check_plugin_os_dependencies(config):
    """
    Checks the system dependencies of plugin
    :params config: plugin metadata
    """
    os_dependencies = config["plugin"].get("os_dependencies")
    if os_dependencies:
        parser = csv.reader([os_dependencies])
        for dep in list(*parser):
            exist, suggestion = library.check_os_libraries(dep.strip())
            if not exist:
                raise ValueError(f"Missing OS dependency {dep.strip()}. {suggestion}")


def check_plugin_python_dependencies(config):
    """
    Checks and fetches dependencies of plugin
    :params config: plugin metadata
    """
    python_dependencies = config["plugin"].get("package_dependencies")
    if python_dependencies:
        parser = csv.reader([python_dependencies])
        for dep in list(*parser):
            library.fetch_python_library(dep.strip())


def read_plugin_metadata(reader, tar):
    """
    Extract information from plugin metadata
    :params reader: reader to metadata file
    :params tar: the plugin tar
    """
    config = configparser.ConfigParser()
    config.read_string(reader.read().decode())
    name = config["plugin"]["name"]
    entrypoint = config["plugin"]["entry_point"]
    if "help.json" in tar.getnames():
        with tar.extractfile(tar.getmember("help.json")) as f:
            help = json.load(f)
    else:
        help = {}
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        raise ValueError(f"Invalid plugin name {name}")
    version = config["plugin"]["version"]
    dependencies_raw = config["plugin"].get("dependencies")
    if dependencies_raw:
        parser = csv.reader([dependencies_raw])
        dependencies = [n for i, n in (enumerate(f) for f in parser)]
    else:
        dependencies = []
    return config, dependencies, entrypoint, help, name, version


def load_plugin_plain(file: pathlib.Path):
    """
    Load a plain plugin, from plugin tar
    :params file: the plugin file to load
    :returns: the loaded plugin
    """
    return load_plugin_tar(tarfile.open(file, "r:*"))


def generate_enable_order(plugin_table):
    """
    Generates enable order, tries to avoid dependency problems
    :params plugin_table: the plugin table
    :returns: the order of plugin enabling
    """
    plugin_dict_clone = plugin_table.copy()

    def visit(plugin_name, dependency_stack):
        if plugin_name in plugin_table:
            if not plugin_name in plugin_dict_clone:  # already visited
                return
            for dependency in plugin_table[plugin_name]["dependencies"]:
                yield from visit(dependency, dependency_stack + [plugin_name])
            del plugin_dict_clone[plugin_name]
            yield plugin_name
        else:
            raise ValueError(f"Plugin {plugin_name} not found, required by {dependency_stack}")

    for plugin in plugin_table:
        yield from visit(plugin, [])
