## 钻石铲安装方法

钻石铲目前仅支持Debian系列系统的打包, 请参阅[安装方法](#Debian上的安装)

其他的操作系统请自行下载源码编译, 请参阅[源码使用](#源码使用)


##### Debian上的安装
在电脑版网页或移动版下侧的[Release](https://github.com/diamond-shovel/diamond-shovel/releases)页面中可以找到自动构建的`deb`包, 您只需要将其下载到本地, 在终端中运行以下命令即可安装:

```bash
dpkg -i diamond-shovel_${version}_community_edition.deb
```

在后续的使用中可以直接使用`diamond-shovel`命令调用钻石铲.

##### 源码使用

请使用以下命令将仓库clone到本地, 或通过[Release](https://github.com/diamond-shovel/diamond-shovel/releases)页面下载源码压缩包:

```bash
git clone https://github.com/diamond-shovel/diamond-shovel.git
```

并直接调用`wrapped_main.py`即可
