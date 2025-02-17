import configparser

def clone_config(cfg):
    new_cfg = configparser.ConfigParser(interpolation=configparser.Interpolation())
    for section in cfg.sections():
        new_cfg.add_section(section)
        for key, value in cfg.items(section):
            new_cfg.set(section, key, value)
    return new_cfg
