import configparser
from .result_tidy_up import *
from .retry_decorator import *
from .uuid_helper import generate_uuid

def clone_config(cfg):
    new_cfg = configparser.ConfigParser(interpolation=configparser.Interpolation())
    for section in cfg.sections():
        new_cfg.add_section(section)
        for key, value in cfg.items(section):
            new_cfg.set(section, key, value)
    return new_cfg
