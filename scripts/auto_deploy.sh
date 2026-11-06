#!/usr/bin/env bash
# 主动拉取 main 分支并部署（由 deploy-watcher.service 定时调用）。
#
# 用法：
#   ./scripts/auto_deploy.sh            # 检查一次：有新提交才部署
#   ./scripts/auto_deploy.sh --force    # 忽略是否有新提交，强制同步依赖并重启
#   ./scripts/auto_deploy.sh --watch    # 常驻轮询，间隔由 POLL_INTERVAL 控制（默认 180 秒）
#
# 环境变量（一般不用改）：
#   APP_DIR        项目目录，默认 /home/ubuntu/personal-assistant
#   REPO_BRANCH    跟踪分支，默认 main
#   SERVICE        systemd 服务名，默认 assistant
#   HEALTH_URL     健康检查地址
#   POLL_INTERVAL  --watch 轮询间隔秒数
#   LOG_FILE       部署日志路径，默认 $APP_DIR/deploy.log
#
# 失败策略：fetch/依赖/迁移/重启/健康检查任一步失败，回滚到上一 commit 并重启旧版本，
# 不覆盖线上服务；所有结果写入 deploy.log。

set -uo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/personal-assistant}"
REPO_BRANCH="${REPO_BRANCH:-main}"
SERVICE="${SERVICE:-assistant}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/v1/health}"
UV_INDEX="${UV_INDEX:-https://mirrors.cloud.tencent.com/pypi/simple}"
POLL_INTERVAL="${POLL_INTERVAL:-180}"
LOG_FILE="${LOG_FILE:-$APP_DIR/deploy.log}"
LOCK_FILE="${LOCK_FILE:-/tmp/personal-assistant-deploy.lock}"

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export GIT_TERMINAL_PROMPT=0

FORCE=0
WATCH=0

usage() {
  sed -n '2,20p' "$0"
}

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG_FILE"
}

health_check() {
  local attempt body
  for attempt in $(seq 1 30); do
    if body="$(curl -fsS --max-time 4 "$HEALTH_URL" 2>/dev/null)"; then
      if printf '%s' "$body" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
        log "健康检查通过（第 ${attempt} 次）：$body"
        return 0
      fi
    fi
    sleep 2
  done
  log "健康检查失败：$HEALTH_URL"
  return 1
}

backup_db() {
  local db dest
  shopt -s nullglob
  for db in "$APP_DIR"/data/*.db; do
    dest="$APP_DIR/data/backups/$(basename "$db" .db)-$(date '+%Y%m%d-%H%M%S').db"
    mkdir -p "$APP_DIR/data/backups"
    if cp -p "$db" "$dest"; then
      log "已备份数据库：$dest"
    else
      log "WARNING: 数据库备份失败：$db"
    fi
  done
  shopt -u nullglob
}

# 回滚到部署前的 commit，并让旧版本继续提供服务。
rollback() {
  local reason="$1" prev_sha="$2"
  log "ERROR: $reason；开始回滚到 $prev_sha"
  cd "$APP_DIR" || { log "ERROR: 无法进入 $APP_DIR，请人工处理"; return 1; }

  if git reset --hard "$prev_sha" >>"$LOG_FILE" 2>&1; then
    log "代码已回滚到 $prev_sha"
  else
    log "ERROR: git reset --hard 失败，请人工处理"
  fi

  if command -v uv >/dev/null 2>&1; then
    if UV_HTTP_TIMEOUT=180 uv sync --python 3.12 --no-dev --frozen \
      --index-url "$UV_INDEX" >>"$LOG_FILE" 2>&1; then
      log "回滚后依赖已同步"
    else
      log "WARNING: 回滚时 uv sync 失败，请人工检查"
    fi
  fi

  if sudo -n /usr/bin/systemctl restart "$SERVICE" >>"$LOG_FILE" 2>&1; then
    log "已重启 $SERVICE"
  else
    log "WARNING: 回滚时重启 $SERVICE 失败，请人工检查"
  fi

  if health_check; then
    log "回滚完成，旧版本 $prev_sha 运行正常（状态：FAILED）"
  else
    log "ERROR: 回滚后健康检查仍失败，请立即人工介入（状态：FAILED）"
  fi
  return 1
}

deploy_once() {
  local force="${1:-0}"
  local prev_sha new_sha branch dirty uv_bin

  log "===== 开始部署检查 ====="
  cd "$APP_DIR" || { log "ERROR: 项目目录不存在：$APP_DIR"; return 1; }

  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  if [ "$branch" != "$REPO_BRANCH" ]; then
    log "ERROR: 当前分支为 ${branch:-未知}，期望 $REPO_BRANCH，已跳过"
    return 1
  fi

  # 只检查已跟踪文件的改动；未跟踪文件（如 deploy.log）不影响部署。
  dirty="$(git status --porcelain --untracked-files=no)"
  if [ -n "$dirty" ]; then
    log "ERROR: 工作区有未提交改动，已跳过以避免覆盖服务器修改"
    printf '%s\n' "$dirty" | while read -r line; do log "  $line"; done
    return 1
  fi

  if ! timeout 90 git fetch --prune origin "$REPO_BRANCH" >>"$LOG_FILE" 2>&1; then
    log "ERROR: git fetch 失败（网络或 Deploy Key 认证问题），保持当前版本"
    return 1
  fi

  prev_sha="$(git rev-parse HEAD)"
  new_sha="$(git rev-parse "origin/$REPO_BRANCH")"

  if [ "$prev_sha" = "$new_sha" ] && [ "$force" != "1" ]; then
    log "无更新：当前已是 origin/$REPO_BRANCH 最新提交 $prev_sha"
    return 0
  fi

  if [ "$prev_sha" = "$new_sha" ]; then
    log "强制部署：重新同步依赖并重启（$new_sha）"
  else
    log "发现更新：$prev_sha -> $new_sha"
    git log --oneline "$prev_sha..$new_sha" | head -20 | while read -r line; do log "  $line"; done
  fi

  if ! git merge --ff-only "$new_sha" >>"$LOG_FILE" 2>&1; then
    log "ERROR: 代码快进合并失败（可能有冲突），保持当前版本"
    git reset --hard "$prev_sha" >>"$LOG_FILE" 2>&1 || true
    return 1
  fi

  uv_bin="$(command -v uv || true)"
  if [ -z "$uv_bin" ]; then
    rollback "未找到 uv 命令" "$prev_sha"
    return 1
  fi

  log "同步依赖（uv sync）"
  if ! UV_HTTP_TIMEOUT=180 "$uv_bin" sync --python 3.12 --no-dev --frozen \
    --index-url "$UV_INDEX" >>"$LOG_FILE" 2>&1; then
    rollback "uv sync 失败" "$prev_sha"
    return 1
  fi

  backup_db

  log "执行数据库迁移"
  if ! (cd "$APP_DIR" && .venv/bin/python -c "from src.core.db import init_db; init_db()") \
    >>"$LOG_FILE" 2>&1; then
    rollback "数据库迁移失败" "$prev_sha"
    return 1
  fi

  log "重启 $SERVICE"
  if ! sudo -n /usr/bin/systemctl restart "$SERVICE" >>"$LOG_FILE" 2>&1; then
    rollback "systemctl restart 失败" "$prev_sha"
    return 1
  fi

  if ! health_check; then
    rollback "重启后健康检查失败" "$prev_sha"
    return 1
  fi

  log "部署成功：$new_sha（状态：SUCCESS）"
  return 0
}

deploy_with_lock() {
  (
    if command -v flock >/dev/null 2>&1; then
      if ! flock -n 9; then
        log "已有部署任务在运行，本次跳过"
        exit 0
      fi
    else
      log "WARNING: 未找到 flock，跳过并发保护"
    fi
    deploy_once "$FORCE"
  ) 9>"$LOCK_FILE"
}

case "${1:-}" in
  --force) FORCE=1 ;;
  --watch) WATCH=1 ;;
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) usage; exit 2 ;;
esac

if [ "$WATCH" = "1" ] && [ "$FORCE" = "1" ]; then
  echo "--watch 与 --force 不能同时使用" >&2
  exit 2
fi

if [ "$WATCH" = "1" ]; then
  log "启动部署轮询：每 ${POLL_INTERVAL} 秒检查一次 origin/$REPO_BRANCH"
  while true; do
    deploy_with_lock || true
    sleep "$POLL_INTERVAL"
  done
fi

deploy_with_lock
exit $?
