# pogowrt-root

为 PogoPlug V4 交叉编译包含完整 rootfs 的 OpenWrt initramfs-uImage，并导出独立 SquashFS 镜像和包含本次已编译软件包的 ImageBuilder。

本轮交付完整源码构建工作流、配置输入、已有 SD 启动入口和观测报告工具。提交 `370146e` 的 [Actions 运行 39735742145](https://github.com/SiliCAT/pogowrt-root/actions/runs/39735742145) 已取得完整编译和两份镜像导出的记录。本次新增的 ImageBuilder 交付尚待首次实际构建；没有实机启动记录。

## 构建输入和能力

三个业务输入是：

| 文件 | 用途 |
|---|---|
| `configs/openwrt.config` | 设备、BusyBox 定制和软件包选择 |
| `configs/kernel.config` | 内建 LIO 核心、块设备后端、iSCSI target |
| `files/sbin/sd-init` | 早期 SD 启动入口，权限为 0755 |

软件包选择包含 blkid、losetup、util-linux flock、loop、VFAT、F2FS、XFS、USB 存储、LVM 工具及 NFSv4 客户端。NFSv4 使用 `kmod-fs-nfs-v4` 和 `nfs-utils-v4`，依赖由 OpenWrt 配置系统展开。

`CONFIG_IB=y` 让官方构建流程生成 ImageBuilder，`CONFIG_IB_STANDALONE=y` 将本次已编译的软件包归档一起包含进去。这些选项不表示编译或收录所有 feeds 软件包。

NFSv4 本轮只作为镜像中的可用能力选入。已有 `sd-init` 保持审阅版本：只读挂载 LABEL=BOOT 的 MMC/FAT 分区，然后交接到 FAT 内的 `/boot/init`；实际运行路径为 `/boot/boot/init`。网络初始化、NFS 挂载、远程镜像的 loop 挂载和根目录交接留待后续修订配套启动脚本。

FAT 上的 `boot/init`、`boot/uEnv.txt` 尚未纳入本仓库。SD 卡制作、UBOOT/NAND 操作、LIO LUN 服务编排及实机验收属于后续工作。

## 固定版本

- OpenWrt 标签：`v25.12.0`。
- OpenWrt 提交：`4da53efc2fe744601e6189492dbd06b8930d72b8`。
- 目标：`kirkwood/generic`，设备：`cloudengines_pogoplugv4`，ARMv5TE。
- 主源码和 feeds 使用 OpenWrt 官方 GitHub 镜像。

| Feed | 固定提交 |
|---|---|
| packages | `506c37591d7cd9b3cfd812e69e708349268f9865` |
| luci | `27a9c0c94264063894d40420956696d19b175744` |
| routing | `662b57dff7d20634f2b8676400cf4299611cfe4b` |
| telephony | `2618106d5846a4a542fdf5809f0d3ed228ce439b` |
| video | `094bf58da6682f895255a35a84349a79dab4bf95` |

固定版本以 `.github/workflows/build.yml` 为准；更新版本时应同步记录变更并重新构建、观察。首版不使用历史工具链或构建目录缓存。

## 手动运行

工作流和输入文件推送到 GitHub 后使用以下入口；`workflow_dispatch` 的工作流定义需先存在于仓库默认分支。

1. 打开仓库的 **Actions** 页面。
2. 选择 **Build OpenWrt for PogoPlug V4**。
3. 点击 **Run workflow**，选择构建分支并启动。
4. 在运行页面查看日志和下载区。

工作流使用 `ubuntu-24.04` amd64 托管构建机，以普通用户执行 OpenWrt make。安装依赖时使用 sudo。构建顺序为固定源码和 feeds、导入输入、`make defconfig`、`make download -j2 V=s`、分阶段完成内核配置和固件编译、生成观测报告、导出、上传。

在 OpenWrt 源码根目录中，构建分为两次调用：

```sh
make -j2 -f Makefile -f "$PROJECT_DIR/scripts/kernel-olddefconfig.mk" \
  V=s pogowrt-kernel-olddefconfig
make -j2 V=s
```

`PROJECT_DIR` 指向本仓库的绝对路径；工作流中对应 `$GITHUB_WORKSPACE/project`。第一条命令同时加载官方 Makefile 和本仓库的附加 Makefile。附加目标先复用官方 `prepare_kernel_conf` 准备工具链及 quilt，再进入 Kirkwood 目标，执行官方 `.configured` 目标合并内核配置，最后单独调用内核的 `olddefconfig`。第二条命令继续官方完整构建。顶层 `make defconfig` 展开 OpenWrt 软件包配置，与内核的配置展开不同。

附加 Makefile 保存在本仓库，不修改官方构建代码。该调用方式依赖当前固定版本中的目标和变量，升级 OpenWrt 时需要重新核对。两次调用之间不更改配置、feeds 或源码；在合并输入不变时，官方流程会保留已补全的内核 `.config`。如果调整输入，应重新执行第一条命令。此流程用于补全启用 LIO 后出现的新选项，避免在 `TCM_FILEIO` 等处进入交互提问。

内核配置阶段的输出保存为 `evidence/kernel-olddefconfig.log`，两个阶段的输出和合计耗时保存在 `evidence/build.log`，共享原来的 300 分钟步骤上限。依赖条件不满足时，Kconfig 仍可能调整要求的功能，最终值由现有报告记录。

整个 job 上限为 360 分钟，完整编译步骤上限为 300 分钟。运行 39735742145 中，尚未启用 ImageBuilder 的构建步骤耗时约 55 分 10 秒，末尾磁盘剩余约 75 GB；新增 IB 打包的耗时和体积尚待记录。工作流只配置手动触发。

## 下载交付物

| Artifact | 内容 |
|---|---|
| `pogov4-images-<run_id>-<run_attempt>` | ZIP，包含 `openwrt/lio-uImage` 和 `openwrt/lio-root-aligned.squashfs` |
| `pogov4-evidence-<run_id>-<run_attempt>.tar.gz` | 直接下载的证据归档，内部目录为 `evidence/` |
| `pogov4-imagebuilder-<run_id>-<run_attempt>.tar.zst` | 直接下载的官方 ImageBuilder 归档，包含本次已编译的软件包 |

SquashFS 对构建原文件的副本补零到 4096 字节边界，构建原文件不改动。报告记录原长度、导出长度、原始前缀摘要和追加字节信息。

证据包含项目提交、源码和 feeds 版本、原始输入、配置快照、软件包 manifest、日志、资源记录以及 JSON 报告。tar 归档保留 `.config` 等隐藏文件和原始脚本权限。保留期限沿用仓库设置，下载入口和 artifact 摘要会出现在运行摘要中。

IB 由官方构建流程在 `bin/targets/kirkwood/generic/` 中生成。工作流原样复制归档，仅将外部文件名改为上表中的名称，归档内的顶层目录名保持原样。上传使用 `archive: false`，不会在 `.tar.zst` 外再套一层 ZIP；权限、隐藏文件和链接保留在官方归档中。`evidence/imagebuilder-report.json` 记录 IB 配置值、构建及导出文件的候选路径、大小、权限和 SHA-256；缺少信息时记录原因。

镜像和 IB 分别以各自导出操作完成为上传前提。IB 导出在完整编译完成后执行，即使镜像导出操作报错，仍会尝试导出 IB。证据收集、打包和上传在前面步骤报错后也尽量执行。运行取消、总时限耗尽或基础设施故障可能使收尾操作无法完成。首版使用 Actions artifacts 交付文件。

## 使用 ImageBuilder

下载 IB 后，在兼容的 Linux x86_64 环境中安装 GNU make、tar、zstd 及 IB 所需的宿主依赖。用 `tar --zstd -xf` 解压下载的文件，进入归档中的 `openwrt-imagebuilder-…` 顶层目录，先执行 `make info` 查看设备配置。

如果需要保留本仓库选入的软件包，组装时应显式传入 `PACKAGES`。本地仓库收录某个软件包，并不表示每次组装都会自动安装它。下面的 `FILES` 需要替换为准备好的文件目录的绝对路径：

```sh
make image PROFILE=cloudengines_pogoplugv4 \
  PACKAGES="blkid flock losetup kmod-loop kmod-fs-vfat kmod-fs-f2fs kmod-fs-nfs-v4 kmod-fs-xfs kmod-usb-storage lvm2 nfs-utils-v4" \
  FILES="/绝对路径/自定义files目录"
```

例如，静态 IP 配置放在该目录下的 `etc/config/network`。需要保留本仓库的自定义文件时，可用仓库 `files/` 或证据包中的 `evidence/inputs/files/` 作为基础，再加入其他配置。官方 IB 不会自动收录源码构建时通过 `files/` 注入的全部自定义文件。

该 IB 携带本次定制的预编译内核和已编译软件包，适合重新组装外置 rootfs 和设备镜像；未编译的软件包不在离线仓库中。新内核模块需要来自匹配的内核构建。IB 不重新编译 Linux，也不重新生成内嵌 initramfs 的内核。因此它不能把更新后的 `sd-init` 或网络配置编入新的 `lio-uImage`，更新内嵌 rootfs 仍使用源码构建流程。

## 检查只生成报告

每项观测具有四个字段：

| 字段 | 内容 |
|---|---|
| `item` | 项目 |
| `requirement` | 要求值或描述 |
| `observed` | 实际观察值 |
| `unavailable_reason` | 无法取得信息的原因；无此情况时为 null |

报告不输出通过/失败或整体合格结论，也不根据观察值退出、拦截、跳过、重试或修复流程。信息缺失时记录原因，并继续采集其他独立项目。下载、复制、配置生成、编译、打包、上传等操作保留自身的执行结果；报告工具自身运行或写出故障也不隐藏。

运行状态和报告生成完成不等同于固件能力或实机启动已验收。NFS 工具、依赖和模块同样只记录配置值及文件观察；当前不会在 amd64 构建机执行 ARM 程序。

## 开发与本地验证

报告脚本位于 `scripts/`，仅依赖 Python 标准库；ELF 信息采集调用宿主 `readelf`。工作流使用 `project/` 放置本仓库、`work/openwrt/` 放置上游源码，`evidence/`、`artifacts/`、`delivery/` 分别存放证据、镜像副本和证据包。

报告行为和分阶段调用测试使用临时目录及模拟数据；分阶段调用测试还需要 GNU make。可执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

这些测试覆盖报告行为、文件处理和阶段调用顺序，不运行完整 OpenWrt 构建，也不代表真实固件已完成验收。后续自动化协作遵循 `AGENTS.md` 中的报告原则。
