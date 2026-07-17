"""期3 集成验收（manual，不进 CI）：真实触发 MediaCrawler 搜索，并对典型笔记读评论。

前置：① ../MediaCrawler 已就绪（Playwright 环境）；② 已在 MediaCrawler 登录（qrcode/cookie）。
用法：
  uv run python scripts/integration_mediacrawler.py [--config configs/sample_mediacrawler.yaml] [-v]
建议：使用 CDP / 本机已登录浏览器复用会话；纯 qrcode 可能因 detail 子进程再次要求扫码。
注意：真实联网采集小红书，请低频、个人自用；真实评论采集不进 CI。
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/sample_mediacrawler.yaml")
    ap.add_argument("--verbose", "-v", action="store_true", help="输出 DEBUG 控制台日志")
    args = ap.parse_args()
    sys.stdout.write("提示：建议在 CDP / 本机已登录浏览器会话下运行，避免 detail 阶段二次扫码。\n")
    command = [
        sys.executable,
        "-m",
        "src.recon.entrypoints.cli",
        "research",
        "--config",
        args.config,
    ]
    if args.verbose:
        command.append("--verbose")
    raise SystemExit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()
