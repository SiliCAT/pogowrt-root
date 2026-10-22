# PogoWrt 基础 rootfs 配方

该配方安装 `configs/packages/base.list` 和设备默认软件包，`packages.list` 当前不追加软件包，不选择 LuCI。

| 文件 | 用途 |
|---|---|
| `disabled-services.list` | 将 `dnsmasq`、`odhcpd` 传给 IB 官方的 `DISABLED_SERVICES`；保留包和配置，不开机启动服务 |
| `files/etc/config/network` | LAN 静态 IPv4 为 `172.16.16.1/24`，保留 `br-lan`/`eth0`；不配置默认网关和 DNS；关闭 br-lan 的 IPv6，不整机禁用 IPv6 |
| `files/etc/config/dhcp` | dnsmasq 不监听 DNS、不作为本机解析器；不配置 DHCP 地址池、DHCPv6 或 RA 接口；使用 `/tmp/odhcpd.leases` 路径 |
| `files/etc/config/firewall` | 默认及 lan 区域的入站、出站和转发均为 ACCEPT，启用 SYN flood 限制和 MSS 调整，不配置 NAT |
| `files/etc/uci-defaults/99-pogowrt-hostname` | 首次启动时将 hostname 设置为 `PogoWrt`，权限 `0755` |

`/24` 对应掩码 `255.255.255.0`。若实际网络采用其他前缀，应修改 `network`。后续需要网关和 DNS 时，也在该文件中配置。

hostname 脚本由 OpenWrt 在默认系统配置生成后执行。组装阶段保留脚本，不提前执行目标系统的 UCI；首次启动需要可写配置层。复用已有可写层时，旧配置和已删除脚本的记录可能继续生效。

在 Actions 中选择 `Assemble rootfs from ImageBuilder`，选择 `image=pogowrt`，填写 IB 来源运行编号和尝试次数。可使用包含所需基础包的既有 IB，无需因为这些配置文件重新编译内核或 LuCI。

产物为 `pogowrt-root-aligned.squashfs` 和官方 IB 生成后原样复制的 `pogowrt-rootfs.tar.gz`。前者只对导出副本补零到 4096 字节边界；后者可直接解压到目录、分区或 NFS 目录。外置 rootfs 的启动和根目录交接仍由配套启动流程负责。
