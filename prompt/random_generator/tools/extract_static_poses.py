#!/usr/bin/env python3
"""从「基础动作」中提取明确的静止姿态词到「静止姿态」子类。

规则（保守）：
- 以 sitting/standing/lying/leaning/kneeling/crouching/squatting 开头
- 或 on_ 前缀（on_stool/on_ball/on_rock...，表示"处于某物上"的静止状态）
- 或明确的静态姿态词（head_down/head_tilt/head_on_knees/facing_up/facing_back/
  collapsed/dogeza/lounging/waiting/arms_at_sides/a-pose/contrapposto/head_turned/
  folded/knees_to_chest/clinging/no_hands）
其余留在「基础动作」。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
FILE = KB / "tags_表情动作.txt"

STATIC_PREFIX = (
    "sitting", "standing", "lying", "leaning", "kneeling", "crouching", "squatting",
    "on_",
)
STATIC_EXACT = {
    "head_down", "head_tilt", "head_on_knees", "facing_up", "facing_back",
    "collapsed", "dogeza", "lounging", "waiting", "arms_at_sides", "a-pose",
    "contrapposto", "head_turned", "folded", "knees_to_chest", "clinging",
    "no_hands", "head_on_table", "head_on_arm", "buried", "posed", "poses",
    "crossed_arms", "arm_above_head", "hands_together", "hands_on_hips",
    "hands_on_own_chest", "hands_on_own_thighs", "hands_on_own_knees",
    "hand_on_own_hip", "arm_behind_back", "arms_behind_back", "bent_over",
    "bending_backward", "leaning_back", "leaning_forward", "leaning_to_the_side",
    "sitting_on_roof", "sitting_on_desk", "sitting_on_ball", "sitting_on_stool",
    "sitting_on_bench", "sitting_on_floor", "sitting_on_ground",
}

moved = 0
kept = 0
lines = FILE.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
for ln in lines:
    m = re.match(r"^(\[DOMAIN:标签\] \[CAT:表情动作/基础动作\])\s+([^\s|]+)", ln.strip())
    if not m:
        out.append(ln)
        continue
    tag = m.group(2).lower()
    is_static = tag.startswith(STATIC_PREFIX) or tag in STATIC_EXACT
    if is_static:
        out.append(ln.replace("[CAT:表情动作/基础动作]", "[CAT:表情动作/静止姿态]", 1))
        moved += 1
    else:
        kept += 1
        out.append(ln)
FILE.write_text("".join(out), encoding="utf-8")
print(f"提取到静止姿态: {moved} 条; 留在基础动作: {kept} 条")

# 验证
from collections import Counter
cats = Counter()
for ln in FILE.read_text(encoding="utf-8").splitlines():
    m = re.match(r"\[DOMAIN:标签\] \[CAT:(表情动作/[^\]]+)\]", ln)
    if m:
        cats[m.group(1)] += 1
for k in sorted(cats):
    print(f"  {cats[k]:>6}  {k}")
