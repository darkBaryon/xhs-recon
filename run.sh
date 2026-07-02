#!/usr/bin/env bash
# xhs-recon 启动脚本
#   ./run.sh            # 离线 fixture demo（无需登录/浏览器）
#   ./run.sh real       # 真实采集：自动确保采集浏览器就绪后运行（可加 --config xxx.yaml）
#   ./run.sh browser    # 只启动/检查采集浏览器（专用 profile + CDP 9222）
set -euo pipefail
cd "$(dirname "$0")"

CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE_DIR="$HOME/.xhs-recon-chrome"
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

cmd="${1:-demo}"
[ $# -gt 0 ] && shift

case "$cmd" in
  demo)
    exec uv run python -m src.pipelines.run_research --config configs/sample.yaml "$@"
    ;;
  real)
    ensure_browser
    exec uv run python scripts/integration_mediacrawler.py --config configs/sample_mediacrawler.yaml "$@"
    ;;
  browser)
    ensure_browser
    ;;
  *)
    echo "用法: ./run.sh [demo|real|browser]" >&2
    exit 2
    ;;
esac
