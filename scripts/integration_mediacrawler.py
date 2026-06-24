"""期2 集成验收（manual，不进 CI）：真实触发 MediaCrawler 采集，端到端跑通管线。

前置：① ../MediaCrawler 已就绪（Playwright 环境）；② 已在 MediaCrawler 登录（qrcode/cookie）。
用法：uv run python scripts/integration_mediacrawler.py [--config configs/sample_mediacrawler.yaml]
注意：真实联网采集小红书，请低频、个人自用。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.run_research import run_research  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/sample_mediacrawler.yaml")
    args = ap.parse_args()
    paths = run_research(args.config)
    sys.stdout.write("集成验收产出：\n")
    for name, p in paths.items():
        sys.stdout.write(f"  {name}: {p}\n")


if __name__ == "__main__":
    main()
