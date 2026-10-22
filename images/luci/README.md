# LuCI rootfs 配方

- `packages.list`：在 `configs/packages/base.list` 和设备默认包之外安装的软件包，目前为 `luci`。
- `disabled-services.list`：本配方不开机启动的服务，目前为空，沿用软件包默认启动设置。
- `files/`：注入外置 rootfs 的文件目录，路径对应目标根目录。例如 `files/etc/config/network` 对应 `/etc/config/network`。
- `.gitkeep` 只用于保存空目录，由构建助手排除；其他隐藏文件、脚本权限和符号链接会保留。

源码阶段的 `configs/ib-extra.config` 负责预编译额外软件包。目前使用 `CONFIG_PACKAGE_luci=m`，让 standalone IB 携带 LuCI 及其依赖。这里选择安装包，不能编译 IB 中缺少的包。

在 Actions 中手动运行 `Assemble rootfs from ImageBuilder`，选择 `image=luci`，填写提供该 IB 的源码构建运行编号及尝试次数。输出为 `luci-root-aligned.squashfs` 和 `luci-rootfs.tar.gz`；内嵌 initramfs 的 `lio-uImage` 仍由源码工作流生成。

本配方不自动继承 `images/pogowrt/` 的网络配置和服务设置。
