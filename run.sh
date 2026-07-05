#!/usr/bin/env bash
# xhs-recon 启动脚本
#   ./run.sh            # 离线 fixture demo（无需登录/浏览器）
#   ./run.sh search     # 真实·广角：关键词搜索+榜单（每周）
#   ./run.sh sync       # 真实·长焦：watchlist→creator→topic_feed（每周）
#   ./run.sh comments   # 真实·深读：补采评论（做深度分析时）
#   ./run.sh real       # 真实·全流程（= research）
#   ./run.sh browser    # 只启动/检查采集浏览器（专用 profile + CDP 9222）
#   ./run.sh web        # 把最新一跑渲染成本地静态站并打开（离线，无需采集）
# 主题配置默认 configs/留学辅导/run.yaml，换赛道：CONFIG=configs/<主题>/run.yaml ./run.sh sync
set -euo pipefail
cd "$(dirname "$0")"

CONFIG="${CONFIG:-configs/留学辅导/run.yaml}"

CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="$HOME/.xhs-recon-chrome"
LOCK_DIR="$PROFILE_DIR/.xhs-recon-run.lock"
CDP_URL="http://127.0.0.1:9222/json/version"

cdp_alive() { curl -s --max-time 2 "$CDP_URL" >/dev/null 2>&1; }

ensure_browser() {
  if cdp_alive; then
    echo "采集浏览器已就绪（CDP 9222）"
    return
  fi
  echo "启动采集浏览器（专用 profile：${PROFILE_DIR}，静音后台）……"
  # Chrome 136+ 要求非默认 user-data-dir 才会真正开启调试端口；
  # 必须直接调二进制起第二实例（open -a 会把参数丢给已运行实例）。
  "$CHROME_BIN" --remote-debugging-port=9222 --user-data-dir="$PROFILE_DIR" \
    >/dev/null 2>&1 &
  for _ in $(seq 1 15); do
    sleep 1
    if cdp_alive; then
      echo "采集浏览器已就绪（CDP 9222）"
      echo "提示：若弹出的窗口里小红书未登录，请先扫码登录再继续（登录态会保存在专用 profile）。"
      return
    fi
  done
  echo "错误：等待 15s 后 CDP 9222 仍不可达，请检查 Chrome 是否正常启动。" >&2
  exit 1
}

release_run_lock() {
  if [ -d "$LOCK_DIR" ] && [ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
}

acquire_run_lock() {
  mkdir -p "$PROFILE_DIR"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    trap release_run_lock EXIT
    return
  fi

  holder="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$holder" ] && ps -p "$holder" >/dev/null 2>&1; then
    echo "错误：已有真实采集任务在运行（pid ${holder}）。请等它结束后再跑，避免多个任务共用 CDP 触发风控。" >&2
    exit 1
  fi

  echo "清理上次异常退出留下的采集锁……" >&2
  rm -f "$LOCK_DIR/pid" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || {
    echo "错误：采集锁被占用：$LOCK_DIR" >&2
    exit 1
  }
  mkdir "$LOCK_DIR"
  printf '%s\n' "$$" >"$LOCK_DIR/pid"
  trap release_run_lock EXIT
}

cmd="${1:-demo}"
[ $# -gt 0 ] && shift

case "$cmd" in
  demo)
    exec uv run python -m src.pipelines.run_research --config configs/sample.yaml "$@"
    ;;
  search|sync|comments)
    ensure_browser
    acquire_run_lock
    uv run python -m src.pipelines.cli "$cmd" --config "$CONFIG" "$@"
    ;;
  real)
    ensure_browser
    acquire_run_lock
    uv run python -m src.pipelines.cli research --config "$CONFIG" "$@"
    ;;
  browser)
    ensure_browser
    ;;
  web)
    # 把最新一跑的导出渲染成本地静态站并打开（离线，无需采集浏览器/锁）
    line="$(uv run python -m src.pipelines.cli web --config "$CONFIG" "$@")"
    echo "$line"
    path="${line#web: }"
    [ -n "$path" ] && [ -f "$path" ] && command -v open >/dev/null 2>&1 && open "$path"
    ;;
  *)
    echo "用法: ./run.sh [demo|search|sync|comments|real|browser|web]" >&2
    exit 2
    ;;
esac
