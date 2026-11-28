#!/bin/sh
set -e

has_pending_restore() {
    for _f in /storage/.restore/*.tar /storage/.restore/*.tar.bz2 /storage/.restore/*.tar.gz /storage/.restore/*.tar.xz /storage/.restore/*.tar.zst; do
        [ -f "$_f" ] && return 0
    done
    return 1
}

apply_pending_restore_or_reset() {
    if has_pending_restore || [ -f /storage/.cache/reset_soft ] || [ -f /storage/.cache/reset_hard ]; then
        python3 - << 'PY'
import os
import shutil
import tarfile

RESTORE_DIR = "/storage/.restore"
SOFT_DIRS = ["/storage/.kodi", "/storage/.cache", "/storage/.config"]
EXTS = (".tar", ".tar.bz2", ".tar.gz", ".tar.xz", ".tar.zst")

def clear_dir_contents(path):
    if not os.path.isdir(path):
        return True
    ok = True
    with os.scandir(path) as it:
        for entry in it:
            try:
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    os.unlink(entry.path)
                else:
                    shutil.rmtree(entry.path)
            except OSError as err:
                print(f"[start-kodi] 清理 {entry.path} 失败: {err}")
                ok = False
    return ok

def find_backup():
    if not os.path.isdir(RESTORE_DIR):
        return None
    for name in sorted(os.listdir(RESTORE_DIR)):
        if name.endswith(EXTS):
            p = os.path.join(RESTORE_DIR, name)
            if os.path.isfile(p):
                return p
    return None

reset_hard = "/storage/.cache/reset_hard"
reset_soft = "/storage/.cache/reset_soft"
backup_file = find_backup()

if os.path.isfile(reset_hard):
    print("[start-kodi] 检测到硬重置标记，正在清空 /storage...")
    try:
        os.remove(reset_hard)
    except OSError:
        pass
    clear_dir_contents("/storage")
    os.sync()
elif os.path.isfile(reset_soft):
    print("[start-kodi] 检测到软重置标记，正在重置 LibreELEC / Kodi 配置...")
    try:
        os.remove(reset_soft)
    except OSError:
        pass
    for d in SOFT_DIRS:
        clear_dir_contents(d)
    os.sync()
elif backup_file:
    print(f"[start-kodi] 检测到待还原备份 {backup_file}，正在恢复配置...")
    if tarfile.is_tarfile(backup_file):
        if all(clear_dir_contents(d) for d in SOFT_DIRS):
            try:
                with tarfile.open(backup_file, "r:*") as tf:
                    tf.extractall(path="/", filter="fully_trusted")
                print("[start-kodi] 备份还原成功！")
            except Exception as err:
                print(f"[start-kodi] 备份解压失败: {err}")
    else:
        print(f"[start-kodi] 无效的备份压缩包: {backup_file}")
    try:
        os.remove(backup_file)
    except OSError:
        pass
    os.sync()
PY
    fi
}

ensure_runtime_env() {
    # 对齐真实 LibreELEC：/var/run 指向 /run，使 /run/dbus 与 /var/run/service.libreelec.settings.sock 统一落盘
    if [ ! -L /var/run ]; then
        rm -rf /var/run
        ln -sfn /run /var/run
    fi

    mkdir -p /storage/.kodi/temp /storage/.kodi/userdata /storage/.cache /storage/.config /storage/.ssh /storage/backup /storage/.restore /var/log /run/libreelec /run/dbus

    # 初始化 machine-id（/etc/machine-id -> /storage/.cache/systemd-machine-id）
    if [ ! -s /storage/.cache/systemd-machine-id ] && [ -x /usr/bin/dbus-uuidgen ]; then
        /usr/bin/dbus-uuidgen --ensure=/storage/.cache/systemd-machine-id 2>/dev/null || true
    fi

    # 启动容器内系统 D-Bus（LibreELEC 设置插件 dbus_utils 依赖 /run/dbus/system_bus_socket）
    if [ -x /usr/bin/dbus-daemon ] && ! pgrep -x dbus-daemon >/dev/null 2>&1; then
        rm -f /run/dbus/pid /run/dbus/system_bus_socket
        /usr/bin/dbus-daemon --system --fork >/var/log/dbus.log 2>&1 || true
    fi

    # 初始化 LibreELEC SSL 根证书
    if [ -f /etc/ssl/cacert.pem.system ]; then
        cp -f /etc/ssl/cacert.pem.system /run/libreelec/cacert.pem
    fi

    # 若宿主机未运行 udevd（例如 iStoreOS / OpenWrt），启动容器内置 systemd-udevd 并触发 input 事件以便 libinput 识别遥控器/键鼠
    if [ ! -d /run/udev/data ] || ! ls /run/udev/data/c13:* >/dev/null 2>&1; then
        if [ -x /usr/lib/systemd/systemd-udevd ] && [ -w /sys ]; then
            mkdir -p /run/udev
            if ! pgrep -x systemd-udevd >/dev/null 2>&1; then
                /usr/lib/systemd/systemd-udevd --daemon >/var/log/udevd.log 2>&1 || true
            fi
            udevadm trigger --subsystem-match=input --action=add >/dev/null 2>&1 || true
            udevadm settle --timeout=3 >/dev/null 2>&1 || true
        fi
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
}

KODI_PID=""
STOP_REQUESTED=0
trap 'STOP_REQUESTED=1; [ -n "$KODI_PID" ] && kill -TERM "$KODI_PID" 2>/dev/null || true' TERM INT

while :; do
    apply_pending_restore_or_reset
    ensure_runtime_env
    rm -f /run/libreelec/.kodi-restart

    /usr/lib/kodi/kodi.bin --standalone -fs --audio-backend=alsa "$@" &
    KODI_PID=$!
    set +e
    wait "$KODI_PID"
    KODI_RC=$?
    set -e
    KODI_PID=""

    [ "$STOP_REQUESTED" -eq 1 ] && exit "$KODI_RC"
    if [ -f /run/libreelec/.kodi-restart ] || \
       has_pending_restore || \
       [ -f /storage/.cache/reset_soft ] || \
       [ -f /storage/.cache/reset_hard ]; then
        rm -f /run/libreelec/.kodi-restart
        continue
    fi
    exit "$KODI_RC"
done
