# LibreELEC Hades x86_64 Dolby Vision & HDR10+ Docker 镜像

基于 [LibreELEC-Hades](https://github.com/hadesdevls/LibreELEC-Hades)（1.0 RC8 定制增强版）构建的容器化 LibreELEC 用户态与宿主机内核/驱动镜像，专为 **飞牛 FnOS** 及 **Debian / Ubuntu** 等 x86_64 NAS 与 HTPC 宿主系统设计。无需重装宿主机，即可通过 Docker 容器实现 **GBM 无桌面独占显示直通 + 硬件解码 + ALSA 次世代源码直通 + 原生 HDMI 杜比视界（Dolby Vision）与 HDR10+ 输出**。

---

## 核心特性

- **原生 HDMI 杜比视界（TV-Led / Standard）**：完整支持 **Profile 5、Profile 7（FEL 双层完整增强层与 MEL）、Profile 8.1**，逐帧重构画面并注入动态 RPU 元数据；同时支持 **LLDV（低延迟杜比视界）** 与老款电视的 **HDMI 1.4b 杜比信令**。
- **原生 HDR10+ 与跨格式动态映射**：支持逐帧发送 HDR10+ 动态元数据，并支持 **Dolby Vision ↔ HDR10+ / HDR10** 互转映射（兼容投影仪与仅支持单一 HDR 格式的显示设备）。
- **蓝光原盘完整体验**：内置开箱即用的 **BD-J（Blu-ray Java）蓝光菜单服务**（无需额外配置 Java 环境）以及 **3D 蓝光（H.264 MVC）帧封装输出**。
- **广泛的硬件兼容性**：支持 Intel 核显（9 代酷睿 / UHD 6xx 及以上，包括 N100 / Core Ultra）、AMD 核显与独显（RX 400/500、Vega、RX 5000–9000 及 Ryzen 集显）。

---

## 镜像标签（Tags）说明

| 标签 | 说明 |
| :--- | :--- |
| `aguan/libreelec-hades-dv:latest` | LibreELEC 13 用户态镜像（Hades 1.0 RC8 定制增强版，内置 Intel / AMD 显卡驱动自动识别与 BD-J 蓝光菜单支持） |
| `aguan/libreelec-hades-dv:hades-1.0-rc8-8ed4131` | 同 `latest`（固定版本归档标签） |
| `aguan/libreelec-hades-dv:kernel` | **宿主机杜比视界驱动/内核一键三模切换工具**（支持 **飞牛原生内核无损注入** / **`7.3.1-dv` 独立完整内核** / **纯净原厂内核** 一键切换） |
| `aguan/libreelec-hades-dv:kernel-7.3.1-dv` | 同 `kernel`（固定内核版本归档标签） |

---

## 第一步：宿主机杜比视界内核与驱动配置（支持三大模式自由切换）

由于 Docker 容器与宿主机共享内核及 DRM 显示驱动，开启 **HDMI 杜比视界隧道直通（DV Bridge）与次时代音频源码透传**前，请先在宿主机拉取内核管理工具：

```bash
docker pull aguan/libreelec-hades-dv:kernel
```

根据你的宿主系统与需求，在以下**三种模式**之间随时一键切换（切换后执行 `reboot` 重启宿主机生效）：

### 【模式 1】飞牛 FnOS 原生内核无损注入模式（飞牛系统默认推荐）

在飞牛 FnOS 宿主机上直接运行默认命令（或显式添加 `--fnos-dv`）：

```bash
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel
# 或显式指定（从 7.3.1-dv 切回飞牛原生内核时同样适用）：
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --fnos-dv
```

- **不替换飞牛官方内核**：自动识别宿主机当前运行的飞牛内核版本（`uname -r`），优先匹配镜像内置驱动包或宿主机本地缓存（`/var/cache/kodi-dv/`），若为其他已适配内核版本则自动从 GitHub Releases（`fnos-dv-modules`）按需下载并经 SHA256 与 `vermagic` 校验后，向 `/lib/modules/<当前内核>/updates/dv/` 无损注入打好杜比视界补丁的 `i915`（Intel）与 `amdgpu`（AMD）显卡驱动模块。
- **100% 保留飞牛全部原生特性**：飞牛专属 VFS 文件权限（`trim_acl`）、内核级回收站（`trim_trashbin`）、ZFS 存储池、KVM/VFIO 虚拟机直通、网卡与主板温控传感器均不受任何影响。
- **按需下载与代理 / 离线支持**：
  ```bash
  # 若飞牛系统版本较新、需要从 GitHub 按需下载对应驱动包，且国内网络直连较慢，可传入代理或加速前缀：
  docker run --rm --privileged -v /:/host -e HTTPS_PROXY=http://代理IP:端口 aguan/libreelec-hades-dv:kernel
  docker run --rm --privileged -v /:/host -e FNOS_GH_MIRROR=https://你的GitHub加速前缀 aguan/libreelec-hades-dv:kernel

  # 常见进阶参数：
  #   --kver <版本>     手动指定目标飞牛内核（默认自动按 uname -r 识别）
  #   --refresh         忽略 /var/cache/kodi-dv 本地缓存重新拉取
  #   --no-download     纯离线模式（仅使用镜像内置或 /var/cache/kodi-dv、/out 下离线包）
  #   --fallback-full   当前飞牛内核暂无无损包时，自动改用模式 2（7.3.1-dv 完整内核）
  ```
- *(注：若在非飞牛的普通 Debian / Ubuntu 系统上执行上述默认命令，工具会自动安装下方的 `7.3.1-dv` 完整内核；飞牛系统若当前内核暂未发布预编译驱动包，会给出明确提示并引导使用 `--safe-boot` / `--full-kernel`。)*

### 【模式 2】独立 `7.3.1-dv` 完整内核模式（Hades 完整特性内核 / Debian & Ubuntu 默认）

如需体验基于 Linux `7.3.1` 的完整 Hades 内核特性（含完整 HDR10+ 动态包、3D MVC 帧封装及全系列新显卡支持），可使用 `--full-kernel`（或 `--7.3.1-dv`）：

```bash
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --full-kernel
# 或使用版本别名：
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --7.3.1-dv
```

- **安全保留原系统内核**：安装并默认引导 `linux-image-7.3.1-dv`（已集成 KVM/VFIO、Bcache、主板传感器 `nct6775`/`it87`、万兆网卡及 HBA 阵列卡驱动），原系统内核保留在 `/boot` 中不删除。
- **安全试引导模式（`--safe-boot`，推荐远程/无键盘 NAS 首次使用）**：仅将**下一次重启（单次）**设为 `7.3.1-dv`，若新内核不兼容，强制重启一次机器即自动回退原系统内核：
  ```bash
  docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --safe-boot
  ```

### 【模式 3】纯净原系统内核模式（一键卸载还原原厂状态）

无论当前处于模式 1 还是模式 2，随时执行以下命令即可移除所有杜比视界注入模块与独立定制内核，**100% 恢复原厂状态**：

```bash
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --restore
```

### 其他实用查询与辅助命令

```bash
# 查看宿主机当前所处模式、内核版本与驱动注入状态
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --status

# 保留定制内核不卸载，仅将 GRUB 默认启动项切回原系统内核
docker run --rm --privileged -v /:/host aguan/libreelec-hades-dv:kernel --switch-orig

# 仅提取 .deb 安装包与飞牛驱动模块压缩包到当前目录
docker run --rm -v $(pwd):/out aguan/libreelec-hades-dv:kernel --extract
```

---

## 第二步：启动 Kodi Hades-DV 容器（Docker Compose）

在宿主机新建目录（例如 `/opt/kodi-hades`），创建 `docker-compose.yml`：

```yaml
services:
  kodi-hades-dv:
    image: aguan/libreelec-hades-dv:latest
    container_name: kodi-hades-dv
    restart: unless-stopped
    privileged: true
    network_mode: host
    ipc: host
    environment:
      # 默认 auto 自动识别 Intel (iHD) 与 AMD (radeonsi) 显卡
      # 如为 Intel 7 代及更早核显，可手动改为 i965
      - LIBVA_DRIVER_NAME=auto
    volumes:
      # 硬件直通（显卡 DRM、声卡 ALSA、输入设备与热插拔监听）
      - /dev:/dev
      - /run/udev:/run/udev:ro
      - /sys:/sys:ro
      # 持久化保存 Kodi 配置、插件、字幕与海报墙数据库
      - ./kodi_storage:/storage
      # 按需挂载宿主机本地影视目录（只读保护，0 损耗原生读取）
      - /mnt:/var/media/mnt:ro
      - /media:/var/media/media:ro
```

启动容器：

```bash
docker compose up -d
```

> **提示**：若宿主机安装了图形桌面环境（GDM / LightDM / SDDM），需先关闭桌面管理器以释放 DRM 显卡独占锁：
> ```bash
> systemctl disable --now gdm3 lightdm sddm
> systemctl set-default multi-user.target
> ```

---

## 常用维护与验证命令

```bash
# 查看 Kodi 实时运行日志
tail -f ./kodi_storage/.kodi/temp/kodi.log

# 验证杜比视界内核通道识别状态
grep -iE "Dolby Vision|DVBridge|dv_property" ./kodi_storage/.kodi/temp/kodi.log

# 拉取新版镜像并重启容器（保留全部配置与媒体库）
docker compose pull && docker compose up -d

# 停止容器（立即释放电视 HDMI 与声卡独占）
docker compose down
```

---

## 致谢与声明

- 上游内核与媒体中心杜比视界 / HDR10+ 实现基于 [hadesdevls/LibreELEC-Hades](https://github.com/hadesdevls/LibreELEC-Hades)。
- 本镜像为非官方社区打包构建，与 Team LibreELEC、Team Kodi / XBMC Foundation、Dolby Laboratories 及 HDR10+ Technologies 无关联。
