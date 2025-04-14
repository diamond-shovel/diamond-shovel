import os
import pathlib
import shutil
from typing import Annotated

from fastapi import APIRouter, HTTPException, Body, Depends, UploadFile
from kink import di

import diamond_shovel.plugins
from diamond_shovel.function.task import worker_pool

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
def enable_plugin(plugin_name: Annotated[str, Body(embed=True)]):
    if plugin_name not in diamond_shovel.plugins.manage.plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")
    diamond_shovel.plugins.manage.set_plugin_enabled(plugin_name, True)

@router.delete("/{plugin_name}")
def disable_plugin(plugin_name: Annotated[str, Body(embed=True)]):
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

@router.post("/install")
def install_plugin(file: UploadFile, data_path: pathlib.Path = Depends(lambda: di["data_path"])):
    plugin_path = data_path / "plugins"
    if not plugin_path.exists():
        plugin_path.mkdir(parents=True)

    upload_path = plugin_path / file.filename
    with open(upload_path, "wb") as f:
        f.write(file.file.read())

    plugin_name = diamond_shovel.plugins.load_plugin(plugin_path)
    diamond_shovel.plugins.set_plugin_enabled(plugin_name, True)

@router.get("/uninstall/{plugin_name}")
def uninstall_plugin(plugin_name: str, data_path: pathlib.Path = Depends(lambda: di["data_path"])):
    plugin_path = data_path / "plugins" / plugin_name
    if not plugin_path.exists() or plugin_name not in diamond_shovel.plugins.manage.plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")

    plugin = diamond_shovel.plugins.manage.plugin_table.get(plugin_name)
    worker_pool.wipe_plugin_workers(diamond_shovel.plugins.plugin_list[plugin_name])
    diamond_shovel.plugins.set_plugin_enabled(plugin_name, False)
    shutil.rmtree(plugin_path)
    os.unlink(plugin["file"])
