import os
import pathlib
from configparser import ConfigParser, Interpolation


def environ(key):
    try:
        return os.environ[key]
    except KeyError:
        return None


def generate_config(target_dir: pathlib.Path):
    config_file_path = target_dir / 'diamond-shovel.ini'

    if config_file_path.exists():
        return

    config_file_path.touch(exist_ok=True, mode=0o644)

    with open(config_file_path, 'w', encoding='utf-8') as f:
        config = ConfigParser(interpolation=Interpolation())

        config.add_section('global')
        config.set('global', 'encoding', environ('ENCODING') or 'utf-8')

        config.add_section('logging')
        config.set('logging', 'directory', '/var/log/diamond-shovel/')
        config.set('logging', 'level', '1')
        config.set('logging', 'color', 'true')

        config.add_section('plugin')
        config.set('plugin', 'library-index', 'https://mirrors.aliyun.com/pypi/simple/')

        config.write(f)

        f.flush()


if __name__ == "__main__":
    generate_config(pathlib.Path.cwd())
