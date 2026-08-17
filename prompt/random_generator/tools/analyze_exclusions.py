#!/usr/bin/env python3
"""盘点知识库 v1 中被排除机制命中的行（排除项清单分析）。

输出：
- 每个排除模式命中的知识库行（tag/中文/CAT/命中模式），供人工分类排除项。
- 汇总各机制命中数、模式命中分布。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from prompt.random_generator import config, retrieval

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")


def load_rows() -> list[dict]:
    rows: list[dict] = []
    for f in sorted(KB.glob("tags_*.txt")):
        for idx, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            p = retrieval.parse_knowledge_v1_line(ln)
            if p:
                rows.append({"file": f.name, "line": idx, **p})
    return rows


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
    rows = load_rows()
    hits = [r for r in rows if hit_mechs(r)]
    print(f"知识库 v1 总行数: {len(rows)}，任一排除机制命中: {len(hits)}")

    combo = Counter(tuple(sorted(hit_mechs(r))) for r in hits)
    print("== 机制组合 ==")
    for k, v in combo.most_common():
        print(f"  {k}: {v}")

    cat_dist = Counter(r["category"] + "/" + r["subcategory"] for r in hits)
    print("== CAT 分布 top30 ==")
    for k, v in cat_dist.most_common(30):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
