import logging
import os
import pathlib
import shutil

from . import config_generation


def perform_installation(root: pathlib.Path = pathlib.Path("/")):
    if os.getuid() != 0:
        raise PermissionError("请以root权限运行安装程序")

    logging.info("检查依赖...")
    if not os.path.exists("/usr/bin/git"):
        raise FileNotFoundError("请安装git")

    logging.info("检查是否重复安装...")
    if (root / "etc" / "diamond-shovel" / "diamond-shovel.ini").exists():
        logging.error("已经安装过了")
        return

    logging.info("创建用户...")
    install_user()

    logging.info("创建配置文件...")
    install_config(root)

    logging.info("创建数据文件夹...")
    install_data_folder(root)

    logging.info("创建运行文件夹...")
    install_runtime_folder(root)

    logging.info("创建日志文件夹...")
    install_log_folder(root)

    logging.info("安装完成")


def install_log_folder(root):
    log_folder = root / "var" / "log" / "diamond-shovel"
    log_folder.mkdir(parents=True, exist_ok=True)
    log_folder.chmod(0o644)
    shutil.chown(log_folder, "diamond-shovel", "diamond-shovel")


def install_runtime_folder(root):
    run_folder = root / "var" / "run" / "diamond-shovel"
    run_folder.mkdir(parents=True, exist_ok=True)
    run_folder.chmod(0o644)
    shutil.chown(run_folder, "diamond-shovel", "diamond-shovel")


def install_data_folder(root):
    data_folder = root / "var" / "lib" / "diamond-shovel"
    data_folder.mkdir(parents=True, exist_ok=True)
    data_folder.chmod(0o755)
    shutil.chown(data_folder, "diamond-shovel", "diamond-shovel")


def install_config(root):
    config_folder = root / "etc" / "diamond-shovel"
    config_folder.mkdir(parents=True, exist_ok=True)
    config_generation.generate_config(config_folder)


def perform_removal(root: pathlib.Path = pathlib.Path('/')):
    if os.getuid() != 0:
        raise PermissionError("请以root权限运行安装程序")

    logging.info("删除数据文件夹...")
    data_folder = root / "var" / "lib" / "diamond-shovel"
    data_folder.rmdir()

    logging.info("删除运行文件夹...")
    run_folder = root / "var" / "run" / "diamond-shovel"
    run_folder.rmdir()

    logging.info("删除日志文件夹...")
    log_folder = root / "var" / "log" / "diamond-shovel"
    log_folder.rmdir()

    logging.info("删除配置文件...")
    config_folder = root / "etc" / "diamond-shovel" / "diamond-shovel.ini"
    config_folder.unlink()

    logging.info("卸载完成")

def install_user():
    try:
        os.system("useradd -r -s /bin/false diamond-shovel")
        os.system("groupadd -r diamond-shovel")
        os.system("usermod -aG diamond-shovel diamond-shovel")
    except Exception as e:
        logging.error(f"创建用户失败: {e}")

def uninstall_user():
    try:
        os.system("userdel -r -s diamond-shovel")
        os.system("groupdel -r diamond-shovel")
    except Exception as e:
        logging.error(f"Failed: {e}")
