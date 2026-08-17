#!/usr/bin/env python3
"""导出"未细粒度分类"的知识库 v1 行为分块文件（人工分类用）。

判定口径：行号不在 classify_work 任何 map_*.txt（appear/detail/clothing/
expr/action/scene/exclude）覆盖范围内，且不属结构性管理子类（性器官/
身份职业/成人玩具/性爱动作/元数据/颜文字）→ 视为"未细粒度分类"。

按池导出（每池独立前缀，BLOCK_SIZE=130）：
  shot: 镜头/*            -> camera_shot 池
  env:  环境/*            -> scene_environment 池
  bkg:  画面/背景          -> scene_environment 池
  face: 人物/面部+嘴巴 + 表情动作/笑哭生气不开心蔑视 -> expression_reaction 池
  pose: 表情动作/手部动作+手部拿着某物+基础动作+手放在某地+腿部动作+静止姿态+手抓着某物 -> pose_action_sex 池
  item: 物品/*            -> scene_environment 池

格式：文件短名|行号|tag|中文|CAT（行号=知识库原 txt 行号，用于回写）。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from prompt.random_generator import retrieval

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")
WORK.mkdir(parents=True, exist_ok=True)

BLOCK_SIZE = 130

# 已有人工分类映射族 -> 对应 KB 文件（旧格式：行号|子类）
_MAP_FAMILIES = {
    "tags_人物.txt": ("map_appear_*.txt",),
    "tags_画面.txt": ("map_detail_*.txt",),
    "tags_服饰.txt": ("map_clothing_*.txt",),
    "tags_表情动作.txt": ("map_expr_*.txt", "map_action_*.txt"),
    "tags_场景.txt": ("map_scene_*.txt",),
}
_STRUCTURAL = {
    ("物品", "成人玩具"), ("人物", "性器官"), ("表情动作", "颜文字"),
    ("人物", "身份（职业）"), ("表情动作", "性爱动作"), ("画面", "元数据"),
}

# 池定义：前缀 -> (池名, (category, subcategory) 精确集合 或 category 前缀)
POOLS: dict[str, tuple[str, dict]] = {
    "shot": ("camera_shot", {("镜头", "*")}),
    "env": ("scene_environment", {("环境", "*")}),
    "bkg": ("scene_environment", {("画面", "背景")}),
    "face": ("expression_reaction", {
        ("人物", "面部"), ("人物", "嘴巴"),
        ("表情动作", "笑"), ("表情动作", "哭"), ("表情动作", "生气"),
        ("表情动作", "不开心"), ("表情动作", "蔑视"),
    }),
    "pose": ("pose_action_sex", {
        ("表情动作", "手部动作"), ("表情动作", "手部拿着某物"),
        ("表情动作", "基础动作"), ("表情动作", "手放在某地"),
        ("表情动作", "腿部动作"), ("表情动作", "静止姿态"),
        ("表情动作", "手抓着某物"), ("表情动作", "其他动作"),
    }),
    "item": ("scene_environment", {("物品", "*")}),
}


def load_covered() -> dict[str, set[int]]:
    covered: dict[str, set[int]] = defaultdict(set)
    # 新格式 map（文件短名|行号|目标CAT，如 map_shot/map_bkg/map_env/map_face/map_pose/map_item）
    for fam in ("map_shot_*.txt", "map_bkg_*.txt", "map_env_*.txt",
                "map_face_*.txt", "map_pose_*.txt", "map_item_*.txt"):
        for p in sorted(WORK.glob(fam)):
            for ln in p.read_text(encoding="utf-8").splitlines():
                parts = ln.split("|")
                if len(parts) >= 2:
                    covered[parts[0]].add(int(parts[1]))
    # 旧格式 map（行号|子类，如 map_appear/map_detail/map_clothing/map_expr/map_action/map_scene）
    for fname, fams in _MAP_FAMILIES.items():
        for fam in fams:
            for p in sorted(WORK.glob(fam)):
                for ln in p.read_text(encoding="utf-8").splitlines():
                    if "|" in ln:
                        covered[fname].add(int(ln.split("|", 1)[0]))
    for p in sorted(WORK.glob("map_exclude_*.txt")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            parts = ln.split("|")
            covered[parts[0]].add(int(parts[1]))
    return covered


def main() -> int:
    covered = load_covered()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for prefix, (pool, spec) in POOLS.items():
        if only and prefix != only:
            continue
        items: list[tuple[str, int, str, str, str]] = []
        for f in sorted(KB.glob("tags_*.txt")):
            fname = f.name
            if fname == "tags_二次元角色.txt":
                continue
            for idx, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
                p = retrieval.parse_knowledge_v1_line(ln)
                if not p:
                    continue
                cat, sub = p["category"], p["subcategory"]
                # 命中判定
                hit = False
                for spec_cat, spec_sub in spec:
                    if spec_sub == "*" and cat == spec_cat:
                        hit = True
                        break
                    if cat == spec_cat and sub == spec_sub:
                        hit = True
                        break
                if not hit:
                    continue
                if (cat, sub) in _STRUCTURAL:
                    continue
                if idx in covered.get(fname, set()):
                    continue
                items.append((fname, idx, p["tag"], p["chinese"] or "", f"{cat}/{sub}"))
        if not items:
            print(f"{prefix}: 无待分类行")
            continue
        total_blocks = 0
        for b, start in enumerate(range(0, len(items), BLOCK_SIZE), start=1):
            chunk = items[start:start + BLOCK_SIZE]
            out = WORK / f"{prefix}_{b}.txt"
            out.write_text(
                "\n".join(f"{fn}|{ix}|{tag}|{cn}|{cat}" for fn, ix, tag, cn, cat in chunk),
                encoding="utf-8",
            )
            total_blocks += 1
        print(f"{prefix} [{pool}]: {len(items)} 条 -> {total_blocks} 块")
    return 0


if __name__ == "__main__":
    sys.exit(main())