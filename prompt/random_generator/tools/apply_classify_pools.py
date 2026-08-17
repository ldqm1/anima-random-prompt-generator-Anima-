#!/usr/bin/env python3
"""应用人工分类映射到知识库 v1（外貌/画面/服饰 三池）。

读取 classify_work/map_<pool>_*.txt（行号|子类），把知识库对应文件行号
的 CAT 字段改写为 <分类>/<子类>。未在映射中的行保持原样（不属本批范围）。
按行号精确回写，保留行其余部分与行尾换行符。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")

LINE_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:)([^\]]+)(\]\s+.*)$")

# pool -> (知识库文件名, 分类前缀, 合法子类集合)
POOLS: dict[str, tuple[str, str, set[str]]] = {
    "appear": (
        "tags_人物.txt",
        "人物",
        {
            "发色", "发型", "眼睛", "身材体态", "胸部", "皮肤肤色", "肢体",
            "面部细节", "非人特征", "身体标记", "体型年龄", "身体状态", "其他",
        },
    ),
    "detail": (
        "tags_画面.txt",
        "画面",
        {"画风画派", "颜色风格", "质感特效", "氛围光影", "构图氛围", "元数据"},
    ),
    "clothing": (
        "tags_服饰.txt",
        "服饰",
        {
            "日常便服", "制服校服", "泳装内衣", "和风民族", "洋装礼服", "外套大衣",
            "运动休闲", "军装战斗", "鞋袜", "头饰", "配饰", "其他",
        },
    ),
}


def load_maps(pool: str) -> dict[int, str]:
    maps: dict[int, str] = {}
    for p in sorted(WORK.glob(f"map_{pool}_*.txt")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "|" in ln:
                line_no, sub = ln.split("|", 1)
                maps[int(line_no)] = sub.strip()
    return maps


def apply(file: str, prefix: str, maps: dict[int, str], valid: set[str]) -> tuple[int, list[str]]:
    lines = (KB / file).read_text(encoding="utf-8").splitlines(keepends=True)
    applied = 0
    unmapped: list[str] = []
    out: list[str] = []
    for idx, ln in enumerate(lines, start=1):
        m = LINE_RE.match(ln.strip())
        if not m:
            out.append(ln)
            continue
        cat = m.group(2)
        if idx not in maps:
            out.append(ln)
            continue
        target = maps[idx]
        if target not in valid:
            print(f"!! 非法子类 {target} @ {idx}|{cat}")
            target = "其他"
        new_cat = f"{prefix}/{target}"
        out.append(ln.replace(f"[CAT:{cat}]", f"[CAT:{new_cat}]", 1))
        applied += 1
    (KB / file).write_text("".join(out), encoding="utf-8")
    return applied, unmapped


for pool, (file, prefix, valid) in POOLS.items():
    maps = load_maps(pool)
    n, u = apply(file, prefix, maps, valid)
    print(f"{pool}: 应用 {n} 条, 未映射 {len(u)} 条")
    for x in u[:20]:
        print("  ", x)
