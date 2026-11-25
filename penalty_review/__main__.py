"""命令行入口：python3 -m penalty_review

读取项目语料，走一遍复议流程，打印双语恢复通报。
"""
from __future__ import annotations

import json
from pathlib import Path

from .pipeline import run_pipeline


def _load():
    try:
        from materials import load_corpus
        return load_corpus()
    except ImportError:
        path = Path(__file__).resolve().parent.parent / "data" / "corpus.json"
        return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    result = run_pipeline(_load())
    print(result.bulletin.render())


if __name__ == "__main__":
    main()
