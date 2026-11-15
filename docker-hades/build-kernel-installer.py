#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import os
import tarfile
import time


SCRIPT_TEMPLATE = r"""#!/bin/sh
set -e

KERNEL_VER="__KERNEL_VER__"
PKG_VER="__PKG_VER__"
DOCKER_REPO="__REPO__"
DEFAULT_GITHUB_REPO="__GITHUB_REPO__"
DEFAULT_FNOS_RELEASE_TAG="__FNOS_RELEASE_TAG__"
DEFAULT_FNOS_GH_MIRROR="__FNOS_GH_MIRROR__"

EXPLICIT_FNOS_KVER="${FNOS_KVER:-}"
NO_DOWNLOAD="${FNOS_NO_DOWNLOAD:-0}"
REFRESH_CACHE="${FNOS_REFRESH:-0}"
FALLBACK_FULL="${FNOS_FALLBACK_FULL:-0}"
FORCE_MODE=0
ACTION=""

# 统一归一化代理环境变量（BusyBox wget 仅识别小写 http_proxy/https_proxy，宿主机 curl/wget 同时兼容大小写）
[ -z "${https_proxy:-}" ] && [ -n "${HTTPS_PROXY:-}" ] && export https_proxy="$HTTPS_PROXY"
[ -z "${http_proxy:-}" ] && [ -n "${HTTP_PROXY:-}" ] && export http_proxy="$HTTP_PROXY"
[ -z "${all_proxy:-}" ] && [ -n "${ALL_PROXY:-}" ] && export all_proxy="$ALL_PROXY"
[ -z "${HTTPS_PROXY:-}" ] && [ -n "${https_proxy:-}" ] && export HTTPS_PROXY="$https_proxy"
[ -z "${HTTP_PROXY:-}" ] && [ -n "${http_proxy:-}" ] && export HTTP_PROXY="$http_proxy"
[ -z "${ALL_PROXY:-}" ] && [ -n "${all_proxy:-}" ] && export ALL_PROXY="$all_proxy"

echo "================================================================"
echo "  LibreELEC Dolby Vision 定制内核管理工具 ($KERNEL_VER / $PKG_VER)"
echo "  (飞牛原生内核多版本自适应注入 | $KERNEL_VER 独立内核 | 纯净原厂内核 一键切换)"
echo "================================================================"

show_usage() {
    echo "[使用方法 - 支持三大内核模式自由切换]"
    echo ""
    echo "  【模式 1】智能安装 / 切换为飞牛原生修改内核（飞牛 FnOS 默认推荐）："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel"
    echo "     (或显式指定: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --fnos-dv)"
    echo "     -> 自动识别宿主机当前飞牛内核版本 (uname -r)，优先匹配镜像内置/本地缓存，"
    echo "        若为其他已适配内核版本则自动从 GitHub Releases 按需下载并校验注入，100% 保留飞牛全部特性；"
    echo "     -> 非飞牛 Debian/Ubuntu 系统自动安装 $KERNEL_VER 完整内核。"
    echo ""
    echo "  【模式 2】手动安装 / 切换到独立 $KERNEL_VER 完整内核（飞牛与通用系统均可用）："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --full-kernel"
    echo "     (或使用别名: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --$KERNEL_VER)"
    echo "     -> 安装并默认引导独立的 linux-image-$KERNEL_VER 主线杜比视界内核（原内核安全保留）。"
    echo ""
    echo "  【模式 3】手动切换回纯净原系统内核（卸载注入模块与定制内核，100% 恢复原厂状态）："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --restore"
    echo "     (或使用别名: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --orig-kernel)"
    echo ""
    echo "  [其他辅助功能与飞牛多版本选项]"
    echo "  - 保留 $KERNEL_VER 内核文件，仅将 GRUB 启动项切回原系统内核："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --switch-orig"
    echo "  - 安全试引导模式（仅下次重启单次试运行 $KERNEL_VER，死机再重启自动回退原内核）："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --safe-boot"
    echo "  - 查看宿主机当前所处模式、内核版本与驱动状态："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --status"
    echo "  - 强制重新安装当前模式："
    echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --force"
    echo "  - 手动指定飞牛目标内核版本 / 刷新下载缓存 / 离线模式："
    echo "     --kver <内核版本>         指定目标飞牛内核（默认自动读取当前 uname -r）"
    echo "     --refresh                 忽略 /var/cache/kodi-dv 本地缓存并重新按需下载"
    echo "     --no-download             纯离线模式（仅使用镜像内置、/out 或宿主机缓存包）"
    echo "     --fallback-full           飞牛无匹配模块包时自动降级安装 $KERNEL_VER 完整内核"
    echo "     --modules-url <URL>       指定自定义驱动模块压缩包直链"
    echo "     (默认加速前缀: ${DEFAULT_FNOS_GH_MIRROR:-无}, 设 FNOS_GH_MIRROR=direct 可禁用; 其他变量: HTTPS_PROXY / FNOS_MODULES_BASE_URL / FNOS_GH_REPO)"
    echo "  - 仅提取 .deb 安装包与飞牛内置驱动模块到当前目录："
    echo "     docker run --rm -v \$(pwd):/out ${DOCKER_REPO}:kernel --extract"
}

set_action() {
    if [ -n "$ACTION" ] && [ "$ACTION" != "$1" ]; then
        echo "[错误] 参数冲突: 不能同时指定 $ACTION 与 $1"
        exit 1
    fi
    ACTION="$1"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --help|-h)
            show_usage
            exit 0
            ;;
        --extract)
            set_action "--extract"
            ;;
        --status)
            set_action "--status"
            ;;
        --restore|--orig-kernel|--rollback|--uninstall)
            set_action "--restore"
            ;;
        --switch-orig)
            set_action "--switch-orig"
            ;;
        --fnos-dv|--fnos-modules)
            set_action "$1"
            ;;
        --full-kernel|--safe-boot)
            set_action "$1"
            ;;
        --"$KERNEL_VER")
            set_action "$1"
            ;;
        install)
            set_action "install"
            ;;
        --force)
            FORCE_MODE=1
            ;;
        --kver=*|--fnos-kver=*)
            EXPLICIT_FNOS_KVER="${1#*=}"
            ;;
        --kver|--fnos-kver)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "[错误] 参数 $1 需要提供具体内核版本号"
                exit 1
            fi
            shift
            EXPLICIT_FNOS_KVER="$1"
            ;;
        --modules-url=*)
            FNOS_MODULES_URL="${1#*=}"
            export FNOS_MODULES_URL
            ;;
        --modules-url)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                echo "[错误] 参数 --modules-url 需要提供下载链接"
                exit 1
            fi
            shift
            FNOS_MODULES_URL="$1"
            export FNOS_MODULES_URL
            ;;
        --no-download|--offline)
            NO_DOWNLOAD=1
            ;;
        --refresh|--no-cache)
            REFRESH_CACHE=1
            ;;
        --fallback-full)
            FALLBACK_FULL=1
            ;;
        *)
            echo "[错误] 未知参数: $1"
            echo ""
            show_usage
            exit 1
            ;;
    esac
    shift
done

if [ -z "$ACTION" ]; then
    if [ "$FORCE_MODE" = "1" ]; then
        ACTION="--force"
    else
        ACTION="install"
    fi
fi

if [ "$ACTION" = "--extract" ]; then
    if [ ! -d /out ]; then
        echo "[错误] 提取模式需挂载输出目录，例如："
        echo "  docker run --rm -v \$(pwd):/out ${DOCKER_REPO}:kernel --extract"
        exit 1
    fi
    cp -vf /debs/*.deb /out/ 2>/dev/null || true
    cp -vf /fnos/*.tar.gz /out/ 2>/dev/null || true
    echo "[完成] 内核安装包与飞牛驱动包已提取至当前目录！"
    exit 0
fi

if [ ! -f /host/etc/debian_version ] || [ ! -x /host/usr/bin/dpkg ]; then
    show_usage
    exit 1
fi

is_dv_kernel() {
    case "$1" in
        *-dv|*-dv[!a-zA-Z0-9]*) return 0 ;;
        *) return 1 ;;
    esac
}

host_kernel_ready() {
    [ -n "$1" ] && [ -d "/host/lib/modules/$1" ] && [ -f "/host/boot/vmlinuz-$1" ]
}

fnos_dir_has_dv_mods() {
    [ -d "$1" ] && { [ -f "$1/i915.ko.xz" ] || [ -f "$1/i915.ko" ] || [ -f "$1/i915.ko.gz" ] || [ -f "$1/amdgpu.ko.xz" ] || [ -f "$1/amdgpu.ko" ] || [ -f "$1/amdgpu.ko.gz" ]; }
}

IS_FNOS=0
if [ -d /host/usr/trim ]; then
    IS_FNOS=1
fi

INSTALLED_VER=$(chroot /host dpkg-query -W -f='${Version}' "linux-image-$KERNEL_VER" 2>/dev/null || true)
RUNNING_KERNEL=$(uname -r)

# 探测宿主机上保留的非 DV 原系统内核列表
ORIG_KERNELS=$(chroot /host /bin/sh -s << 'EOF'
ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|^/boot/vmlinuz-||' | grep -vE '(-dv$|-dv[^a-zA-Z0-9])' | sort -V || true
EOF
)

SAVED_ORIG=$(chroot /host /bin/sh -s << 'EOF'
if [ -f /etc/kodi-dv-original-kernel ]; then
    CAND=$(cat /etc/kodi-dv-original-kernel 2>/dev/null | tr -d " \n\r\t")
    if [ -n "$CAND" ] && [ -f "/boot/vmlinuz-$CAND" ]; then
        echo "$CAND"
        exit 0
    fi
fi
ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|^/boot/vmlinuz-||' | grep -vE '(-dv$|-dv[^a-zA-Z0-9])' | sort -V | tail -n 1 || true
EOF
)

# 扫描宿主机所有已注入 DV 驱动的内核版本
INJECTED_FNOS_KVERS=""
for dv_dir in /host/lib/modules/*/updates/dv; do
    if fnos_dir_has_dv_mods "$dv_dir"; then
        kv=$(basename "$(dirname "$(dirname "$dv_dir")")")
        INJECTED_FNOS_KVERS="${INJECTED_FNOS_KVERS}${INJECTED_FNOS_KVERS:+ }${kv}"
    fi
done

# 按宿主机实际环境动态确定目标飞牛原生内核版本
TARGET_FNOS_KVER=""
FNOS_KVER_SOURCE=""
if [ "$IS_FNOS" = "1" ]; then
    if [ -n "$EXPLICIT_FNOS_KVER" ]; then
        case "$EXPLICIT_FNOS_KVER" in
            */*|*" "*|*"	"*)
                echo "[错误] 非法的内核版本号参数: $EXPLICIT_FNOS_KVER"
                exit 1
                ;;
        esac
        if ! host_kernel_ready "$EXPLICIT_FNOS_KVER"; then
            echo "[错误] 宿主机上未找到指定的内核版本: $EXPLICIT_FNOS_KVER"
            echo "       请确认 /lib/modules/$EXPLICIT_FNOS_KVER 与 /boot/vmlinuz-$EXPLICIT_FNOS_KVER 同时存在。"
            if [ -n "$ORIG_KERNELS" ]; then
                echo "       宿主机当前可用原系统内核："
                echo "$ORIG_KERNELS" | sed 's/^/         - /'
            fi
            exit 1
        fi
        TARGET_FNOS_KVER="$EXPLICIT_FNOS_KVER"
        FNOS_KVER_SOURCE="手动指定 (--kver / FNOS_KVER)"
    elif ! is_dv_kernel "$RUNNING_KERNEL" && host_kernel_ready "$RUNNING_KERNEL"; then
        TARGET_FNOS_KVER="$RUNNING_KERNEL"
        FNOS_KVER_SOURCE="宿主机当前运行内核 (uname -r)"
    else
        # 若宿主机当前正运行在 -dv 独立内核上，回溯飞牛原生内核
        if [ -f /host/etc/kodi-dv-original-kernel ]; then
            CAND=$(cat /host/etc/kodi-dv-original-kernel 2>/dev/null | tr -d " \n\r\t")
            if host_kernel_ready "$CAND"; then
                TARGET_FNOS_KVER="$CAND"
                FNOS_KVER_SOURCE="已保存基准内核 (/etc/kodi-dv-original-kernel)"
            fi
        fi
        if [ -z "$TARGET_FNOS_KVER" ]; then
            TRIM_CAND=$(chroot /host /bin/sh -c 'ls -1 /boot/vmlinuz-*-trim* 2>/dev/null | sed "s|^/boot/vmlinuz-||" | grep -vE "(-dv$|-dv[^a-zA-Z0-9])" | sort -V | tail -n 1' || true)
            if host_kernel_ready "$TRIM_CAND"; then
                TARGET_FNOS_KVER="$TRIM_CAND"
                FNOS_KVER_SOURCE="自动探测最新飞牛原生内核 (/boot/*-trim)"
            elif host_kernel_ready "$SAVED_ORIG"; then
                TARGET_FNOS_KVER="$SAVED_ORIG"
                FNOS_KVER_SOURCE="自动探测原系统内核 (/boot)"
            fi
        fi
    fi
fi

FNOS_MOD_INSTALLED=0
if [ -n "$TARGET_FNOS_KVER" ] && fnos_dir_has_dv_mods "/host/lib/modules/$TARGET_FNOS_KVER/updates/dv"; then
    FNOS_MOD_INSTALLED=1
fi

INSTALLED_VER=$(chroot /host dpkg-query -W -f='${Version}' "linux-image-$KERNEL_VER" 2>/dev/null || true)
RUNNING_KERNEL=$(uname -r)

# 探测宿主机上保留的非 DV 原系统内核列表
ORIG_KERNELS=$(chroot /host /bin/sh -s << 'EOF'
ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|^/boot/vmlinuz-||' | grep -vE '(-dv$|-dv[^a-zA-Z0-9])' | sort -V || true
EOF
)

SAVED_ORIG=$(chroot /host /bin/sh -s << 'EOF'
if [ -f /etc/kodi-dv-original-kernel ]; then
    CAND=$(cat /etc/kodi-dv-original-kernel 2>/dev/null | tr -d " \n\r")
    if [ -n "$CAND" ] && [ -f "/boot/vmlinuz-$CAND" ]; then
        echo "$CAND"
        exit 0
    fi
fi
ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|^/boot/vmlinuz-||' | grep -vE '(-dv$|-dv[^a-zA-Z0-9])' | sort -V | tail -n 1 || true
EOF
)

# 通用工具函数：安全下载、SHA256 校验与 vermagic ABI 校验
apply_gh_mirror() {
    _raw_url="$1"
    # 未设置 FNOS_GH_MIRROR 时默认使用内置加速前缀；显式传 "" / direct / none / off 则禁用前缀直连
    _mirror="${FNOS_GH_MIRROR-$DEFAULT_FNOS_GH_MIRROR}"
    case "$_mirror" in
        ""|direct|DIRECT|none|NONE|off|OFF|false|FALSE)
            _mirror=""
            ;;
    esac
    if [ -n "$_mirror" ]; then
        _mirror="${_mirror%/}"
        case "$_raw_url" in
            https://github.com/*|https://raw.githubusercontent.com/*)
                printf '%s/%s\n' "$_mirror" "$_raw_url"
                return 0
                ;;
        esac
    fi
    printf '%s\n' "$_raw_url"
}

download_file() {
    _url="$1"
    _dest="$2"
    _dest_dir=$(dirname "$_dest")
    mkdir -p "$_dest_dir"

    # 1. 优先使用宿主机 curl（具备完整 CA 证书链、HTTP CONNECT 与 SOCKS5 代理能力）
    if [ -x /host/usr/bin/curl ]; then
        _host_tmp="/tmp/.kodi-dv-dl-$$"
        rm -f "/host${_host_tmp}"
        if chroot /host /usr/bin/curl -fsSL --retry 2 --connect-timeout 15 --max-time 180 -o "$_host_tmp" "$_url" 2>/dev/null && [ -s "/host${_host_tmp}" ]; then
            mv -f "/host${_host_tmp}" "$_dest"
            return 0
        fi
        rm -f "/host${_host_tmp}"
    fi

    # 2. 次选宿主机 wget（同样使用宿主机 TLS 证书库）
    if [ -x /host/usr/bin/wget ]; then
        _host_tmp="/tmp/.kodi-dv-dl-$$"
        rm -f "/host${_host_tmp}"
        if chroot /host /usr/bin/wget -q --timeout=20 --tries=2 -O "$_host_tmp" "$_url" 2>/dev/null && [ -s "/host${_host_tmp}" ]; then
            mv -f "/host${_host_tmp}" "$_dest"
            return 0
        fi
        rm -f "/host${_host_tmp}"
    fi

    # 3. 兜底使用容器内置 BusyBox wget + ssl_client（直接使用 Docker 容器 DNS）
    rm -f "${_dest}.part"
    if wget -T 25 -q -O "${_dest}.part" "$_url" 2>/dev/null && [ -s "${_dest}.part" ]; then
        mv -f "${_dest}.part" "$_dest"
        return 0
    fi
    rm -f "${_dest}.part"
    return 1
}

download_with_mirror_fallback() {
    _raw_url="$1"
    _dest="$2"
    _primary=$(apply_gh_mirror "$_raw_url")
    echo "    -> 尝试下载: $_primary"
    if download_file "$_primary" "$_dest"; then
        return 0
    fi
    if [ "$_primary" != "$_raw_url" ]; then
        echo "    -> 镜像下载失败，回退直连: $_raw_url"
        if download_file "$_raw_url" "$_dest"; then
            return 0
        fi
    fi
    return 1
}

lookup_sha256_in_manifest() {
    _manifest="$1"
    _fname="$2"
    [ -s "$_manifest" ] || return 0
    awk -v fname="$_fname" '
        length($1) == 64 && $1 ~ /^[0-9a-fA-F]+$/ {
            f = $2
            sub(/^.*\//, "", f)
            sub(/^\*/, "", f)
            if (f == fname) { print tolower($1); exit }
        }
    ' "$_manifest"
}

verify_fnos_bundle() {
    _tar_path="$1"
    _target_kver="$2"
    _expected_sha="${3:-}"

    [ -s "$_tar_path" ] || return 1

    if [ -n "$_expected_sha" ]; then
        _actual_sha=$(sha256sum "$_tar_path" | awk '{print tolower($1)}')
        if [ "$_actual_sha" != "$_expected_sha" ]; then
            echo "[警告] 文件校验失败 (SHA256 不匹配): $_tar_path"
            echo "       期望: $_expected_sha"
            echo "       实际: $_actual_sha"
            return 1
        fi
        echo "    [OK] SHA256 完整性校验通过 (${_actual_sha})"
    fi

    _mod_list=$(tar -tzf "$_tar_path" 2>/dev/null || true)
    if [ -z "$_mod_list" ]; then
        echo "[警告] 文件不是有效的 tar.gz 压缩包: $_tar_path"
        return 1
    fi

    _probe_mod=""
    for _cand in i915.ko.xz ./i915.ko.xz i915.ko.gz ./i915.ko.gz i915.ko ./i915.ko amdgpu.ko.xz ./amdgpu.ko.xz amdgpu.ko.gz ./amdgpu.ko.gz amdgpu.ko ./amdgpu.ko; do
        if printf '%s\n' "$_mod_list" | grep -qx "$_cand"; then
            _probe_mod="$_cand"
            break
        fi
    done

    if [ -z "$_probe_mod" ]; then
        echo "[警告] 压缩包中未包含 i915.ko* 或 amdgpu.ko* 驱动模块: $_tar_path"
        return 1
    fi

    _vermagic_line=""
    case "$_probe_mod" in
        *.ko.xz)
            _vermagic_line=$(tar -xOzf "$_tar_path" "$_probe_mod" 2>/dev/null | xzcat 2>/dev/null | strings | grep '^vermagic=' | head -n 1 || true)
            ;;
        *.ko.gz)
            _vermagic_line=$(tar -xOzf "$_tar_path" "$_probe_mod" 2>/dev/null | zcat 2>/dev/null | strings | grep '^vermagic=' | head -n 1 || true)
            ;;
        *.ko)
            _vermagic_line=$(tar -xOzf "$_tar_path" "$_probe_mod" 2>/dev/null | strings | grep '^vermagic=' | head -n 1 || true)
            ;;
    esac

    _mod_kver=""
    if [ -n "$_vermagic_line" ]; then
        _mod_kver=$(printf '%s\n' "$_vermagic_line" | sed 's/^vermagic=//' | awk '{print $1}')
    fi

    if [ -n "$_mod_kver" ] && [ "$_mod_kver" != "$_target_kver" ]; then
        echo "[错误] 驱动包内部 ABI vermagic ($_mod_kver) 与宿主机目标内核 ($_target_kver) 不一致，已拒绝加载！"
        return 1
    fi
    if [ -n "$_mod_kver" ]; then
        echo "    [OK] 模块 vermagic ABI 校验匹配: $_mod_kver"
    fi
    return 0
}

RESOLVED_FNOS_TAR=""
RESOLVED_FNOS_SRC=""
HOST_CACHE_DIR="/host/var/cache/kodi-dv"

resolve_fnos_bundle() {
    _target_kver="$1"
    _bundle_name="fnos-${_target_kver}-dv-modules.tar.gz"
    RESOLVED_FNOS_TAR=""
    RESOLVED_FNOS_SRC=""

    # 1. 镜像内置驱动包
    if [ -f "/fnos/${_bundle_name}" ]; then
        echo ">>> [匹配成功] 在镜像内置仓库中找到适配 $_target_kver 的驱动包"
        if verify_fnos_bundle "/fnos/${_bundle_name}" "$_target_kver" ""; then
            RESOLVED_FNOS_TAR="/fnos/${_bundle_name}"
            RESOLVED_FNOS_SRC="镜像内置 (/fnos/${_bundle_name})"
            return 0
        fi
    fi

    # 2. 用户额外挂载目录 /out (手动离线包)
    if [ -f "/out/${_bundle_name}" ]; then
        echo ">>> [匹配成功] 在挂载目录 /out 中找到离线驱动包: $_bundle_name"
        if verify_fnos_bundle "/out/${_bundle_name}" "$_target_kver" ""; then
            RESOLVED_FNOS_TAR="/out/${_bundle_name}"
            RESOLVED_FNOS_SRC="外部挂载 (/out/${_bundle_name})"
            return 0
        fi
    fi

    # 3. 宿主机持久化缓存 /var/cache/kodi-dv/
    if [ "$REFRESH_CACHE" != "1" ] && [ -f "${HOST_CACHE_DIR}/${_bundle_name}" ]; then
        echo ">>> [匹配成功] 在宿主机本地缓存中找到驱动包: /var/cache/kodi-dv/${_bundle_name}"
        if verify_fnos_bundle "${HOST_CACHE_DIR}/${_bundle_name}" "$_target_kver" ""; then
            RESOLVED_FNOS_TAR="${HOST_CACHE_DIR}/${_bundle_name}"
            RESOLVED_FNOS_SRC="本地缓存 (/var/cache/kodi-dv/${_bundle_name})"
            return 0
        else
            echo ">>> [提示] 本地缓存损坏或版本不匹配，清理后尝试重新获取..."
            rm -f "${HOST_CACHE_DIR}/${_bundle_name}"
        fi
    fi

    if [ "$NO_DOWNLOAD" = "1" ]; then
        echo "[提示] 已启用纯离线模式 (--no-download)，且本地未找到 ${_bundle_name}。"
        return 1
    fi

    # 4. 远端按需下载
    echo ">>> [按需下载] 镜像内置仓库与本地缓存未收录 ${_target_kver}，正在联网查找预编译驱动包..."
    _work_dir="/tmp/fnos-dl-$$"
    mkdir -p "$_work_dir" "$HOST_CACHE_DIR"
    _dl_tar="${_work_dir}/${_bundle_name}"
    _manifest_file="${_work_dir}/fnos-modules-sha256.txt"
    _gh_repo="${FNOS_GH_REPO:-$DEFAULT_GITHUB_REPO}"
    _gh_tag="${FNOS_RELEASE_TAG:-$DEFAULT_FNOS_RELEASE_TAG}"

    _try_remote_source() {
        _cand_url="$1"
        _manifest_url="$2"
        _expected_sha=""

        if [ -n "$_manifest_url" ]; then
            rm -f "$_manifest_file"
            if download_with_mirror_fallback "$_manifest_url" "$_manifest_file" >/dev/null 2>&1 || [ -s "$_manifest_file" ]; then
                _expected_sha=$(lookup_sha256_in_manifest "$_manifest_file" "$_bundle_name")
            fi
        fi

        rm -f "$_dl_tar"
        if download_with_mirror_fallback "$_cand_url" "$_dl_tar"; then
            # 如果主清单未提供哈希，再尝试同名 .sha256 伴随文件
            if [ -z "$_expected_sha" ]; then
                rm -f "$_manifest_file"
                if download_with_mirror_fallback "${_cand_url}.sha256" "$_manifest_file" >/dev/null 2>&1; then
                    _expected_sha=$(lookup_sha256_in_manifest "$_manifest_file" "$_bundle_name")
                    if [ -z "$_expected_sha" ]; then
                        _expected_sha=$(awk 'length($1)==64 && $1 ~ /^[0-9a-fA-F]+$/ {print tolower($1); exit}' "$_manifest_file")
                    fi
                fi
            fi

            if verify_fnos_bundle "$_dl_tar" "$_target_kver" "$_expected_sha"; then
                mv -f "$_dl_tar" "${HOST_CACHE_DIR}/${_bundle_name}"
                chmod 0644 "${HOST_CACHE_DIR}/${_bundle_name}"
                RESOLVED_FNOS_TAR="${HOST_CACHE_DIR}/${_bundle_name}"
                RESOLVED_FNOS_SRC="远端按需下载 ($_cand_url)"
                return 0
            fi
        fi
        return 1
    }

    if [ -n "${FNOS_MODULES_URL:-}" ]; then
        if download_file "$FNOS_MODULES_URL" "$_dl_tar" && verify_fnos_bundle "$_dl_tar" "$_target_kver" ""; then
            mv -f "$_dl_tar" "${HOST_CACHE_DIR}/${_bundle_name}"
            chmod 0644 "${HOST_CACHE_DIR}/${_bundle_name}"
            RESOLVED_FNOS_TAR="${HOST_CACHE_DIR}/${_bundle_name}"
            RESOLVED_FNOS_SRC="自定义直链 ($FNOS_MODULES_URL)"
            rm -rf "$_work_dir"
            return 0
        fi
        rm -rf "$_work_dir"
        return 1
    fi

    if [ -n "${FNOS_MODULES_BASE_URL:-}" ]; then
        _base="${FNOS_MODULES_BASE_URL%/}"
        if _try_remote_source "${_base}/${_bundle_name}" "${_base}/fnos-modules-sha256.txt"; then
            rm -rf "$_work_dir"
            return 0
        fi
        rm -rf "$_work_dir"
        return 1
    fi

    _rel_base="https://github.com/${_gh_repo}/releases/download/${_gh_tag}"
    if _try_remote_source "${_rel_base}/${_bundle_name}" "${_rel_base}/fnos-modules-sha256.txt"; then
        rm -rf "$_work_dir"
        return 0
    fi

    _raw_base="https://raw.githubusercontent.com/${_gh_repo}/main/docker-hades"
    if _try_remote_source "${_raw_base}/${_bundle_name}" "${_raw_base}/fnos-modules-sha256.txt"; then
        rm -rf "$_work_dir"
        return 0
    fi

    rm -rf "$_work_dir"
    return 1
}

if [ "$IS_FNOS" = "1" ]; then
    echo ">>> 宿主机系统类型: 飞牛 FnOS (检测到 /usr/trim)"
    echo ">>> 飞牛目标原生内核: ${TARGET_FNOS_KVER:-未检测到} (${FNOS_KVER_SOURCE:-无可用原生内核})"
    if is_dv_kernel "$RUNNING_KERNEL"; then
        echo ">>> 当前激活模式: 【模式 2】独立杜比视界完整内核 ($RUNNING_KERNEL)"
    elif [ "$FNOS_MOD_INSTALLED" = "1" ]; then
        echo ">>> 当前激活模式: 【模式 1】飞牛原生内核 ($TARGET_FNOS_KVER) + 杜比视界无损驱动注入"
    else
        echo ">>> 当前激活模式: 【模式 3】纯净飞牛原厂内核 (${TARGET_FNOS_KVER:-$RUNNING_KERNEL}，未注入 DV 驱动)"
    fi
else
    echo ">>> 宿主机系统类型: 通用 Debian / Ubuntu"
fi
echo ">>> 宿主机当前运行内核 (uname -r): $RUNNING_KERNEL"
echo ">>> 当前飞牛内核 DV 注入状态: $([ "$FNOS_MOD_INSTALLED" = "1" ] && echo "已注入 (/lib/modules/$TARGET_FNOS_KVER/updates/dv)" || echo "未注入")"
if [ -n "$INJECTED_FNOS_KVERS" ] && [ "$INJECTED_FNOS_KVERS" != "$TARGET_FNOS_KVER" ]; then
    echo ">>> 宿主机其他已注入 DV 模块的内核: $INJECTED_FNOS_KVERS"
fi
echo ">>> 独立 $KERNEL_VER 内核包: ${INSTALLED_VER:-未安装} (镜像内最新: $PKG_VER)"
echo ">>> 宿主机原系统基准内核: ${SAVED_ORIG:-未检测到}"

# ==================== 查看状态 (--status) ====================
if [ "$ACTION" = "--status" ]; then
    echo ""
    echo ">>> 宿主机 /boot 下所有可用原系统内核："
    if [ -n "$ORIG_KERNELS" ]; then
        echo "$ORIG_KERNELS" | sed 's/^/    - /'
    else
        echo "    (无)"
    fi
    if [ "$IS_FNOS" = "1" ]; then
        echo ""
        echo ">>> 飞牛各版本内核杜比视界模块注入状态 (/lib/modules/*/updates/dv)："
        if [ -n "$INJECTED_FNOS_KVERS" ]; then
            for _kv in $INJECTED_FNOS_KVERS; do
                echo "    [内核 $_kv]:"
                ls -lh "/host/lib/modules/$_kv/updates/dv/" 2>/dev/null | sed 's/^/      /' || true
            done
        else
            echo "    (所有飞牛内核均未注入)"
        fi
        echo ""
        echo ">>> 镜像内置飞牛驱动包 (/fnos)："
        ls -lh /fnos/fnos-*-dv-modules.tar.gz 2>/dev/null | sed 's/^/    /' || echo "    (无)"
        echo ""
        echo ">>> 宿主机本地缓存飞牛驱动包 (/var/cache/kodi-dv)："
        ls -lh "${HOST_CACHE_DIR}"/fnos-*-dv-modules.tar.gz 2>/dev/null | sed 's/^/    /' || echo "    (无)"
    fi
    echo ""
    echo ">>> 宿主机已安装的独立 DV 内核软件包："
    chroot /host /bin/sh -s << 'EOF'
dpkg-query -W -f='    - ${Package} (${Version})\n' 'linux-image-*dv*' 'linux-headers-*dv*' 2>/dev/null | grep -E 'linux-(image|headers)' || echo '    (未安装)'
EOF
    echo ""
    echo ">>> 当前 GRUB 默认启动项配置："
    chroot /host /bin/sh -s << 'EOF'
grep -E '^(GRUB_DEFAULT|GRUB_TIMEOUT)=' /etc/default/grub 2>/dev/null | sed 's/^/    /' || true
EOF
    exit 0
fi

# ==================== 模式 3: 恢复纯净原系统内核 (--restore) ====================
if [ "$ACTION" = "--restore" ]; then
    echo ""
    echo ">>> 正在执行【模式 3：恢复纯净原系统内核（移除 DV 注入模块与独立定制内核）】..."
    if [ -z "$SAVED_ORIG" ]; then
        echo "[错误] 未在宿主机 /boot 下检测到任何原系统内核（非 -dv 内核）！"
        echo "       为防止卸载后系统无法启动，已安全中止操作。"
        exit 1
    fi

    chroot /host /bin/sh -s "$SAVED_ORIG" "$TARGET_FNOS_KVER" << 'EOF'
set -e
SAVED_ORIG="$1"
TARGET_FNOS_KVER="$2"
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

CLEANED_DV_KVER=""
for dv_dir in /lib/modules/*/updates/dv; do
    if [ -d "$dv_dir" ]; then
        kver=$(basename "$(dirname "$(dirname "$dv_dir")")")
        echo ">>> [飞牛模式] 正在移除内核 $kver 注入的杜比视界显卡驱动 ($dv_dir)..."
        rm -rf "$dv_dir"
        rmdir "/lib/modules/$kver/updates" 2>/dev/null || true
        if [ -d "/lib/modules/$kver" ]; then
            depmod -a "$kver"
            if [ -f "/boot/vmlinuz-$kver" ] && command -v update-initramfs >/dev/null 2>&1; then
                update-initramfs -u -k "$kver"
            fi
        fi
        CLEANED_DV_KVER="${CLEANED_DV_KVER}${CLEANED_DV_KVER:+ }$kver"
    fi
done

if [ -f /etc/depmod.d/kodi-dv.conf ]; then
    rm -f /etc/depmod.d/kodi-dv.conf
    if [ -z "$CLEANED_DV_KVER" ]; then
        _fix_kver="${TARGET_FNOS_KVER:-$SAVED_ORIG}"
        if [ -n "$_fix_kver" ] && [ -d "/lib/modules/$_fix_kver" ]; then
            depmod -a "$_fix_kver"
            if [ -f "/boot/vmlinuz-$_fix_kver" ] && command -v update-initramfs >/dev/null 2>&1; then
                update-initramfs -u -k "$_fix_kver"
            fi
        fi
    fi
fi
rm -rf /var/cache/kodi-dv

echo ">>> [1/3] 正在还原 GRUB 默认配置..."
if [ -f /etc/default/grub.kodi-dv.bak ]; then
    cp -f /etc/default/grub.kodi-dv.bak /etc/default/grub
    echo "    已从 /etc/default/grub.kodi-dv.bak 还原原系统 GRUB 配置"
else
    sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=0/' /etc/default/grub 2>/dev/null || true
fi
if command -v grub-editenv >/dev/null 2>&1 && [ -f /boot/grub/grubenv ]; then
    grub-editenv /boot/grub/grubenv unset next_entry 2>/dev/null || true
    grub-editenv /boot/grub/grubenv unset saved_entry 2>/dev/null || true
fi

echo ">>> [2/3] 正在卸载所有独立杜比视界定制内核软件包..."
DV_PKGS=$(dpkg-query -W -f='${Package} ' 'linux-image-*dv*' 'linux-headers-*dv*' 2>/dev/null || true)
if [ -n "$DV_PKGS" ]; then
    dpkg --purge --force-all $DV_PKGS || true
fi
rm -f /boot/vmlinuz-*dv* /boot/initrd.img-*dv* /boot/config-*dv* /boot/System.map-*dv*

echo ">>> [3/3] 正在重新生成 GRUB 引导菜单..."
if command -v update-grub >/dev/null 2>&1; then
    update-grub
fi
EOF

    echo ""
    echo "================================================================"
    echo "  [模式 3 切换完成] 杜比视界定制驱动与独立内核已全部移除！"
    echo "  宿主机已 100% 恢复为纯净原系统内核 ($SAVED_ORIG) 及原厂驱动。"
    echo "  请执行 'reboot' 重启宿主机以生效。"
    echo "================================================================"
    exit 0
fi

# ==================== 辅助模式: 保留定制内核，仅切回原系统内核启动 (--switch-orig) ====================
if [ "$ACTION" = "--switch-orig" ]; then
    echo ""
    echo ">>> 正在将 GRUB 默认启动项切换回原系统内核 ($SAVED_ORIG)..."
    if [ -z "$SAVED_ORIG" ]; then
        echo "[错误] 未在宿主机 /boot 下检测到原系统内核！"
        exit 1
    fi

    chroot /host /bin/sh -s "$SAVED_ORIG" << 'EOF'
set -e
SAVED_ORIG="$1"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SUBMENU_ID=$(grep 'gnulinux-advanced-' /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-advanced-[^']*\)'.*/\1/p")
ENTRY_ID=$(grep "gnulinux-${SAVED_ORIG}-advanced-" /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-${SAVED_ORIG}-advanced-[^']*\)'.*/\1/p")

if [ -n "$SUBMENU_ID" ] && [ -n "$ENTRY_ID" ]; then
    TARGET_ENTRY="${SUBMENU_ID}>${ENTRY_ID}"
    echo "    定位到原系统内核 GRUB 菜单项: $TARGET_ENTRY"
    sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"$TARGET_ENTRY\"|" /etc/default/grub
    update-grub
else
    sed -i 's|^GRUB_DEFAULT=.*|GRUB_DEFAULT=0|' /etc/default/grub
    update-grub
fi
EOF

    echo ""
    echo "================================================================"
    echo "  [切换成功] 已将默认启动项切回原系统内核 ($SAVED_ORIG)！"
    echo "  请执行 'reboot' 重启进入 $SAVED_ORIG 内核。"
    echo "================================================================"
    exit 0
fi

# ==================== 模式 1: 飞牛 FnOS 原生内核无损驱动注入模式 (飞牛默认，或 --fnos-dv / --fnos-modules) ====================
if [ "$ACTION" = "--fnos-dv" ] || [ "$ACTION" = "--fnos-modules" ]; then
    if [ "$IS_FNOS" != "1" ]; then
        echo "[错误] 当前宿主机未检测到飞牛 FnOS 环境 (/usr/trim)，无法使用飞牛模块注入模式。"
        echo "       请直接不带参数运行或使用 --full-kernel 安装完整 $KERNEL_VER 内核。"
        exit 1
    fi
    if [ -z "$TARGET_FNOS_KVER" ]; then
        echo "[错误] 已检测到飞牛系统，但在 /boot 与 /lib/modules 下未定位到可用的飞牛原生内核。"
        echo "       可通过 --kver <内核版本号> 手动指定，或使用 --full-kernel 安装独立 $KERNEL_VER 内核。"
        exit 1
    fi
fi

if [ "$IS_FNOS" = "1" ] && [ -z "$TARGET_FNOS_KVER" ] && [ "$ACTION" != "--full-kernel" ] && [ "$ACTION" != "--$KERNEL_VER" ] && [ "$ACTION" != "--safe-boot" ]; then
    if [ "$FALLBACK_FULL" = "1" ] && [ "$ACTION" = "install" ]; then
        echo ">>> 未定位到可用的飞牛原生内核，已启用 --fallback-full，转入【模式 2】..."
    else
        echo "[错误] 已检测到飞牛 FnOS 环境 (/usr/trim)，但未定位到 /boot/vmlinuz-* 与 /lib/modules/* 匹配的原生内核。"
        echo "       请确认宿主机 /boot 与 /lib/modules 完整（或用 --kver <版本> 指定），"
        echo "       如需改用独立 $KERNEL_VER 完整内核，请显式传入 --safe-boot / --full-kernel。"
        exit 1
    fi
fi

TRY_FNOS_MODE=0
if [ "$IS_FNOS" = "1" ] && [ -n "$TARGET_FNOS_KVER" ] && [ "$ACTION" != "--full-kernel" ] && [ "$ACTION" != "--$KERNEL_VER" ] && [ "$ACTION" != "--safe-boot" ]; then
    TRY_FNOS_MODE=1
fi

if [ "$TRY_FNOS_MODE" = "1" ]; then
    if resolve_fnos_bundle "$TARGET_FNOS_KVER"; then
        echo ""
        echo ">>> 正在执行【模式 1：飞牛 FnOS 原生内核 ($TARGET_FNOS_KVER) 无损杜比视界驱动注入】..."
        echo "    来源：$RESOLVED_FNOS_SRC"
        echo "    优势：100% 保留飞牛原生内核全部特性（VFS 权限/回收站/ZFS/虚拟机/网卡/风扇传感器），"
        echo "          向 /lib/modules/$TARGET_FNOS_KVER/updates/dv/ 注入杜比视界 i915 & amdgpu 驱动并配置 HDMI 源码直通声卡！"

        rm -rf "/host/lib/modules/$TARGET_FNOS_KVER/updates/dv"
        mkdir -p "/host/lib/modules/$TARGET_FNOS_KVER/updates/dv"
        tar -xzf "$RESOLVED_FNOS_TAR" -C "/host/lib/modules/$TARGET_FNOS_KVER/updates/dv"

        chroot /host /bin/sh -s "$TARGET_FNOS_KVER" << 'EOF'
set -e
TARGET_FNOS_KVER="$1"
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if grep -qi "AuthenticAMD" /proc/cpuinfo 2>/dev/null || grep -qi "0x1002" /sys/class/drm/*/device/vendor 2>/dev/null; then
    if [ ! -d /lib/firmware/amdgpu ] && [ ! -d /usr/lib/firmware/amdgpu ]; then
        echo ">>> 检测到 AMD 平台缺少 /lib/firmware/amdgpu，正在自动安装 firmware-amd-graphics..."
        apt-get update && apt-get install -y firmware-amd-graphics amd64-microcode || true
    fi
fi

echo ">>> [1/3] 正在更新飞牛原生内核模块依赖与 HDMI 源码直通音频配置 (depmod -a $TARGET_FNOS_KVER)..."
mkdir -p /etc/depmod.d /etc/modprobe.d
cat > /etc/depmod.d/kodi-dv.conf << 'DEPEOF'
override i915 * updates/dv
override amdgpu * updates/dv
DEPEOF
cat > /etc/modprobe.d/kodi-dv-audio.conf << 'AUOF'
# 强制 Intel 11~14 代平台使用标准 HDA 驱动 (snd_hda_intel)，以支持 HDMI 多声道与杜比全景声/DTS:X 源码直通
options snd-intel-dspcfg dsp_driver=1
blacklist snd_pcsp
AUOF
depmod -a "$TARGET_FNOS_KVER"

echo ">>> [2/3] 正在刷新飞牛原生内核 initramfs 镜像..."
if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -u -k "$TARGET_FNOS_KVER"
fi

echo ">>> [3/3] 正在将系统默认启动项指向飞牛原生内核 ($TARGET_FNOS_KVER)..."
DV_PKGS=$(dpkg-query -W -f='${Package} ' 'linux-image-*dv*' 'linux-headers-*dv*' 2>/dev/null || true)
if [ -n "$DV_PKGS" ]; then
    echo "    检测到已安装的独立 $DV_PKGS 内核，正在卸载以恢复飞牛原生内核为第一启动项..."
    dpkg --purge --force-all $DV_PKGS || true
    rm -f /boot/vmlinuz-*dv* /boot/initrd.img-*dv* /boot/config-*dv* /boot/System.map-*dv*
fi
if [ -f /etc/default/grub.kodi-dv.bak ]; then
    cp -f /etc/default/grub.kodi-dv.bak /etc/default/grub
else
    sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=0/' /etc/default/grub 2>/dev/null || true
fi
if command -v grub-editenv >/dev/null 2>&1 && [ -f /boot/grub/grubenv ]; then
    grub-editenv /boot/grub/grubenv unset next_entry 2>/dev/null || true
    grub-editenv /boot/grub/grubenv unset saved_entry 2>/dev/null || true
fi
if command -v update-grub >/dev/null 2>&1; then
    update-grub
fi

# 若宿主机 /boot 中存在比目标内核更高版本的原生内核，自动精准锁定 GRUB 到 $TARGET_FNOS_KVER
TOP_NON_DV=$(ls -1 /boot/vmlinuz-* 2>/dev/null | sed 's|^/boot/vmlinuz-||' | grep -vE '(-dv$|-dv[^a-zA-Z0-9])' | sort -V | tail -n 1 || true)
if [ -n "$TOP_NON_DV" ] && [ "$TOP_NON_DV" != "$TARGET_FNOS_KVER" ] && [ -f /boot/grub/grub.cfg ]; then
    SUBMENU_ID=$(grep 'gnulinux-advanced-' /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-advanced-[^']*\)'.*/\1/p")
    ENTRY_ID=$(grep "gnulinux-${TARGET_FNOS_KVER}-advanced-" /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-${TARGET_FNOS_KVER}-advanced-[^']*\)'.*/\1/p")
    if [ -n "$SUBMENU_ID" ] && [ -n "$ENTRY_ID" ]; then
        TARGET_ENTRY="${SUBMENU_ID}>${ENTRY_ID}"
        echo "    检测到更新版本内核 ($TOP_NON_DV)，已精准锁定默认引导项到目标飞牛内核: $TARGET_FNOS_KVER"
        sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"$TARGET_ENTRY\"|" /etc/default/grub
        update-grub
    fi
fi
EOF

        echo ""
        echo "================================================================"
        echo "  [模式 1 启用成功] 飞牛原生内核 ($TARGET_FNOS_KVER) 杜比视界无损驱动已就绪！"
        echo "  - 注入位置: /lib/modules/$TARGET_FNOS_KVER/updates/dv/ (i915 & amdgpu)"
        echo "  - 引导内核: $TARGET_FNOS_KVER (飞牛全部 NAS 特性 100% 完整保留)"
        echo "  - 其他模式切换命令："
        echo "    * 切换到独立 $KERNEL_VER 内核: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --full-kernel"
        echo "    * 恢复纯净飞牛原厂内核:     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --restore"
        echo "  - 请执行 'reboot' 重启宿主机生效！"
        echo "================================================================"
        exit 0
    else
        echo ""
        echo "================================================================"
        echo "  [未找到匹配的无损驱动包] 飞牛当前目标内核: $TARGET_FNOS_KVER"
        echo "================================================================"
        if [ "$FALLBACK_FULL" = "1" ] && [ "$ACTION" = "install" ]; then
            echo ">>> 已启用 --fallback-full，正在自动降级切换到【模式 2】安装独立 $KERNEL_VER 完整内核..."
        else
            echo "可能原因与解决方式："
            echo "  1. 当前飞牛内核版本 ($TARGET_FNOS_KVER) 尚未预编译发布对应的无损驱动包；"
            echo "  2. 或宿主机当前网络访问镜像/GitHub 受限（默认已启用 ${DEFAULT_FNOS_GH_MIRROR:-直连}，可改用代理、直连或更换加速前缀重试）："
            echo "     docker run --rm --privileged -v /:/host -e HTTPS_PROXY=http://代理IP:端口 ${DOCKER_REPO}:kernel"
            echo "     docker run --rm --privileged -v /:/host -e FNOS_GH_MIRROR=https://你的加速前缀 ${DOCKER_REPO}:kernel"
            echo "     docker run --rm --privileged -v /:/host -e FNOS_GH_MIRROR=direct ${DOCKER_REPO}:kernel"
            echo "  3. 若已手动下载 fnos-${TARGET_FNOS_KVER}-dv-modules.tar.gz，可放入宿主机："
            echo "     /var/cache/kodi-dv/fnos-${TARGET_FNOS_KVER}-dv-modules.tar.gz 后重新运行；"
            echo "  4. 若希望直接使用基于 Linux ${KERNEL_VER} 的独立完整内核（推荐配合安全试引导）："
            echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --safe-boot"
            echo "     docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --full-kernel"
            exit 1
        fi
    fi
fi

# ==================== 模式 2: 安装/切换到独立 $KERNEL_VER 完整内核 (通用 Debian/Ubuntu 默认，或飞牛 --full-kernel / --$KERNEL_VER) ====================
if [ "$ACTION" != "install" ] && [ "$ACTION" != "--force" ] && [ "$ACTION" != "--safe-boot" ] && [ "$ACTION" != "--full-kernel" ] && [ "$ACTION" != "--$KERNEL_VER" ]; then
    echo "[错误] 未知参数: $ACTION"
    echo ""
    show_usage
    exit 1
fi

if [ "$INSTALLED_VER" = "$PKG_VER" ] && [ "$ACTION" = "install" ] && [ "$FORCE_MODE" != "1" ]; then
    chroot /host /bin/sh -s << 'EOF'
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if ! grep -q "^GRUB_DEFAULT=0$" /etc/default/grub 2>/dev/null; then
    echo ">>> 正在将杜比视界定制内核固定为 GRUB 默认启动项 (GRUB_DEFAULT=0)..."
    sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=0|" /etc/default/grub
    if command -v grub-editenv >/dev/null 2>&1 && [ -f /boot/grub/grubenv ]; then
        grub-editenv /boot/grub/grubenv unset next_entry 2>/dev/null || true
        grub-editenv /boot/grub/grubenv unset saved_entry 2>/dev/null || true
    fi
    update-grub
fi
EOF
    echo ""
    echo "[已是最新] 宿主机已安装 linux-image-$KERNEL_VER ($PKG_VER) 且已设为默认启动项。"
    if [ "$RUNNING_KERNEL" != "$KERNEL_VER" ]; then
        echo ">>> 提示：你尚未重启进入 $KERNEL_VER 内核，请执行 'reboot' 重启宿主机。"
    fi
    echo ">>> 如需切换回飞牛原生修改内核，请加 '--fnos-dv' 参数运行。"
    echo ">>> 如需恢复纯净原系统内核 ($SAVED_ORIG)，请加 '--restore' 参数运行。"
    exit 0
fi

echo ""
echo ">>> 正在执行【模式 2：安装并切换到独立 $KERNEL_VER ($PKG_VER) 完整定制内核】..."
echo ">>> [1/5] 正在备份原系统内核记录与 GRUB 配置..."
chroot /host /bin/sh -s "$SAVED_ORIG" << 'EOF'
SAVED_ORIG="$1"
if [ ! -f /etc/default/grub.kodi-dv.bak ] && [ -f /etc/default/grub ]; then
    cp -f /etc/default/grub /etc/default/grub.kodi-dv.bak
    echo "    已备份原系统 GRUB 配置至 /etc/default/grub.kodi-dv.bak"
fi
if [ ! -f /etc/kodi-dv-original-kernel ] && [ -n "$SAVED_ORIG" ]; then
    echo "$SAVED_ORIG" > /etc/kodi-dv-original-kernel
    echo "    已记录原系统基准内核版本: $SAVED_ORIG (/etc/kodi-dv-original-kernel)"
fi
mkdir -p /etc/modprobe.d
cat > /etc/modprobe.d/kodi-dv-audio.conf << 'AUOF'
# 强制 Intel 11~14 代平台使用标准 HDA 驱动 (snd_hda_intel)，以支持 HDMI 多声道与杜比全景声/DTS:X 源码直通
options snd-intel-dspcfg dsp_driver=1
blacklist snd_pcsp
AUOF
EOF

echo ">>> [2/5] 正在检测宿主机 CPU/GPU 固件完整性..."
chroot /host /bin/sh -s << 'EOF'
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if grep -qi "AuthenticAMD" /proc/cpuinfo 2>/dev/null || grep -qi "0x1002" /sys/class/drm/*/device/vendor 2>/dev/null; then
    echo "    检测到 AMD 平台，正在检查 amdgpu 显卡与微码固件..."
    if [ ! -d /lib/firmware/amdgpu ] && [ ! -d /usr/lib/firmware/amdgpu ]; then
        echo "    [提示] 宿主机缺少 /lib/firmware/amdgpu，正在尝试通过 apt 自动安装 firmware-amd-graphics..."
        apt-get update && apt-get install -y firmware-amd-graphics amd64-microcode || echo "    [警告] 自动安装 firmware-amd-graphics 失败，请确保宿主机已安装 AMD 显卡固件"
    else
        echo "    [OK] 宿主机已具备 amdgpu 固件目录"
    fi
fi
EOF

echo ">>> [3/5] 正在向宿主机复制内核安装包..."
mkdir -p /host/tmp/kodi-dv-kernel
cp -f /debs/*.deb /host/tmp/kodi-dv-kernel/

echo ">>> [4/5] 正在宿主机内执行 dpkg 安装与 initramfs/GRUB 配置..."
chroot /host /bin/sh -s "$KERNEL_VER" "$ACTION" "$SAVED_ORIG" << 'EOF'
set -e
KERNEL_VER="$1"
ACTION="$2"
SAVED_ORIG="$3"
export DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

dpkg -i /tmp/kodi-dv-kernel/linux-image-*dv*.deb /tmp/kodi-dv-kernel/linux-headers-*dv*.deb
if command -v update-initramfs >/dev/null 2>&1; then
    update-initramfs -u -k "$KERNEL_VER"
fi

# 确保 GRUB 菜单显示至少 5 秒，以便用户在极端情况下可在开机界面手动选回原内核
if [ -f /etc/default/grub ]; then
    if grep -q '^GRUB_TIMEOUT=0' /etc/default/grub; then
        sed -i 's/^GRUB_TIMEOUT=0/GRUB_TIMEOUT=5/' /etc/default/grub
    fi
    sed -i 's/^GRUB_TIMEOUT_STYLE=hidden/GRUB_TIMEOUT_STYLE=menu/' /etc/default/grub 2>/dev/null || true
fi

if [ "$ACTION" = "--safe-boot" ] && [ -n "$SAVED_ORIG" ]; then
    echo ">>> 正在配置【安全试引导模式 (--safe-boot)】..."
    sed -i 's|^GRUB_DEFAULT=.*|GRUB_DEFAULT=saved|' /etc/default/grub
    update-grub
    SUBMENU_ID=$(grep 'gnulinux-advanced-' /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-advanced-[^']*\)'.*/\1/p")
    ENTRY_ID=$(grep "gnulinux-${SAVED_ORIG}-advanced-" /boot/grub/grub.cfg 2>/dev/null | head -n 1 | sed -n "s/.*'\(gnulinux-${SAVED_ORIG}-advanced-[^']*\)'.*/\1/p")
    if [ -n "$SUBMENU_ID" ] && [ -n "$ENTRY_ID" ] && command -v grub-set-default >/dev/null 2>&1 && command -v grub-reboot >/dev/null 2>&1; then
        grub-set-default "${SUBMENU_ID}>${ENTRY_ID}"
        grub-reboot 0
        echo "    已将永久默认内核保底设为原内核 ($SAVED_ORIG)，仅下一次重启试引导 $KERNEL_VER！"
    else
        sed -i 's|^GRUB_DEFAULT=.*|GRUB_DEFAULT=0|' /etc/default/grub
        update-grub
    fi
else
    sed -i 's|^GRUB_DEFAULT=.*|GRUB_DEFAULT=0|' /etc/default/grub 2>/dev/null || true
    if command -v grub-editenv >/dev/null 2>&1 && [ -f /boot/grub/grubenv ]; then
        grub-editenv /boot/grub/grubenv unset next_entry 2>/dev/null || true
        grub-editenv /boot/grub/grubenv unset saved_entry 2>/dev/null || true
    fi
    if command -v update-grub >/dev/null 2>&1; then
        update-grub
    fi
fi
EOF

echo ">>> [5/5] 正在清理临时文件..."
rm -rf /host/tmp/kodi-dv-kernel

echo ""
echo "================================================================"
echo "  [模式 2 安装成功] 独立定制内核 linux-image-$KERNEL_VER ($PKG_VER) 已就绪！"
if [ "$ACTION" = "--safe-boot" ]; then
    echo "  当前为【安全试引导模式】："
    echo "  1. 请执行 'reboot' 重启测试新内核 ($KERNEL_VER)；"
    echo "  2. 若新内核无法开机，再次强制重启机器即可【自动回退】至原内核 ($SAVED_ORIG)；"
    echo "  3. 若新内核运行正常，重启后再次运行 '--full-kernel' 即可固定为永久默认。"
else
    echo "  1. 请立即在宿主机执行 'reboot' 重启以进入 $KERNEL_VER 内核。"
    echo "  2. 原系统内核 ($SAVED_ORIG) 已安全保留在 /boot 中；"
    echo "  3. 随时可通过以下命令自由切换模式："
    echo "     * 切回飞牛原生修改内核: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --fnos-dv"
    echo "     * 恢复纯净原厂系统内核: docker run --rm --privileged -v /:/host ${DOCKER_REPO}:kernel --restore"
fi
echo "================================================================"
"""


def make_install_script(
    kernel_ver: str,
    pkg_ver: str,
    repo: str,
    github_repo: str,
    fnos_release_tag: str,
    fnos_gh_mirror: str,
) -> str:
    return (
        SCRIPT_TEMPLATE.replace("__KERNEL_VER__", kernel_ver)
        .replace("__PKG_VER__", pkg_ver)
        .replace("__REPO__", repo)
        .replace("__GITHUB_REPO__", github_repo)
        .replace("__FNOS_RELEASE_TAG__", fnos_release_tag)
        .replace("__FNOS_GH_MIRROR__", fnos_gh_mirror)
    )


def _add_file_to_tar(tf: tarfile.TarFile, arcname: str, src_path: str, mode: int = 0o644) -> bytes:
    """将文件写入 tar 流并返回原始字节内容。"""
    with open(src_path, "rb") as f:
        data = f.read()
    ti = tarfile.TarInfo(name=arcname)
    ti.size = len(data)
    ti.mode = mode
    tf.addfile(ti, io.BytesIO(data))
    return data


def build_layer_tar(
    bundle_dir: str,
    kernel_ver: str,
    pkg_ver: str,
    repo: str,
    github_repo: str,
    fnos_release_tag: str,
    fnos_gh_mirror: str = "https://gh-proxy.com",
    include_builtin_fnos: bool = True,
) -> tuple[bytes, str]:
    buf = io.BytesIO()
    fnos_shas: dict[str, str] = {}

    with tarfile.open(fileobj=buf, mode="w") as tf:
        for d in ["bin", "etc", "sbin", "usr", "usr/bin", "usr/sbin", "debs", "fnos", "host", "out", "tmp"]:
            ti = tarfile.TarInfo(name=d)
            ti.type = tarfile.DIRTYPE
            ti.mode = 0o755
            tf.addfile(ti)

        _add_file_to_tar(tf, "bin/busybox", "/bin/busybox", mode=0o755)

        applets = [
            "sh", "ash", "cp", "mv", "rm", "mkdir", "cat", "echo", "ls",
            "uname", "grep", "sed", "awk", "sort", "tr", "cut",
            "chmod", "sleep", "head", "tail", "tar", "gzip", "xz",
            "wget", "ssl_client", "sha256sum", "mktemp", "basename",
            "dirname", "find", "wc", "strings", "xzcat", "zcat",
            "env", "expr", "touch",
        ]
        for app in applets:
            ti = tarfile.TarInfo(name=f"bin/{app}")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "busybox"
            tf.addfile(ti)

        for app in ["chroot"]:
            ti = tarfile.TarInfo(name=f"usr/sbin/{app}")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "../../bin/busybox"
            tf.addfile(ti)

        script_bytes = make_install_script(
            kernel_ver=kernel_ver,
            pkg_ver=pkg_ver,
            repo=repo,
            github_repo=github_repo,
            fnos_release_tag=fnos_release_tag,
            fnos_gh_mirror=fnos_gh_mirror,
        ).encode("utf-8")
        ti = tarfile.TarInfo(name="install-kernel.sh")
        ti.size = len(script_bytes)
        ti.mode = 0o755
        tf.addfile(ti, io.BytesIO(script_bytes))

        for fname in sorted(os.listdir(bundle_dir)):
            fpath = os.path.join(bundle_dir, fname)
            if fname.endswith(".deb") and "dv" in fname and ("linux-image-" in fname or "linux-headers-" in fname):
                _add_file_to_tar(tf, f"debs/{fname}", fpath, mode=0o644)

        if include_builtin_fnos:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            search_dirs = [bundle_dir]
            if os.path.isdir(script_dir) and os.path.abspath(script_dir) != os.path.abspath(bundle_dir):
                search_dirs.append(script_dir)
            for sdir in search_dirs:
                for fname in sorted(os.listdir(sdir)):
                    if fname.startswith("fnos-") and fname.endswith("-dv-modules.tar.gz") and fname not in fnos_shas:
                        fpath = os.path.join(sdir, fname)
                        data = _add_file_to_tar(tf, f"fnos/{fname}", fpath, mode=0o644)
                        fnos_shas[fname] = hashlib.sha256(data).hexdigest()

    fnos_manifest_text = "".join(f"{fnos_shas[k]}  {k}\n" for k in sorted(fnos_shas))
    fnos_hash = hashlib.sha256(fnos_manifest_text.encode("utf-8")).hexdigest()
    return buf.getvalue(), fnos_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--output-tar", required=True)
    parser.add_argument("--kernel-ver", required=True)
    parser.add_argument("--pkg-ver", required=True)
    parser.add_argument("--kernel-hash", default="")
    parser.add_argument("--repo", default="aguan/libreelec-hades-dv")
    parser.add_argument("--github-repo", default="zhang1yun1/LibreELEC-Hades")
    parser.add_argument("--fnos-release-tag", default="fnos-dv-modules")
    parser.add_argument("--fnos-gh-mirror", default="https://gh-proxy.com")
    parser.add_argument("--no-builtin-fnos", action="store_true")
    args = parser.parse_args()

    layer_bytes, fnos_hash = build_layer_tar(
        bundle_dir=args.bundle_dir,
        kernel_ver=args.kernel_ver,
        pkg_ver=args.pkg_ver,
        repo=args.repo,
        github_repo=args.github_repo,
        fnos_release_tag=args.fnos_release_tag,
        fnos_gh_mirror=args.fnos_gh_mirror,
        include_builtin_fnos=not args.no_builtin_fnos,
    )
    layer_sha = hashlib.sha256(layer_bytes).hexdigest()

    with open(__file__, "rb") as sf:
        installer_rev = hashlib.sha256(sf.read()).hexdigest()[:16]

    created_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config_obj = {
        "architecture": "amd64",
        "os": "linux",
        "created": created_ts,
        "config": {
            "Env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            ],
            "Entrypoint": ["/install-kernel.sh"],
            "WorkingDir": "/",
            "Labels": {
                "org.opencontainers.image.title": f"LibreELEC Dolby Vision Kernel Installer ({args.kernel_ver})",
                "org.opencontainers.image.version": args.pkg_ver,
                "org.opencontainers.image.description": f"Three-mode host kernel manager for LibreELEC Dolby Vision (FnOS native DV injection / {args.kernel_ver} full kernel / pure original kernel rollback)",
                "io.kodi-dv.kernel-hash": args.kernel_hash,
                "io.kodi-dv.installer-rev": installer_rev,
                "io.kodi-dv.fnos-hash": fnos_hash,
            },
        },
        "rootfs": {
            "type": "layers",
            "diff_ids": [f"sha256:{layer_sha}"],
        },
        "history": [
            {
                "created": created_ts,
                "created_by": f"build-kernel-installer.py ({args.kernel_ver} {args.pkg_ver})",
            }
        ],
    }

    config_bytes = json.dumps(config_obj, indent=2).encode("utf-8")
    config_sha = hashlib.sha256(config_bytes).hexdigest()

    manifest_obj = [
        {
            "Config": f"{config_sha}.json",
            "RepoTags": [
                f"{args.repo}:kernel",
                f"{args.repo}:kernel-{args.kernel_ver}",
            ],
            "Layers": [f"{layer_sha}/layer.tar"],
        }
    ]
    manifest_bytes = json.dumps(manifest_obj).encode("utf-8")

    with tarfile.open(args.output_tar, "w") as out_tf:
        ti = tarfile.TarInfo(name=f"{layer_sha}/layer.tar")
        ti.size = len(layer_bytes)
        ti.mode = 0o644
        out_tf.addfile(ti, io.BytesIO(layer_bytes))

        ti = tarfile.TarInfo(name=f"{config_sha}.json")
        ti.size = len(config_bytes)
        ti.mode = 0o644
        out_tf.addfile(ti, io.BytesIO(config_bytes))

        ti = tarfile.TarInfo(name="manifest.json")
        ti.size = len(manifest_bytes)
        ti.mode = 0o644
        out_tf.addfile(ti, io.BytesIO(manifest_bytes))

    print(f"Created {args.output_tar} ({os.path.getsize(args.output_tar) / (1024*1024):.2f} MB)")


if __name__ == "__main__":
    main()
