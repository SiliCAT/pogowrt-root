# pogowrt-root

为 PogoPlug V4 编译基础镜像和自包含 ImageBuilder，再使用指定的 ImageBuilder 组装包含 LuCI 的外置 SquashFS rootfs。

提交 `370146e` 的 [Actions 运行 39735742145](https://github.com/SiliCAT/pogowrt-root/actions/runs/39735742145) 已取得完整编译和两份基础镜像导出的记录。后续提交增加了 IB 导出；本次将基础包清单共用，并增加 LuCI 的预编译选择和 IB 组装工作流。这些新增流程尚待实际构建记录，没有实机启动记录。

## 仓库结构和两个阶段

```text
.github/workflows/
  build.yml                  源码编译：基础镜像、IB、证据
  build-rootfs.yml           使用指定 IB：LuCI rootfs、证据
configs/
  openwrt.config             设备、BusyBox 和 IB 构建选项
  kernel.config              内核定制
  ib-extra.config            为 IB 额外编译的软件包，通常选为 m
  packages/base.list         两个阶段共用的基础软件包名称
images/luci/
  packages.list              LuCI rootfs 额外安装的软件包
  files/                     LuCI rootfs 注入的配置文件
files/sbin/sd-init           源码构建使用的早期启动入口
scripts/                    配置合成、IB 调用、镜像导出及观察报告
tests/                      使用临时数据验证辅助工具
```

`build.yml` 从固定源码、feeds 和配置生成基础镜像及 IB。`build-rootfs.yml` 根据用户指定的源码构建运行编号和尝试次数下载 IB，用当前选定分支中的组装配方生成外置 rootfs。两个工作流均只手动触发；不自动选择“最新 IB”，也不自动连锁启动。

## 构建输入和能力

源码构建的输入是：

| 文件 | 用途 |
|---|---|
| `configs/openwrt.config` | 设备、BusyBox 定制和生成 IB 的选项 |
| `configs/packages/base.list` | 基础软件包，每行一个名称；源码构建选为 `y`，IB 组装时也安装 |
| `configs/ib-extra.config` | 为 IB 额外编译的软件包，目前为 `CONFIG_PACKAGE_luci=m` |
| `configs/kernel.config` | 内建 LIO 核心、块设备后端、iSCSI target |
| `files/sbin/sd-init` | 早期 SD 启动入口，权限为 0755 |

软件包选择包含 blkid、losetup、util-linux flock、loop、VFAT、F2FS、XFS、USB 存储、LVM 工具及 NFSv4 客户端。NFSv4 使用 `kmod-fs-nfs-v4` 和 `nfs-utils-v4`，依赖由 OpenWrt 配置系统展开。

`CONFIG_IB=y` 让官方构建流程生成 ImageBuilder，`CONFIG_IB_STANDALONE=y` 将本次已编译的软件包归档一起包含进去。这些选项不表示编译或收录所有 feeds 软件包。

工作流调用 `scripts/prepare-build-config.py`，依次合并 `openwrt.config`、由基础包清单生成的 `CONFIG_PACKAGE_包名=y`、`ib-extra.config`，写入上游源码目录的 `.config`；随后执行官方 `make defconfig` 展开依赖。合并前的三个输入保持原样，合并结果保存为 `evidence/openwrt.config.input`。同一个配置项应只在一个输入中定义。

对普通软件包，`y` 表示编译并安装进基础镜像，`m` 表示编译成包供后续使用。LuCI 在额外片段中选为 `m`，由完整构建编译并纳入 standalone IB；基础镜像不因该项选择而安装 LuCI。依赖可能被其他选择提升为 `y`，最终值由报告记录。`ib-extra.config` 不放设备、内核或 BusyBox 选项。

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

这是源码编译阶段。需要生成包含 LuCI 软件包的新 IB 时，应运行包含本次配置调整的提交；之前没有选择 LuCI 的 IB 不具备这套离线组装所需的软件包。修改仓库不会改变已经启动的运行使用的提交。

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

源码工作流完成后，记下该次运行页面 URL 中的运行编号，以及对应的尝试次数。运行编号不是提交号，也不是 Artifact ID；首次执行的尝试次数为 `1`。

在 **Actions → Assemble LuCI rootfs from ImageBuilder → Run workflow** 中选择组装配方所在分支，填写：

| 输入 | 含义 |
|---|---|
| `source_run_id` | 已上传所需 IB 的源码构建运行编号 |
| `source_run_attempt` | 该次构建的尝试次数，默认为 `1` |

新工作流使用自动提供的 `github.token`，授予 `contents: read` 和 `actions: read`，从同一仓库的指定运行下载 `pogov4-imagebuilder-<run_id>-<run_attempt>.tar.zst`。下载动作固定为支持原始文件 artifact 的 `actions/download-artifact` v8 提交，无需另外配置个人令牌。来源 artifact 必须仍在 GitHub 保留期内。

解压后，`scripts/build-rootfs.py` 合并 `configs/packages/base.list` 和 `images/luci/packages.list`，调用官方 IB 的 `make image`。清单允许空行、`#` 注释和每行一个包名；重复名称只安装一次。包依赖由 IB 的包管理器计算。

`images/luci/packages.list` 当前选择 `luci` 集合包，由它带入界面、主题、uhttpd、RPC 支持等依赖。仅在此列表新增一个包，不会让旧 IB 自动拥有该包；需要额外预编译时，同步调整 `configs/ib-extra.config` 并重新生成 IB。

组装产物为：

| Artifact | 内容 |
|---|---|
| `pogov4-luci-rootfs-<run_id>-<run_attempt>` | ZIP，包含 `luci/luci-root-aligned.squashfs` |
| `pogov4-luci-evidence-<run_id>-<run_attempt>.tar.gz` | IB 来源运行及提交、IB 摘要、组装参数、输入配置、安装包 manifest、日志和观察报告 |

基础镜像和 LuCI rootfs 共用 `scripts/export-rootfs.py`，只对副本补零到 4096 字节边界。观察报告记录原始前缀摘要和追加字节，不根据观察结果控制上传。LuCI 报告还记录界面入口、uhttpd/rpcd 配置、启动链接及可执行文件信息，不在 amd64 构建机运行 ARM 服务。

`images/luci/files/` 是该 rootfs 的注入目录。例如静态 IP 配置放在 `images/luci/files/etc/config/network`；目前没有预设新的网络配置，沿用包内默认值。构建助手将目录复制为 `work/luci-files/`，保留权限、隐藏文件和符号链接，并排除用于跟踪空目录的 `.gitkeep`。注入文件也保存在证据中。现有 `files/sbin/sd-init` 保持用于源码构建的早期启动入口，不自动注入这个外置 rootfs。

若需要在自己的 Linux x86_64 环境使用 IB，安装 GNU make、tar、zstd 及 IB 所需的宿主依赖，用 `tar --zstd -xf` 解压，进入归档中的 `openwrt-imagebuilder-…` 顶层目录，先执行 `make info` 查看设备配置。

如果需要保留本仓库选入的软件包，组装时应显式传入 `PACKAGES`。本地仓库收录某个软件包，并不表示每次组装都会自动安装它。下面的 `FILES` 需要替换为准备好的文件目录的绝对路径：

```sh
make image PROFILE=cloudengines_pogoplugv4 \
  PACKAGES="blkid flock losetup kmod-loop kmod-fs-vfat kmod-fs-f2fs kmod-fs-nfs-v4 kmod-fs-xfs kmod-usb-storage lvm2 nfs-utils-v4 luci" \
  FILES="/绝对路径/自定义files目录"
```

手动调用时，`FILES` 下的 `etc/config/network` 同样可以注入静态 IP。官方 IB 不会自动收录源码构建时通过 `files/` 注入的全部自定义文件；应明确选择需要的文件目录。新工作流已经通过 `images/luci/files/` 管理它们。

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

辅助脚本位于 `scripts/`，仅依赖 Python 标准库；ELF 信息采集调用宿主 `readelf`，来源运行元数据由宿主 `gh api` 采集。API 信息无法取得时记录原因，仍采集其他项目。工作流使用 `project/` 放置本仓库，源码阶段使用 `work/openwrt/`，组装阶段使用 `work/imagebuilder/`；`evidence/`、`artifacts/`、`delivery/` 分别存放证据、镜像副本和证据包。

报告行为和分阶段调用测试使用临时目录及模拟数据；分阶段调用测试还需要 GNU make。可执行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

这些测试覆盖配置合成、共用包清单、IB 调用参数、注入文件权限和链接、导出补零、失败操作的退出结果、报告行为及阶段调用顺序。IB 调用测试使用临时 Makefile，不运行真实 IB 或完整 OpenWrt 构建，也不代表真实固件已完成验收。后续自动化协作遵循 `AGENTS.md` 中的报告原则。
