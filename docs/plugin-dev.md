# 钻石铲插件开发

目前我们仅支持Python语言插件的开发, 同时请确保您的插件使用Python 3.12所支持的语法.

同时我们假设您已经了解了Python的基本语法, 同时如何使用`tar`命令来制作以`tar.gz`结尾的压缩包.

## 要开始了呦

1. (可选) 请为你的插件创建一个隔离的环境, 在该教程下我们将使用`virtualenv`作为我们的样例环境

```shell
python3 -m venv .env
source .env/bin/activate
```

2. 安装diamond-shovel-api库, 作为钻石铲的基本开发库

```shell
pip install diamond-shovel-api
```

3. 创建一个`plugin.ini`文件, 用于描述你的插件的基本信息

```ini
[plugin]
name=插件名
version=版本号
description=插件描述
entry_point=插件入口(无.py后缀)
tags=插件标签, 以便于管理, 使用空格分割
os_dependencies=插件需要的系统软件包, 使用空格分割 (可选, 为空时请删除此条目)
package_dependencies=插件需要的Python软件包, 使用空格分割 (可选, 为空时请删除此条目). 软件包无需打包进插件包, 钻石铲将自动从pypi源获取
```

4. 编写入口文件, 作为插件的入口

```python
from diamond_shovel.plugins import PluginInitContext, inject

@inject
def enable(load_context: PluginInitContext):
    # 插件启用时的操作
    ...

@inject
def load(load_context: PluginInitContext):
    # 插件加载时的操作
    ...
```

其中你可以在`enable`和`load`函数中编写插件的启用和加载时的操作. 

4.1. `load`函数一般用于释放插件所必须的文件, 以及向钻石铲提交可能的运行信息
4.2. `enable`函数常用于启用插件的功能, 例如注册事件监听器, 注册任务处理器等

5. 从钻石铲那里接取可用的任务池, 并注册我们所能做的任务处理器

需要注意的是, 钻石铲为了加快任务的处理速度, 会将任务分发给多个处理器, 因此我们会用到Python的`asyncio`库来处理异步任务

```python
import asyncio
from diamond_shovel.function.task import TaskContext

async def handle_task(task):
    # 处理任务的代码
    ...
```

同时我们需要先获取可用的任务池, 并注册我们的任务处理器

上文中部分import行将变更为
```python
from diamond_shovel.plugins import PluginInitContext, events, inject
```

同时`enable`函数需要让钻石铲知道我们需要在任务池初始化时添加我们自己的任务处理器, 因此变更为

```python
@inject
def enable(load_context: PluginInitContext):
    events.register_event(load_context, events.WorkerPoolInitEvent, 任务池函数)
```

因此我们需要添加一个`任务池函数`来注册我们的任务处理器

```python
@inject
def 任务池函数(evt: events.WorkerPoolInitEvent, load_context: PluginInitContext):
    evt.pool.register_worker(load_context, handle_task, nice='优先级, 数字, 越低代表越优先')
```

6. 打包插件

```shell
cd 插件名/
tar -czvf ../插件名.tar.gz *
cd ../
```

7. Tada~★! 你的插件已经打包好了, 你可以将它上传到你的插件仓库, 或者直接将其复制到`${cwd}/plugins/`下安装插件使用

## 附注

这个教程只是一个精简版的插件开发过程, 如需必要请使用类似[PyCharm](https://www.jetbrains.com/pycharm/)这样的IDE来进行插件开发, 以加快插件开发的进程.

同时请自行寻找可用的Python库以帮助功能实现
