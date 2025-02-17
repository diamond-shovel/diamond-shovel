import pathlib
from configparser import ConfigParser

from kink import di

from diamond_shovel.cli import historian
from diamond_shovel.install import config_generation


def init(daemon: bool = False, root: pathlib.Path = pathlib.Path("/")):
    if not daemon:
        config_target = "diamond-shovel.ini"
        config_generation.generate_config(pathlib.Path.cwd())
        di["data_path"] = pathlib.Path.cwd()
        di["config_path"] = pathlib.Path.cwd()
    else:
        config_path = root / "etc" / "diamond-shovel"
        di["config_path"] = config_path
        config_target = config_path / "diamond-shovel.ini"
        di["data_path"] = root / "var" / "lib" / "diamond-shovel"

    with open(config_target, 'r', encoding='utf-8') as f:
        config = ConfigParser(allow_no_value=True)
        config.read_file(f)
        di['config'] = config
    historian.setup_logger()

if __name__ == '__main__':
    init(daemon=False)
