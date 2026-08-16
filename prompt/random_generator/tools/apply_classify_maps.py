#!/usr/bin/env python3
"""应用人工分类映射到知识库 v1。

读取 classify_work/map_*.txt（行号|子类），把：
- tags_表情动作.txt 的「其他表情」行 CAT 改为 表情动作/<表情子类>
- tags_表情动作.txt 的「其他动作」行 CAT 改为 表情动作/<动作子类>
- tags_场景.txt 的全部行 CAT 改为 场景/<场景子类>
未在映射中的行保持原样并报告（人工兜底检查）。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")

EXPR_CAT = "表情动作/其他表情"
ACTION_CAT = "表情动作/其他动作"
SCENE_PREFIX = "场景/"

# 表情/动作的"其他"子类分开命名，避免 CAT="表情动作/其他" 歧义：
# 表情杂项 -> 表情动作/其他表情（映射 expression_reaction）
# 动作杂项 -> 表情动作/其他动作（映射 pose_action_sex）
EXPR_OTHER = "其他表情"
ACTION_OTHER = "其他动作"

LINE_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:)([^\]]+)(\]\s+.*)$")

VALID_EXPR = {"微笑喜悦", "害羞脸红", "惊讶恐惧", "愤怒不满", "悲伤哭泣", "冷淡思考", "状态反应", EXPR_OTHER}
VALID_ACTION = {"静止姿态", "手势肢体", "动态动作", "人物交互", "职业活动", "性爱动作", ACTION_OTHER}
VALID_SCENE = {"自然户外", "城市街景", "室内家居", "公共设施", "奇幻幻想", "特殊场所", "交通载具", "其他"}


def load_maps() -> dict[str, dict[int, str]]:
    """返回 {文件前缀: {行号: 子类}}。"""
    maps: dict[str, dict[int, str]] = {"expr": {}, "action": {}, "scene": {}}
    for name in maps:
        for p in sorted(WORK.glob(f"map_{name}_*.txt")):
            for ln in p.read_text(encoding="utf-8").splitlines():
                if "|" in ln:
                    line_no, sub = ln.split("|", 1)
                    maps[name][int(line_no)] = sub.strip()
    return maps


def apply(file: str, maps: dict[int, str], cat_filter: str | None, valid: set[str]) -> tuple[int, list[str]]:
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
        tag = m.group(3).strip()
        if cat_filter == SCENE_PREFIX:
            target = maps.get(idx)
            if target is None:
                unmapped.append(f"{idx}|{tag}|{cat}")
                out.append(ln)
                continue
            if target not in valid:
                print(f"!! 非法场景子类 {target} @ {idx}|{tag}")
                target = "其他"
            new_cat = SCENE_PREFIX + target
            # 只替换 CAT 字段，保留行其余部分与行尾换行符
            out.append(ln.replace(f"[CAT:{cat}]", f"[CAT:{new_cat}]", 1))
            applied += 1
        elif cat == cat_filter:
            target = maps.get(idx)
            if target is None:
                unmapped.append(f"{idx}|{tag}|{cat}")
                out.append(ln)
                continue
            if target == "其他":
                # 区分表情/动作的杂项子类，避免 CAT 歧义
                target = EXPR_OTHER if cat_filter == EXPR_CAT else ACTION_OTHER
            if target not in valid:
                print(f"!! 非法子类 {target} @ {idx}|{tag}")
                target = "其他表情" if cat_filter == EXPR_CAT else "其他动作"
            new_cat = "表情动作/" + target
            out.append(ln.replace(f"[CAT:{cat}]", f"[CAT:{new_cat}]", 1))
            applied += 1
        else:
            out.append(ln)
    (KB / file).write_text("".join(out), encoding="utf-8")
    return applied, unmapped


maps = load_maps()
n_e, u_e = apply("tags_表情动作.txt", maps["expr"], EXPR_CAT, VALID_EXPR)
n_a, u_a = apply("tags_表情动作.txt", maps["action"], ACTION_CAT, VALID_ACTION)
n_s, u_s = apply("tags_场景.txt", maps["scene"], SCENE_PREFIX, VALID_SCENE)
print(f"其他表情: 应用 {n_e} 条, 未映射 {len(u_e)} 条")
print(f"其他动作: 应用 {n_a} 条, 未映射 {len(u_a)} 条")
print(f"场景: 应用 {n_s} 条, 未映射 {len(u_s)} 条")
for label, u in [("expr", u_e), ("action", u_a), ("scene", u_s)]:
    if u:
        print(f"--- {label} 未映射({len(u)}) ---")
        print("\n".join(u[:30]))
