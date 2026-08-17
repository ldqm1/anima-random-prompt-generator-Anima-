#!/usr/bin/env python3
"""导出待人工分类的排除项为分块文件。

范围：知识库 v1 中被排除机制（EXACT/REGEX/MALE/NONHUMAN/SEMANTIC/NOISE）
命中的行，减去：
- 二次元角色/*（用户确认角色不分类）
- 已结构性排除的行（分类/配额已驱动，不属正则误判区）：
  - 人物/性器官、人物/身份（职业）、物品/成人玩具（EXCLUDED_SUBCATEGORIES）
  - 表情动作/性爱动作（subcategory_quotas max:0）
  - 画面/元数据（subcategory_quotas max:0）

格式：文件短名|行号|tag|中文|CAT|命中机制（逗号分隔）
行号 = 知识库原 txt 行号（用于回写）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from prompt.random_generator import config, retrieval

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")
WORK.mkdir(parents=True, exist_ok=True)

BLOCK_SIZE = 130

# 已结构性排除（无需人工判定）：(category, subcategory)
STRUCTURALLY_EXCLUDED: set[tuple[str, str]] = {
    ("人物", "性器官"),
    ("人物", "身份（职业）"),
    ("物品", "成人玩具"),
    ("表情动作", "性爱动作"),
    ("画面", "元数据"),
}


def hit_mechs(r: dict) -> list[str]:
    norm = retrieval._normalize_tag(r["tag"])
    m: list[str] = []
    if norm in config.EXACT_EXCLUDE_TAGS:
        m.append("EXACT")
    for p in retrieval._COMPILED_EXCLUDE_PATTERNS:
        if p.search(norm):
            m.append("REGEX")
            break
    if config.is_noise_meta_tag(norm):
        m.append("NOISE")
    if not retrieval._is_female_only_tag(norm):
        m.append("MALE")
    if not retrieval._is_human_like_tag(norm):
        m.append("NONHUMAN")
    if retrieval._is_semantically_excluded(r["tag"], "r15"):
        m.append("SEMANTIC")
    return m


def main() -> int:
    items: list[tuple[str, int, str, str, str, str]] = []
    for f in sorted(KB.glob("tags_*.txt")):
        if f.name == "tags_二次元角色.txt":
            continue  # 角色不分类
        for idx, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            p = retrieval.parse_knowledge_v1_line(ln)
            if not p:
                continue
            if (p["category"], p["subcategory"]) in STRUCTURALLY_EXCLUDED:
                continue
            mechs = hit_mechs(p)
            if not mechs:
                continue
            items.append(
                (f.name, idx, p["tag"], p["chinese"], f'{p["category"]}/{p["subcategory"]}', ",".join(mechs))
            )

    print(f"待分类排除项: {len(items)} 条")
    for b, start in enumerate(range(0, len(items), BLOCK_SIZE), start=1):
        chunk = items[start:start + BLOCK_SIZE]
        out = WORK / f"exclude_{b}.txt"
        out.write_text(
            "\n".join(f"{fname}|{ln}|{tag}|{cn}|{cat}|{mech}" for fname, ln, tag, cn, cat, mech in chunk),
            encoding="utf-8",
        )
    print(f"导出到 {WORK}/exclude_*.txt, 共 {(len(items) + BLOCK_SIZE - 1)//BLOCK_SIZE} 块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
