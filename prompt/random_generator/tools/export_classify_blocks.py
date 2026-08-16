#!/usr/bin/env python3
"""导出待分类 tag 为分块文件（人工分类工作目录）。

从知识库 v1 提取三类待分类 tag，每块约 BLOCK_SIZE 条，
写入 classify_work/ 下的分块文件，格式：
    行号|tag|中文|原子类
行号 = 原 txt 文件中的行号（用于回写）。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")
WORK.mkdir(parents=True, exist_ok=True)

BLOCK_SIZE = 130
TAG_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:([^\]]+)\])\s+([^\s|]+)(?:\s*\|\s*(.*))?$")


def extract(file: str, cat_prefix: str) -> list[tuple[int, str, str, str]]:
    """返回 [(行号, tag, 中文, cat)]。"""
    out = []
    for idx, ln in enumerate(
        (KB / file).read_text(encoding="utf-8").splitlines(), start=1
    ):
        m = TAG_RE.match(ln.strip())
        if not m:
            continue
        cat = m.group(2)
        if cat.startswith(cat_prefix):
            out.append((idx, m.group(3), (m.group(4) or "").strip(), cat))
    return out


def write_blocks(name: str, items: list[tuple[int, str, str, str]]) -> int:
    total = 0
    for b, start in enumerate(range(0, len(items), BLOCK_SIZE), start=1):
        chunk = items[start:start + BLOCK_SIZE]
        path = WORK / f"{name}_{b}.txt"
        lines = [f"{idx}|{tag}|{cn}|{cat}" for idx, tag, cn, cat in chunk]
        path.write_text("\n".join(lines), encoding="utf-8")
        total += 1
    return total


expr = extract("tags_表情动作.txt", "表情动作/其他表情")
action = extract("tags_表情动作.txt", "表情动作/其他动作")
scene = extract("tags_场景.txt", "场景/")

ne = write_blocks("expr", expr)
na = write_blocks("action", action)
ns = write_blocks("scene", scene)

print(f"其他表情 {len(expr)} 条 -> {ne} 块")
print(f"其他动作 {len(action)} 条 -> {na} 块")
print(f"场景 {len(scene)} 条 -> {ns} 块")
print(f"共 {len(expr) + len(action) + len(scene)} 条, {ne + na + ns} 块")
print("工作目录:", WORK)
