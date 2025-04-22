from fastapi import APIRouter, HTTPException

import diamond_shovel.plugins

router = APIRouter(prefix="/plugin", tags=["plugin"])

@router.get("/")
def list_plugins():
    result = {}
    for plugin_name in diamond_shovel.plugins.manage.plugin_table:
        result[plugin_name] = {
            "enabled": diamond_shovel.plugins.manage.is_plugin_enabled(plugin_name),
            "version": diamond_shovel.plugins.manage.plugin_table[plugin_name]["version"],
            "tags": diamond_shovel.plugins.manage.plugin_table[plugin_name]["tags"],
            "description": diamond_shovel.plugins.manage.plugin_table[plugin_name]["description"],
            "help": diamond_shovel.plugins.manage.plugin_table[plugin_name]["help"]
        }
    return result

@router.put("/{plugin_name}")
def enable_plugin(plugin_name: str):
    if plugin_name not in diamond_shovel.plugins.manage.plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")
    diamond_shovel.plugins.manage.set_plugin_enabled(plugin_name, True)

@router.delete("/{plugin_name}")
def disable_plugin(plugin_name: str):
    if plugin_name not in diamond_shovel.plugins.manage.plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")
    diamond_shovel.plugins.manage.set_plugin_enabled(plugin_name, False)

@router.get("/{plugin_name}")
def get_plugin(plugin_name: str):
    if plugin_name not in diamond_shovel.plugins.manage.plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {
        "enabled": diamond_shovel.plugins.manage.is_plugin_enabled(plugin_name),
        "version": diamond_shovel.plugins.manage.plugin_table[plugin_name]["version"],
        "tags": diamond_shovel.plugins.manage.plugin_table[plugin_name]["tags"],
        "description": diamond_shovel.plugins.manage.plugin_table[plugin_name]["description"],
        "help": diamond_shovel.plugins.manage.plugin_table[plugin_name]["help"]
    }
