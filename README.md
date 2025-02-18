# Diamond Shovel

> 面向目标的自动化漏洞发现和渗透测试框架

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg?style=for-the-badge&logo=python)

## 简介

项目名来源: Minecraft同款名[Diamond Shovel](https://en.wikipedia.org/wiki/Diamond_shovel)

<details>
<summary>项目名原因</summary>

~~你能指望一大群理工人怎么起名=-=~~

嗯, 至少在中文语境下, 铲子是用来挖洞的, 安全漏洞简称洞, 就先叫`Shovel`了

至于`Diamond`的话, 我也不知道=-=

</details>

这个框架本身并不会做太多的事情, 而是起到了类似于免疫系统中<cite>[树突状细胞][1]</cite>的作用, 
将目标信息呈递给各个插件, 并允许插件在*Diamond Shovel*的*平台*上进行信息交换,
省去了安全研究人员在日常工作中大量的虐待`Ctrl` `C`和`V`键的工作, 
让他们更加专注于思考和脱发, 并通过在*Diamond Shovel*编写或使用插件来提高他们的效率.

## 使用方法

请注意, 正如上述简介所述, *Diamond Shovel*本身并不会做太多的事情, 您需要通过编写插件或者安装额外的插件来达到您的需要.

您可以在[这里](https://github.com/diamond-shovel/diamond-shovel-plugins)找到我们预先免费提供的插件, 但请注意社区版钻石铲并不能正确识别`.ore`结尾的插件包.

### 安装

参见[安装方法](docs/install.md)

### 钻石铲命令行调用办法

参见[命令行调用](docs/cmdline.md)

### 钻石铲插件开发

参见[插件开发](docs/plugin-dev.md)

## 贡献

如果您遇到了Bug, 或者是想为钻石铲做一些什么, 请参考[贡献指南](CONTRIBUTING.md)


## 开源许可

钻石铲社区版是一个开源项目, 由[LGPL-3.0](LICENSE)许可证保护.

[1]: https://en.wikipedia.org/wiki/Dendritic_cell 或 [树突状细胞](https://baike.baidu.com/item/%E6%A0%91%E7%AA%81%E7%8A%B6%E7%BB%86%E8%83%9E/1375145)
