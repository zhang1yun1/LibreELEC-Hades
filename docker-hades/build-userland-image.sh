#!/usr/bin/env bash
set -euo pipefail

RELEASE_TAG="${1:?Usage: build-userland-image.sh <RELEASE_TAG> <SOURCE_URL_OR_SYSTEM_PATH> <DOCKERHUB_REPO> [UPSTREAM_COMMIT] [EXTRA_TAG]}"
SOURCE_REF="${2:?Missing SOURCE_URL_OR_SYSTEM_PATH}"
DOCKERHUB_REPO="${3:?Missing DOCKERHUB_REPO}"
UPSTREAM_COMMIT="${4:-}"
EXTRA_TAG="${5:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/le-hades-userland.XXXXXX")"
trap 'sudo rm -rf "$WORK_DIR"' EXIT

echo "=== [1/4] 正在获取用户态 SYSTEM SquashFS: ${RELEASE_TAG} ==="
echo "Source: ${SOURCE_REF}"

SYSTEM_FILE=""
if [[ "${SOURCE_REF}" == http://* || "${SOURCE_REF}" == https://* ]]; then
    if [[ "${SOURCE_REF}" == *.tar ]]; then
        curl -fL --retry 5 -o "${WORK_DIR}/release.tar" "${SOURCE_REF}"
        mkdir -p "${WORK_DIR}/extracted"
        tar -xf "${WORK_DIR}/release.tar" -C "${WORK_DIR}/extracted" --wildcards '*/target/SYSTEM'
        SYSTEM_FILE=$(find "${WORK_DIR}/extracted" -name "SYSTEM" -type f | head -n 1)
    elif [[ "${SOURCE_REF}" == *.img.gz ]]; then
        curl -fL --retry 5 -o "${WORK_DIR}/release.img.gz" "${SOURCE_REF}"
        gunzip "${WORK_DIR}/release.img.gz"
        7z x "${WORK_DIR}/release.img" -o"${WORK_DIR}/img_parts" >/dev/null
        PART_FILE=$(find "${WORK_DIR}/img_parts" -type f | sort | head -n 1)
        7z x "${PART_FILE}" -o"${WORK_DIR}/fat_parts" >/dev/null
        SYSTEM_FILE="${WORK_DIR}/fat_parts/SYSTEM"
    else
        echo "Unsupported remote asset format: ${SOURCE_REF}"
        exit 1
    fi
elif [[ -f "${SOURCE_REF}" ]]; then
    if [[ "${SOURCE_REF}" == *.system || "$(basename "${SOURCE_REF}")" == "SYSTEM" ]]; then
        SYSTEM_FILE="${SOURCE_REF}"
    elif [[ "${SOURCE_REF}" == *.tar ]]; then
        mkdir -p "${WORK_DIR}/extracted"
        tar -xf "${SOURCE_REF}" -C "${WORK_DIR}/extracted" --wildcards '*/target/SYSTEM'
        SYSTEM_FILE=$(find "${WORK_DIR}/extracted" -name "SYSTEM" -type f | head -n 1)
    elif [[ "${SOURCE_REF}" == *.img.gz ]]; then
        gzip -dc "${SOURCE_REF}" > "${WORK_DIR}/release.img"
        7z x "${WORK_DIR}/release.img" -o"${WORK_DIR}/img_parts" >/dev/null
        PART_FILE=$(find "${WORK_DIR}/img_parts" -type f | sort | head -n 1)
        7z x "${PART_FILE}" -o"${WORK_DIR}/fat_parts" >/dev/null
        SYSTEM_FILE="${WORK_DIR}/fat_parts/SYSTEM"
    elif [[ "${SOURCE_REF}" == *.img ]]; then
        7z x "${SOURCE_REF}" -o"${WORK_DIR}/img_parts" >/dev/null
        if [[ -f "${WORK_DIR}/img_parts/SYSTEM" ]]; then
            SYSTEM_FILE="${WORK_DIR}/img_parts/SYSTEM"
        else
            PART_FILE=$(find "${WORK_DIR}/img_parts" -type f | sort | head -n 1)
            7z x "${PART_FILE}" -o"${WORK_DIR}/fat_parts" >/dev/null
            SYSTEM_FILE="${WORK_DIR}/fat_parts/SYSTEM"
        fi
    else
        echo "Unsupported local file format: ${SOURCE_REF}"
        exit 1
    fi
else
    echo "Source not found: ${SOURCE_REF}"
    exit 1
fi

if [[ -z "${SYSTEM_FILE}" || ! -f "${SYSTEM_FILE}" ]]; then
    echo "Failed to locate SYSTEM SquashFS file!"
    exit 1
fi

echo "=== [2/4] 正在解包 SquashFS 根文件系统 ==="
sudo unsquashfs -d "${WORK_DIR}/rootfs" "${SYSTEM_FILE}"
sudo install -m 0755 "${SCRIPT_DIR}/start-kodi.sh" "${WORK_DIR}/rootfs/usr/bin/start-kodi.sh"

echo "=== [3/4] 正在构建 Docker 镜像: ${DOCKERHUB_REPO}:${RELEASE_TAG} ==="
IMPORT_ARGS=(
    --change 'ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    --change 'ENV HOME=/storage'
    --change 'ENV KODI_HOME=/usr/share/kodi'
    --change 'ENV KODI_TEMP=/storage/.kodi/temp'
    --change 'ENV LIBVA_DRIVER_NAME=auto'
    --change 'WORKDIR /storage'
    --change 'ENTRYPOINT ["/usr/bin/start-kodi.sh"]'
    --change "LABEL org.opencontainers.image.title=\"LibreELEC Hades x86_64 Dolby Vision (${RELEASE_TAG})\""
    --change "LABEL org.opencontainers.image.version=\"${RELEASE_TAG}\""
    --change "LABEL org.opencontainers.image.source=\"https://github.com/flhs0606/LibreELEC-Hades\""
)
if [[ -n "${UPSTREAM_COMMIT}" ]]; then
    IMPORT_ARGS+=(--change "LABEL io.kodi-dv.upstream-commit=\"${UPSTREAM_COMMIT}\"")
fi

sudo tar -C "${WORK_DIR}/rootfs" -cf - . | docker import "${IMPORT_ARGS[@]}" - "${DOCKERHUB_REPO}:${RELEASE_TAG}"

docker tag "${DOCKERHUB_REPO}:${RELEASE_TAG}" "${DOCKERHUB_REPO}:latest"
if [[ -n "${EXTRA_TAG}" && "${EXTRA_TAG}" != "${RELEASE_TAG}" && "${EXTRA_TAG}" != "latest" ]]; then
    docker tag "${DOCKERHUB_REPO}:${RELEASE_TAG}" "${DOCKERHUB_REPO}:${EXTRA_TAG}"
fi

echo "=== [4/4] 正在推送用户态镜像至 Docker Hub ==="
docker push "${DOCKERHUB_REPO}:${RELEASE_TAG}"
docker push "${DOCKERHUB_REPO}:latest"
if [[ -n "${EXTRA_TAG}" && "${EXTRA_TAG}" != "${RELEASE_TAG}" && "${EXTRA_TAG}" != "latest" ]]; then
    docker push "${DOCKERHUB_REPO}:${EXTRA_TAG}"
fi
echo "=== 用户态镜像发布完成: ${DOCKERHUB_REPO}:${RELEASE_TAG} ==="
