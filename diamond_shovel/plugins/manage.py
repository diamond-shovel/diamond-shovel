import logging
import pathlib
import traceback

import loguru
from kink import inject

from . import events
from .load import load_plugin_plain, generate_enable_order


plugin_table: dict[str, dict] = {}

@inject
def load_plugins(data_path: pathlib.Path, whitelist: list[str] = None, blacklist: list[str] = None):
    plugin_path = data_path / "plugins"

    if not plugin_path.exists():
        plugin_path.mkdir(parents=True)

    for file in plugin_path.iterdir():
        try:
            if not file.is_file():
                continue
            if file.suffix == ".ore":
                raise ValueError("Paid plugin is not supported in Community Edition :(")
            load_plugin(file)
        except Exception:
            loguru.logger.error(f"Failed to load plugin {file}: {traceback.format_exc()}")

    enable_loaded_plugins(blacklist, whitelist)

def load_plugin(file):
    if ".tar" in file.suffixes:
        name, load_data = load_plugin_plain(file)
    else:
        logging.warning(f"Unknown plugin type: {file}")
        return

    load_data["file"] = file

    if load_data:
        plugin_table[name] = load_data

    module = plugin_table[name]
    if hasattr(module, "load"):
        with module['init_context'].attach():
            try:
                module['module'].load()
            except Exception:
                logging.error(f"Error while loading plugin: {name} - {traceback.format_exc()}")
                if name in plugin_table:
                    del plugin_table[name]

    return name

def enable_loaded_plugins(blacklist, whitelist):
    load_order = []
    for plugin in generate_enable_order(plugin_table):
        skip_enable = False
        if whitelist and plugin not in whitelist:
            skip_enable = True
        if blacklist and plugin in blacklist:
            skip_enable = True

        if not skip_enable:
            load_order.append(plugin)
    for plugin in load_order:
        set_plugin_enabled(plugin, True)

def set_plugin_enabled(plugin_name: str, enabled: bool):
    if plugin_name not in plugin_table:
        raise ValueError(f"Plugin {plugin_name} not found")
    if enabled == plugin_table[plugin_name].get("enabled", False):
        return

    plugin_table[plugin_name]["enabled"] = enabled
    module = plugin_table[plugin_name]["module"]
    ctx = plugin_table[plugin_name]["init_context"]
    if enabled:
        if hasattr(module, "enable"):
            with ctx.attach():
                try:
                    module.enable()
                except Exception:
                    logging.error(f"Failed to enable plugin {plugin_name}: {traceback.format_exc()}")
                    set_plugin_enabled(plugin_name, False)
    else:
        if hasattr(module, "disable"):
            with ctx.attach():
                try:
                    module.disable()
                except Exception:
                    logging.error(f"Failed to disable plugin {plugin_name}: {traceback.format_exc()}")

        for evt_class, handler_list in events._handlers.items():
            if plugin_name in handler_list:
                del handler_list[plugin_name]

def is_plugin_enabled(plugin_name: str):
    return plugin_table[plugin_name].get("enabled", False)
