#!/usr/bin/env python3
"""导出待分类 tag 为分块文件（人工分类）。

从知识库 v1 提取指定类别的资源，每块 BLOCK_SIZE 条，写到 classify_work/。
格式：行号|tag|中文|原子分类
行号 = 原 txt 文件行号（用于回写）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")
WORK.mkdir(parents=True, exist_ok=True)

BLOCK_SIZE = 130
TAG_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:([^\]]+)\])\s+([^\s|]+)(?:\s*\|\s*(.*))?$")

# 用法: python export_blocks.py <输出前缀> <CAT 模式> [文件...]
#   CAT 模式: 前缀匹配（如 "人物/"）或精确集合（用 "精确:子类1,子类2" 前缀）
# 例: export_blocks.py appear "精确:头发发型,翅膀,眼睛" 知识库/v1/tags_人物.txt


def main() -> int:
    prefix = sys.argv[1]
    cat_arg = sys.argv[2]
    files = sys.argv[3:]

    exact_set = None
    if cat_arg.startswith("精确:"):
        exact_set = {s.strip() for s in cat_arg[3:].split(",")}
    prefix_set = None

    default_map = {
        "appearance": ["tags_人物.txt"],
        "clothing_state": ["tags_服饰.txt"],
        "detail_mood": ["tags_画面.txt"],
    }
    if not files:
        prefix_set = cat_arg
        files = [str(KB / f) for f in default_map.get(prefix, [])]

    items: list[tuple[int, str, str, str]] = []
    for fp in files:
        p = Path(fp)
        if not p.exists():
            print(f"!! 文件不存在: {p}")
            continue
        for idx, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            m = TAG_RE.match(ln.strip())
            if not m:
                continue
            cat = m.group(2)
            cat_short = cat.rsplit("/", 1)[-1]
            if exact_set is not None:
                # 支持短名（"头发发型"）或全名（"人物/头发发型"）
                if cat not in exact_set and cat_short not in exact_set:
                    continue
            elif prefix_set and not cat.startswith(prefix_set):
                continue
            items.append((idx, m.group(3), (m.group(4) or "").strip(), cat))

    total_blocks = 0
    for b, start in enumerate(range(0, len(items), BLOCK_SIZE), start=1):
        chunk = items[start:start + BLOCK_SIZE]
        out = WORK / f"{prefix}_{b}.txt"
        out.write_text(
            "\n".join(f"{idx}|{tag}|{cn}|{cat}" for idx, tag, cn, cat in chunk),
            encoding="utf-8",
        )
        total_blocks += 1
    print(f"{prefix}: {len(items)} 条 -> {total_blocks} 块 -> {WORK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
