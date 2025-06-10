import logging
import pathlib
import traceback

from kink import inject

from .load import load_plugin_plain, generate_enable_order


plugin_table: dict[str, dict] = {}

@inject
def load_plugins(data_path: pathlib.Path, whitelist: list[str] = None, blacklist: list[str] = None):
    """
    Load all plugins, from diamond shovel workdir
    :params data_path: the diamond shovel workdir
    :params whitelist: plugins to enable
    :params blacklist: plugins to disable
    """
    plugin_path = data_path / "plugins"

    if not plugin_path.exists():
        plugin_path.mkdir(parents=True)

    for file in plugin_path.iterdir():
        load_data = None

        try:
            if not file.is_file():
                continue
            if file.suffix == ".ore":
                raise ValueError("Paid plugin is not supported in Community Edition :(")
            if ".tar" in file.suffixes:
                load_info = load_plugin_plain(file)
                if load_info is None:
                    continue
                name, load_data = load_info
            if load_data:
                load_data['file'] = file
                plugin_table[name] = load_data
        except Exception:
            logging.error(f"Failed to load plugin {file}: {traceback.format_exc()}")

    enable_loaded_plugins(blacklist, whitelist)


def enable_loaded_plugins(blacklist, whitelist):
    """
    Enable all loaded plugins
    :params whitelist: plugins to enable
    :params blacklist: plugins to disable
    """
    load_order = []
    for plugin in generate_enable_order(plugin_table):
        skip_enable = False
        if whitelist and plugin not in whitelist:
            skip_enable = True
        if blacklist and plugin in blacklist:
            skip_enable = True

        module = plugin_table[plugin]['module']
        if not skip_enable:
            load_order.append(plugin)
        if hasattr(module, "load"):
            with plugin_table[plugin]['init_context'].attach():
                try:
                    module.load()
                except Exception:
                    logging.error(f"Failed to load plugin {plugin}: {traceback.format_exc()}")
                    if plugin in load_order:
                        load_order.remove(plugin)
                    continue
    for plugin in load_order:
        set_plugin_enabled(plugin, True)


def set_plugin_enabled(plugin_name: str, enabled: bool):
    """
    Sets the plugin enable state
    :params plugin_name: target plugin name
    :params enabled: whether enabled
    """
    if plugin_name not in plugin_table:
        raise ValueError(f"Plugin {plugin_name} not found")
    if enabled == plugin_table[plugin_name].get("enabled", False):
        return

    plugin_table[plugin_name]["enabled"] = enabled
    module = plugin_table[plugin_name]["module"]
    if enabled:
        if hasattr(module, "enable"):
            with plugin_table[plugin_name]['init_context'].attach():
                try:
                    module.enable()
                except Exception:
                    logging.error(f"Failed to enable plugin {plugin_name}: {traceback.format_exc()}")
                    set_plugin_enabled(plugin_name, False)
    else:
        if hasattr(module, "disable"):
            with plugin_table[plugin_name]['init_context'].attach():
                try:
                    module.disable()
                except Exception:
                    logging.error(f"Failed to disable plugin {plugin_name}: {traceback.format_exc()}")

def is_plugin_enabled(plugin_name: str):
    """
    Checks if plugin is enabled
    :params plugin_name: target plugin to check
    :returns: True if enabled
    """
    return plugin_table[plugin_name].get("enabled", False)
