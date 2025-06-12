import argparse
import json
import logging
import multiprocessing
import os
import pathlib
import pwd
import sys
from concurrent.futures.thread import ThreadPoolExecutor

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
        install.perform_installation()
        sys.exit(0)
    elif args.uninstall:
        import diamond_shovel.install as install
        install.perform_removal()
        sys.exit(0)

    di[BinaryManager] = BinaryManager()
    diamond_shovel.config.init(args.daemon, args.daemon_config, args.daemon_workdir)

    if args.plugin:
        install_plugin(args)

    if os.geteuid() == 0:
        # we need start root daemon even running under cmdline
        # for plugin compatibility
        start_root_daemon()
        if args.daemon:
            os.setuid(pwd.getpwnam("diamond-shovel").pw_uid)

    whitelist = args.enable_plugin
    blacklist = args.disable_plugin
    di[ThreadPoolExecutor] = ThreadPoolExecutor(thread_name_prefix="shovel_runner")

    if whitelist and blacklist:
        whitelist = None

    if not args.target and not args.domain and not args.ip and not args.json and not args.daemon:
        parser.print_help()
    elif args.daemon:
        run_server(args)
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

    parser.add_argument("-D", "--daemon", help="以Daemon模式运行", action="store_true")
    parser.add_argument("-U", "--daemon-url", help="Daemon将会监听的URL", type=str, default="unix:///var/run/diamond_shovel.sock")
    parser.add_argument("--daemon-config", help="Daemon将会使用的配置文件路径", type=pathlib.Path, default=pathlib.Path("/etc/diamond-shovel"))
    parser.add_argument("--daemon-workdir", help="Daemon将会使用的工作目录", type=pathlib.Path, default=pathlib.Path("/var/lib/diamond-shovel"))

    parser.set_defaults(daemon=False)


def run_server(args):
    di["run_context"] = {
        "root": args.daemon_workdir,
        "daemon": True
    }
    os.chdir(args.daemon_workdir)

    from . import plugins
    plugins.load_plugins(whitelist=[], blacklist=[])
    from .plugins import events
    from .function import task
    events.call_event(events.DiamondShovelInitEvent(di["config"], False))
    task.init()

    diamond_shovel.slave.server.start_api_slave(args.daemon_url)


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

    di["run_context"] = {
        "root": os.getcwd(),
        "daemon": False
    }

    from . import plugins
    plugins.load_plugins(whitelist=whitelist, blacklist=blacklist)
    from .plugins import events
    events.call_event(events.DiamondShovelInitEvent(di["config"], False))

    from diamond_shovel.function import task
    task.init()
    ctx = task.TaskContext()

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

    with open(args.out_json, "w") as f:
        scan_result = ctx.get_assigned_event_loop().run_until_complete(task.run_full_scan(ctx))
        try:
            f.write(json.dumps(scan_result, indent=4, cls=json_util.ExceptionExtendedEncoder))
        except Exception as e:
            scan_result['deserialization_failure'] = e
            f.write(json.dumps(scan_result, indent=4, cls=json_util.ExceptionExtendedEncoder, skipkeys=True))
    out_json_abs_path = os.path.abspath(args.out_json)
    logging.info(f"Output json file path: {out_json_abs_path}")

    from diamond_shovel import privileged
    privileged.terminate()


def start_root_daemon():
    from . import privileged
    privileged.privileged_main.key = os.urandom(32)
    queue = multiprocessing.Queue()
    parent_pipe, child_pipe = multiprocessing.Pipe()
    privileged_process = multiprocessing.Process(target=privileged.run, args=(queue, child_pipe))
    privileged.set_privileged_context(queue, parent_pipe)
    privileged_process.start()


def install_plugin(args):
    if not os.getuid() == 0:
        logging.error("请以root权限运行")

    plugin_file = args.plugin
    plugin_dir = di["data_path"] / "plugins"
    if not plugin_dir.exists():
        plugin_dir.mkdir()
    plugin_file.rename(plugin_dir / plugin_file.name)
    logging.info(f"插件{plugin_file.name}安装成功")
    sys.exit(0)


if __name__ == "__main__":
    main()
