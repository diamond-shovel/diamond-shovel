import configparser
import os
import shutil
import signal
import sys

from fastapi import APIRouter, UploadFile, HTTPException
from fastapi.params import Depends
from kink import di

from diamond_shovel.plugins.manage import plugin_table
from diamond_shovel.privileged import privileged_main

router = APIRouter(prefix="/manage", tags=["manage"])


@router.get('/restart')
def restart_slave():
    # we need to make sure that there's a root daemon
    # simple execve does the effect of restarting
    try:
        privileged_main.invoke_method(os, "execve", sys.argv[0], sys.argv, os.environ)
    except:
        pass # will raise EOF as execve terminates the behavior of root daemon

    # we are in a forked process running in `diamond-shovel` user, terminate self
    signal.raise_signal(signal.SIGINT)

@router.post('/plugin')
async def install_plugin(file: UploadFile, data_path = Depends(lambda: di["data_path"])):
    with open(data_path / "plugins" / file.filename, 'wb') as f:
        privileged_main.invoke_method(f, "write", await file.read())

@router.delete('/plugin/{plugin_name}')
def uninstall_plugin(plugin_name: str, data_path = Depends(lambda: di["data_path"])):
    if plugin_name not in plugin_table:
        raise HTTPException(status_code=404, detail="Plugin not found")

    shutil.rmtree(data_path / "plugins" / plugin_name)
    (data_path / "plugins" / plugin_table[plugin_name]['file']).unlink()

@router.post('/plugin/{plugin_name}')
def configure_plugin(plugin_name: str, plugin_config: dict, data_path = Depends(lambda: di["data_path"])):
    if not (data_path / "plugins" / plugin_name).exists():
        raise HTTPException(status_code=404, detail="Plugin not found")
    config_file = data_path / "plugins" / plugin_name / "config.ini"
    if not config_file.exists():
        raise HTTPException(status_code=404, detail="Config file not found")

    config = configparser.ConfigParser()
    config.read(config_file)

    for section, section_data in plugin_config.items():
        for key, value in section_data.items():
            config.set(section, key, value)

    with open(str(config_file), "w") as f:
        config.write(f)

@router.get('/plugin/{plugin_name}')
def get_plugin_configuration(plugin_name: str, data_path = Depends(lambda: di["data_path"])):
    if not (data_path / "plugins" / plugin_name).exists():
        raise HTTPException(status_code=404, detail="Plugin not found")
    config_file = data_path / "plugins" / plugin_name / "config.ini"
    if not config_file.exists():
        raise HTTPException(status_code=404, detail="Config file not found")

    config = configparser.ConfigParser()
    config.read(config_file)

    config_dict = {}
    for section, section_data in config.items():
        config_dict[section] = {}
        for key, value in section_data.items():
            config_dict[section][key] = value

    return config_dict
