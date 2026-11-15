#!/bin/sh
set -e

mkdir -p /storage/.kodi/temp /storage/.kodi/userdata /storage/.cache /var/run /var/log /run/libreelec

# 初始化 LibreELEC SSL 根证书
if [ -f /etc/ssl/cacert.pem.system ]; then
    cp -f /etc/ssl/cacert.pem.system /run/libreelec/cacert.pem
fi

# 自动识别 Intel / AMD 核显驱动
HAS_INTEL=0
HAS_AMD=0
for vfile in /sys/class/drm/renderD*/device/vendor; do
    if [ -f "$vfile" ]; then
        vendor=$(cat "$vfile" 2>/dev/null || true)
        case "$vendor" in
            0x8086) HAS_INTEL=1 ;;
            0x1002) HAS_AMD=1 ;;
        esac
    fi
done

if [ -z "$LIBVA_DRIVER_NAME" ] || [ "$LIBVA_DRIVER_NAME" = "auto" ]; then
    if [ "$HAS_AMD" -eq 1 ] && [ "$HAS_INTEL" -eq 0 ]; then
        export LIBVA_DRIVER_NAME=radeonsi
    elif [ "$HAS_INTEL" -eq 1 ]; then
        export LIBVA_DRIVER_NAME=iHD
    fi
elif [ "$LIBVA_DRIVER_NAME" = "iHD" ] && [ "$HAS_AMD" -eq 1 ] && [ "$HAS_INTEL" -eq 0 ]; then
    echo "[start-kodi] 检测到纯 AMD 显卡环境 (0x1002)，自动切换 LIBVA_DRIVER_NAME=radeonsi"
    export LIBVA_DRIVER_NAME=radeonsi
fi

# 启动 Hades 独立 BD-J 蓝光菜单后台服务（若存在）
for bdj_bin in /usr/bin/bdj-service /usr/lib/kodi/bdj-service /usr/libexec/bdj-service; do
    if [ -x "$bdj_bin" ] && ! pgrep -f "$(basename "$bdj_bin")" >/dev/null 2>&1; then
        "$bdj_bin" >/var/log/bdj-service.log 2>&1 &
    fi
done

# 清理残留崩溃锁文件
rm -f /storage/.kodi/temp/*.lock

exec /usr/lib/kodi/kodi.bin --standalone -fs --audio-backend=alsa "$@"
