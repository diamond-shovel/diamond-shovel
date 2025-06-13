import json
import logging
import os
import pathlib
import subprocess
import threading
import traceback
from contextlib import contextmanager

from diamond_shovel.cli import historian
from diamond_shovel.utils.func import retry, async_helper

metadata_file = 'BinaryMetadata.json'


def print_from_process_stream(process: subprocess.Popen, log_prefix, output_container):
    """
    Print the output of a process stream with real-time output and collect the output.
    :param process: The process to print the output of
    :param log_prefix: Prefix for logging
    :param output_container: Dictionary to collect stdout and stderr
    """
    handler = historian.get_current_thread_handler()

    def read_stream(stream, key):
        with historian.duplicate_threaded_context_handler(handler):
            while True:
                try:
                    line = stream.readline()
                    if not line:
                        break
                    logging.info(f"{log_prefix}: {line.strip()}")
                    output_container[key].append(line)
                except UnicodeDecodeError:
                    logging.warning(f"{log_prefix}: Decode fail: {traceback.format_exc()}")
                except ValueError:
                    # Stream has been closed
                    break

    threads = []
    output_container['stdout'] = []
    output_container['stderr'] = []

    # 启动读取 stdout 的线程
    stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, 'stdout'))
    threads.append(stdout_thread)
    stdout_thread.start()

    # 检查 stderr 是否可用，若可用则启动读取 stderr 的线程
    if process.stderr:
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, 'stderr'))
        threads.append(stderr_thread)
        stderr_thread.start()

    # 等待所有线程结束
    for t in threads:
        t.join()


class BinaryManager:
    def __init__(self):
        self.binary_path_list = {}
        self.load_binary_info()

    def save_binary_info(self):
        """
        将整个类序列化到Binary_Manager.json文件的办法
        :return:
        """
        with open(metadata_file, 'w') as f:
            json.dump({k: {'out': str(v['out']), 'path': str(v['path'])} for k, v in self.binary_path_list.items()}, f)

    def load_binary_info(self):
        """
        从Binary_Manager.json文件中反序列化
        :return:
        """
        if not os.path.exists(metadata_file):
            return
        with open(metadata_file, 'r') as f:
            self.binary_path_list = {k: {'out': pathlib.Path(v['out']), 'path': pathlib.Path(v['path'])} for k, v in
                                     json.load(f).items()}

    def get_binary_list(self):
        """
        获取二进制文件列表
        :return:
        """
        return self.binary_path_list

    def check_binary(self, name):
        """
        判断二进制文件是否注册
        :param name:
        :return:
        """

        if name not in self.binary_path_list:
            return False

        if not self.binary_path_list[name]['path'].exists():
            self.binary_path_list.pop(name)
            return False

        return True

    def get_data_path_by_name(self, name):
        """
        通过name获取输出路径
        :param name:
        :return:
        """
        if not self.check_binary(name):
            raise ValueError(f"No binary registered with the name {name}")
        binary = self.binary_path_list[name]
        self.check_data_path(binary, name)
        return binary['out']

    def check_data_path(self, binary, name):
        if 'out' not in binary:
            binary['out'] = pathlib.Path('data') / name
            logging.debug(f"设置输出路径: {binary['out']}")
        if not binary['out'].exists():
            binary['out'].mkdir(parents=True)  # 如果没有目录就创建
            logging.debug(f"创建输出目录: {binary['out']}")

    def register_binary_path(self, name, path, out=None):
        """
        注册二进制文件name和路径
        :param name:
        :param path:
        :return:
        """
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(path)

        if not path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")

        if not out:
            out = pathlib.Path('data') / name

        if not isinstance(out, pathlib.Path):
            out = pathlib.Path(out)

        # 如果这个name已经注册过了，就不再注册
        if self.check_binary(name):
            logging.debug(f"Binary {name} 已经注册过了")
            return
        self.binary_path_list[name] = {'path': path, 'out': out}

        # 自动给这个文件添加权限
        self.init_binary_permission_with_name(name)
        self.save_binary_info()

    @contextmanager
    def open_file(self, name, file_name, mode='r'):
        """
        打开文件
        :param name:
        :param file_name:
        :return:
        """
        if not self.check_binary(name):
            raise ValueError(f"No binary registered with the name {name}")
        binary = self.binary_path_list[name]
        file_path: pathlib.Path = binary['out'] / file_name

        if not binary['out'].exists():
            binary['out'].mkdir(parents=True)
        if not file_path.exists():
            file_path.touch()

        file = open(file_path, mode)
        try:
            yield file
        finally:
            file.close()

    def init_binary_permission(self):
        """
        初始化二进制文件的权限
        :return:
        """
        for name, binary in self.binary_path_list.items():
            try:
                binary['path'].chmod(0o755)
                logging.debug(f"权限设置成功: {binary['path']}")
            except Exception:
                traceback.print_exc()
                logging.error(f"Failed to set permissions for {name} at {binary['path']}")

    def init_binary_permission_with_name(self, name):
        """
        初始化二进制文件的权限
        :return:
        """
        if not self.check_binary(name):
            raise ValueError(f"No binary registered with the name {name}")
        binary = self.binary_path_list[name]
        try:
            binary['path'].chmod(0o755)
            logging.debug(f"权限设置成功: {binary['path']}")
        except Exception as e:
            logging.warning(f"权限设置失败: {binary['path']}")

    async def execute_binary(self, *args, **kwargs):
        from diamond_shovel.function.task import current_task_context
        ctx = current_task_context()
        def executor():
            with historian.threaded_context_handler(ctx):
                return self.execute_binary_sync(*args, **kwargs)

        return await async_helper.call_sync(executor)

    @retry(max_retries=3, delay=1)
    def execute_binary_sync(self, name, cmd_args, timeout, error_manage=True, separate_output=True, text=True):
        """
        执行二进制文件
        :param error_manage: 是否开启错误管理
        :param name: 二进制文件的名字
        :param cmd_args: 命令行参数
        :param timeout: 子进程超时时间，默认为60秒
        :param separate_output: 是否分离输出
        :param text: 是否以文本形式输出
        :return:
        """
        if not self.check_binary(name):
            raise ValueError(f"No binary registered with the name {name}")
        binary = self.binary_path_list[name]

        full_cmd = [str(binary['path'])] + cmd_args
        logging.info(f"在 `{binary['out']}` 执行系统命令: `{' '.join(full_cmd)}`")
        process = subprocess.Popen(full_cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE if separate_output else subprocess.STDOUT, bufsize=1,
                                   text=text, cwd=str(binary['out']))

        # 收集输出
        output_container = {}
        print_thread = self.start_stdio_agent(full_cmd, output_container, process)

        try:
            # 等待子进程完成，设置超时时间
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            process.kill()
            process.wait()
            if error_manage:
                logging.error(f"子进程超时: {' '.join(full_cmd)}")
                raise e

        # 等待打印线程完成
        print_thread.join()

        stdout = ''.join(output_container.get('stdout', []))
        stderr = ''.join(output_container.get('stderr', [])) if separate_output else ''

        if process.returncode != 0:
            if error_manage:
                logging.error(stderr)
                raise subprocess.CalledProcessError(process.returncode, full_cmd, output=stdout, stderr=stderr)

        logging.info('-' * 20)
        logging.info(f"执行二进制文件成功: {name}")
        return stdout, stderr

    def start_stdio_agent(self, full_cmd, output_container, process):
        handler = historian.get_current_thread_handler()
        def print_wrapper(*args):
            with historian.duplicate_threaded_context_handler(handler):
                print_from_process_stream(*args)

        print_thread = threading.Thread(target=print_wrapper, args=(process, full_cmd[0], output_container))
        print_thread.start()
        return print_thread

    def clear_outs_folder(self):
        """
        清除所有outs文件夹的内容
        :return:
        """
        logging.warning("清除所有outs路径中的内容")
        for name, binary in self.binary_path_list.items():
            if os.path.exists(binary['out']):
                logging.warning(f"清除路径: {binary['out']}")
                if os.path.isdir(binary['out']):
                    try:
                        os.rmdir(binary['out'])
                        logging.info(f"清除目录成功: {binary['out']}")
                    except OSError as e:
                        logging.error(f"无法删除目录 {binary['out']}: {e}")
                else:
                    try:
                        os.remove(binary['out'])
                        logging.info(f"清除文件成功: {binary['out']}")
                    except OSError as e:
                        logging.error(f"无法删除文件 {binary['out']}: {e}")
