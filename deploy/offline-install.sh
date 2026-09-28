#!/usr/bin/env bash
# =============================================================================
# V-FLO 智能办公系统 · 内网服务器 Docker 离线安装脚本
# 适用：金品 JP KU2250-G2（海光 x86_64）· 公司内网服务器 192.168.2.22
# 用途：无外网环境下首次安装 Docker / Docker Compose，并导入应用镜像
#
# 使用方法（在可上网的机器准备离线包后，拷到内网服务器执行）：
#   1) 联网机：bash offline-install.sh prepare    # 生成 offline-bundle.tar.gz
#   2) 拷贝 offline-bundle.tar.gz 到内网服务器
#   3) 内网机：bash offline-install.sh install
#   4) 内网机：bash offline-install.sh verify
#
# 注意：本脚本不包含任何口令；服务器登录与数据库口令自行在 .env 中配置。
# =============================================================================
set -euo pipefail

BUNDLE_DIR="${BUNDLE_DIR:-/opt/vflo-offline}"
BUNDLE_TAR="${BUNDLE_TAR:-vflo-offline-bundle.tar.gz}"
WORK_DIR="${WORK_DIR:-/opt/vflo-offline-work}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/vflo-smart-office}"

# ---- 内核 / 架构检测 ----
ARCH="$(uname -m)"   # 海光为 x86_64
echo "[INFO] 架构: ${ARCH}"

log()  { echo -e "\033[1;32m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARM]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR ]\033[0m $*"; exit 1; }

need_root() {
  [[ "$(id -u)" -eq 0 ]] || err "请用 root 执行"
}

# =============================================================================
# prepare —— 在【可联网】机器上执行：下载离线包
# =============================================================================
cmd_prepare() {
  need_root
  mkdir -p "${BUNDLE_DIR}"
  cd "${BUNDLE_DIR}"

  local os_id=""
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    os_id=$(. /etc/os-release && echo "${ID}")
  fi
  log "宿主机发行版: ${os_id:-unknown} / ${ARCH}"

  log "下载 Docker 安装包（请按发行版选择）..."
  cat <<'EOF'
# ---------- RHEL / Rocky / openEuler / CentOS（rpm）----------
# 下载 docker-ce 与依赖 rpm 后放入 ./rpms/
# 示例（联网机）：
#   yum install -y yum-utils
#   yumdownloader --resolve --destdir=./rpms \
#     docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
#
# ---------- Ubuntu / Debian（deb）----------
#   apt-get download docker-ce docker-ce-cli containerd.io \
#     docker-buildx-plugin docker-compose-plugin
# 或使用官方静态二进制（全发行版通用，推荐内网）：
#   https://download.docker.com/linux/static/stable/x86_64/docker-27.x.tgz
#   https://github.com/docker/compose/releases/download/v2.x/docker-compose-linux-x86_64
EOF

  log "下载/导出应用基础镜像（联网机执行）..."
  cat <<'EOF'
# 拉取并导出镜像（在装好 Docker 的联网机执行）：
#   docker pull postgres:16-alpine
#   docker pull nginx:alpine
#   docker pull redis:7-alpine
#   docker pull python:3.11-slim
#   docker save postgres:16-alpine nginx:alpine redis:7-alpine python:3.11-slim \
#     | gzip > ./images/vflo-base-images.tar.gz
#
# 应用镜像（可选，已 build 过则导出）：
#   cd /path/to/vflo-smart-office && docker compose build
#   docker save vflo-app | gzip > ./images/vflo-app.tar.gz
EOF

  log "打包离线目录（请将 rpms/ 或 tgz/、images/ 放入 ${BUNDLE_DIR} 后执行）..."
  if compgen -G "${BUNDLE_DIR}/*" > /dev/null; then
    tar -czf "${BUNDLE_TAR}" -C "$(dirname "${BUNDLE_DIR}")" "$(basename "${BUNDLE_DIR}")"
    log "已生成: $(pwd)/${BUNDLE_TAR}"
    log "拷贝到内网服务器后执行: bash offline-install.sh install"
  else
    warn "目录为空；请按上方说明放入安装包与镜像后再打包。"
  fi
}

# =============================================================================
# install —— 在【内网】服务器上执行：装 Docker + 导入镜像
# =============================================================================
cmd_install() {
  need_root

  # 1. 解压离线包
  if [[ -f "${BUNDLE_TAR}" ]]; then
    log "解压 ${BUNDLE_TAR} ..."
    tar -xzf "${BUNDLE_TAR}" -C "$(dirname "${BUNDLE_DIR}")"
  fi
  mkdir -p "${WORK_DIR}"

  # 2. 安装 Docker（优先静态二进制，兼容海光 x86_64）
  if command -v docker >/dev/null 2>&1; then
    log "Docker 已安装: $(docker --version)"
  else
    if compgen -G "${BUNDLE_DIR}/tgz/docker-*.tgz" > /dev/null; then
      log "使用静态二进制安装 Docker ..."
      tar -xzf "${BUNDLE_DIR}"/tgz/docker-*.tgz -C "${WORK_DIR}"
      install -m 755 "${WORK_DIR}"/docker/* /usr/local/bin/
    elif compgen -G "${BUNDLE_DIR}/rpms/docker-ce*.rpm" > /dev/null; then
      log "使用 rpm 安装 ..."
      rpm -Uvh --force "${BUNDLE_DIR}"/rpms/*.rpm
    elif compgen -G "${BUNDLE_DIR}/debs/docker-ce*.deb" > /dev/null; then
      log "使用 deb 安装 ..."
      dpkg -i "${BUNDLE_DIR}"/debs/*.deb || apt-get -f install -y
    else
      err "未找到 Docker 安装包（tgz/rpms/debs），请先执行 prepare 并拷贝离线包"
    fi
  fi

  # 3. Docker Compose 插件（v2）
  if ! docker compose version >/dev/null 2>&1; then
    if compgen -G "${BUNDLE_DIR}/tgz/docker-compose-linux-*" > /dev/null; then
      log "安装 docker compose 插件 ..."
      mkdir -p /usr/local/lib/docker/cli-plugins
      cp "${BUNDLE_DIR}"/tgz/docker-compose-linux-* /usr/local/lib/docker/cli-plugins/docker-compose
      chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    else
      warn "未找到 compose 插件，后续请手动安装（docker compose 子命令不可用）"
    fi
  fi

  # 4. systemd 服务（静态安装时可能无 unit）
  if [[ ! -f /etc/systemd/system/docker.service ]]; then
    cat > /etc/systemd/system/docker.service <<'EOF'
[Unit]
Description=Docker Application Container Engine
After=network-online.target docker.socket
Requires=docker.socket

[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
ExecReload=/bin/kill -s HUP $MAINPID
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
TimeoutStartSec=0
RestartSec=2
Restart=always
StartLimitBurst=3
StartLimitInterval=60s

[Install]
WantedBy=multi-user.target
EOF
    cat > /etc/systemd/system/docker.socket <<'EOF'
[Unit]
Description=Docker Socket for the API

[Socket]
ListenStream=/run/docker.sock
SocketMode=0660
SocketUser=root
SocketGroup=docker

[Install]
WantedBy=sockets.target
EOF
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" },
  "data-root": "/var/lib/docker",
  "storage-driver": "overlay2"
}
EOF
    groupadd -f docker
    systemctl daemon-reload
    systemctl enable --now docker.socket docker
    log "Docker systemd 服务已配置"
  else
    systemctl enable --now docker || true
  fi

  # 5. 导入镜像
  if compgen -G "${BUNDLE_DIR}/images/*.tar.gz" > /dev/null; then
    for f in "${BUNDLE_DIR}"/images/*.tar.gz; do
      log "导入镜像: ${f}"
      gunzip -c "${f}" | docker load
    done
  else
    warn "未找到 images/*.tar.gz，跳过镜像导入"
  fi

  # 6. 部署目录
  mkdir -p /data/{pg,backups,logs,uploads,certs,redis} /opt/vflo-smart-office
  log "数据目录已创建 /data/* 与 ${COMPOSE_DIR}"

  log "安装完成。下一步："
  echo "  cd ${COMPOSE_DIR}"
  echo "  cp .env.deploy.example .env && vim .env"
  echo "  docker compose build   # 若已有 vflo-app 镜像可跳过"
  echo "  docker compose up -d"
}

# =============================================================================
# verify —— 环境自检
# =============================================================================
cmd_verify() {
  log "Docker: $(docker --version 2>/dev/null || echo '未安装')"
  docker compose version 2>/dev/null || warn "docker compose 不可用"
  docker info >/dev/null 2>&1 && log "docker daemon 运行中" || warn "docker daemon 未运行"
  docker images 2>/dev/null | sed -n '1,10p' || true
  echo
  log "磁盘:"
  df -h / /data 2>/dev/null || df -h /
  echo
  log "内存 / CPU:"
  free -h | sed -n '1,3p'
  nproc
  echo
  log "健康检查（需应用已启动）:"
  curl -fsS http://127.0.0.1:8000/api/health && echo || warn "应用未启动或健康检查失败（可忽略）"
}

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  echo "用法: $0 {prepare|install|verify}"
}

case "${1:-}" in
  prepare) cmd_prepare ;;
  install) cmd_install ;;
  verify)  cmd_verify ;;
  *)       usage; exit 1 ;;
esac
