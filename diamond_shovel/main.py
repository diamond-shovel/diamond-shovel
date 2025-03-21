import argparse
import asyncio
import base64
import json
import logging
import multiprocessing
import os
import pathlib
import sys
import pwd
from concurrent.futures.thread import ThreadPoolExecutor

import loguru
from kink import di

import diamond_shovel.config
import diamond_shovel.slave.server
import diamond_shovel.utils.func
from diamond_shovel.cli import historian
from diamond_shovel.function.binary_manager import BinaryManager
from diamond_shovel.utils.func import json_util


def main():
    diamond_shovel.utils.func.init()

    parser = argparse.ArgumentParser(prog=sys.argv[0],
                                     description="资产扫描及漏洞发现工具")

    init_parser_arguments(parser)

    args = parser.parse_args(sys.argv[1:])
    di["args"] = args

    historian.setup_logger()

    if args.install:
        import diamond_shovel.install as install
        install.perform_installation(args.root)
        sys.exit(0)
    elif args.uninstall:
        import diamond_shovel.install as install
        install.perform_removal(args.root)
        sys.exit(0)

    di[BinaryManager] = BinaryManager()
    diamond_shovel.config.init(args.daemon, args.root)

    if args.plugin:
        install_plugin(args)

    whitelist = args.enable_plugin
    blacklist = args.disable_plugin
    di[ThreadPoolExecutor] = ThreadPoolExecutor(thread_name_prefix="shovel_runner")

    if whitelist and blacklist:
        whitelist = None

    if not args.target and not args.domain and not args.ip and not args.json and not args.extras and not args.daemon:
        parser.print_help()
    elif args.daemon:
        run_daemon(args)
    else:
        run_once(args, blacklist, whitelist)


def init_parser_arguments(parser):
    parser.add_argument("-I", "--install", help="安装必要文件", action="store_true")
    parser.add_argument("-u", "--uninstall", help="卸载", action="store_true")
    parser.add_argument("-P", "--plugin", help="安装插件", type=pathlib.Path, default=None)
    parser.add_argument("-t", "--target", help="目标公司", nargs="*", default=[], type=str)
    parser.add_argument("-d", "--domain", help="目标域名", nargs="*", default=[], type=str)
    parser.add_argument("-i", "--ip", help="目标ip", nargs="*", default=[], type=str)
    parser.add_argument("-j", "--json", help="从json文件中读取目标", type=pathlib.Path)
    parser.add_argument("-J", "--out-json", help="设置json结果输出目录", type=pathlib.Path,
                        default=pathlib.Path("./diamond-shovel-result.json"))
    parser.add_argument("--enable-plugin", type=str, default=None, help="启用插件", nargs="*")
    parser.add_argument("--disable-plugin", type=str, default=None, help="禁用插件", nargs="*")

    parser.add_argument("-D", "--daemon", help="以守护模式运行", type=bool, default=False)
    parser.add_argument("-U", "--daemon-url", help="守护进程将会监听的URL", type=str, default="unix://%2fvar%2frun%2fdiamond_shovel.sock")

# We won't switch user if they use root for running once, they should be alerted for what they are doing.
def run_once(args, blacklist, whitelist):
    target_companies = args.target if args.target else []
    target_domains = args.domain if args.domain else []
    target_ips = args.ip if args.ip else []

    if args.json:
        with open(args.json, "r") as f:
            data = json.load(f)
            target_companies.extend(data.get("companies", []))
            target_domains.extend(data.get("domains", []))
            target_ips.extend(data.get("ips", []))


    # we'll use cwd if we are not installed to the system, like how Minecraft server did.
    # everything will be isolated there.
    di["run_context"] = {
        "root": '/' if check_installation() else os.getcwd(),
        "daemon": False
    }

    from . import plugins
    plugins.load_plugins(whitelist=whitelist, blacklist=blacklist)
    from .plugins import events
    events.call_event(events.DiamondShovelInitEvent(di["config"], False))

    from diamond_shovel.function import task
    task.init()
    ctx = task.TaskContext()

    if args.extras:
        extras = json.loads(base64.b64decode(args.extras).decode('utf-8'))
    else:
        extras = {}

    for key, value in extras.items():
        ctx[key] = value

    def merge_list(ctx, key, value):
        if key in ctx:
            tmp = ctx[key]
            tmp.extend(value)
            ctx[key] = tmp
        else:
            ctx[key] = value

    merge_list(ctx, "target_companies", target_companies)
    merge_list(ctx, "target_domains", target_domains)
    merge_list(ctx, "target_ips", target_ips)
    if args.config:
        config = json.loads(base64.b64decode(args.config).decode('utf-8'))
    else:
        config = {}

    logging.debug(f"Starting with config: {config}")

    for plugin_name, plugin_config in config.items():
        cfg = ctx.get_plugin_config(plugin_name)
        for section, values in plugin_config.items():
            if section not in cfg:
                cfg[section] = {}
            for key, value in values.items():
                if value is None or len(str(value)) == 0:
                    continue

                if key not in cfg[section]:
                    cfg[section][key] = str(value)

    with open(args.out_json, "w") as f:
        scan_result = asyncio.run(task.run_full_scan(ctx))
        try:
            f.write(json.dumps(scan_result, indent=4, cls=json_util.ExceptionExtendedEncoder))
        except Exception as e:
            scan_result['deserialization_failure'] = e
            f.write(json.dumps(scan_result, indent=4, cls=json_util.ExceptionExtendedEncoder, skipkeys=True))
    out_json_abs_path = os.path.abspath(args.out_json)
    loguru.logger.success(f"Output json file path: {out_json_abs_path}")

def run_daemon(args):
    if not check_installation():
        logging.error("请先安装diamond-shovel")
        sys.exit(1)

    if os.geteuid() != 0:
        logging.error("守护模式需要root权限运行")
        sys.exit(1)

    start_root_daemon()

    os.setuid(pwd.getpwnam("diamond-shovel").pw_uid)

    di["run_context"] = {
        "root": "/",
        "daemon": True
    }
    diamond_shovel.slave.server.start_api_slave(args.daemon_url)

# For low-level PoC that might want special capabilities, use root directly.
def start_root_daemon():
    from . import privileged
    privileged.privileged_main.key = os.urandom(32)
    queue = multiprocessing.Queue()
    parent_pipe, child_pipe = multiprocessing.Pipe()
    privileged_process = multiprocessing.Process(target=privileged.run, args=(queue, child_pipe), daemon=True)
    privileged.set_privileged_context(queue, parent_pipe)
    privileged_process.start()

def install_plugin(args):
    if check_installation() and os.geteuid() != 0:
        logging.error("请以root权限运行")
        sys.exit(1)

    plugin_file = args.plugin
    plugin_dir = di["data_path"] / "plugins"
    if not plugin_dir.exists():
        plugin_dir.mkdir()
    plugin_file.rename(plugin_dir / plugin_file.name)
    logging.info(f"插件{plugin_file.name}安装成功")
    sys.exit(0)

# we consider that diamond-shovel user will be available if installed to the system via package manager, or something
def check_installation() -> bool:
    return pwd.getpwnam('diamond-shovel') is not None

if __name__ == "__main__":
    main()
