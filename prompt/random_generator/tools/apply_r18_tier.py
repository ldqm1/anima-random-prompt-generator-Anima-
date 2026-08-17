#!/usr/bin/env python3
"""应用 r18 两档分类结果:
1. 擦边档(edge):curated_tags.yaml 评级 r18 -> r15。
2. 擦边档且 r15 不可见:KB 行 CAT 改写为保留子类(性爱动作->表情动作/擦边,
   排除/性行为->按文件语义 表情动作/擦边 或 物品/擦边;人物/其他->人物/擦边),
   使其在 r15 低配额可见。
3. 直接暴露档(explicit):维持现状(r18 评级或排除类)。
读取 classify_work/r18_classify_summary.json,输出改写映射并落盘分类清单。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(r"E:\code\Anima\anima-rag-knowledge-release")
KB = ROOT / "知识库" / "v1"
WORK = ROOT / "prompt" / "random_generator" / "tools" / "classify_work"
CURATED = ROOT / "prompt" / "random_generator" / "curated_tags.yaml"

# 改写目标: 原CAT -> 新CAT(按 tag 语义划分)
def rewrite_target(cat: str, kb_file: str, tag: str) -> str | None:
    if cat == "表情动作/性爱动作":
        return "表情动作/擦边"
    if cat == "排除/性行为":
        return "物品/擦边" if kb_file.startswith("tags_物品") else "表情动作/擦边"
    if cat == "人物/其他":
        return "人物/擦边"
    if cat == "人物/对象":
        return "人物/擦边"
    return None


# 不上浮的 edge(语义仍为硬排除): 血腥/噪音/其他排除类; 触手系(用户上轮明确"触手性=直接暴露");
# bisected(躯体分割=猎奇)单独改写为 排除/猎奇血腥, 不降级。
def should_skip(tag: str, cat: str) -> bool:
    if cat.startswith("排除/") and cat != "排除/性行为":
        return True
    if cat == "排除/性行为" and "tentacle" in tag:
        return True
    if tag == "bisected":
        return True
    return False


def main() -> int:
    summary = json.loads((WORK / "r18_classify_summary.json").read_text(encoding="utf-8"))
    edges = [v for v in summary.values() if v["tier"] == "edge"]

    # ---- 1) 收集需降级 tag(跳过不上浮的) ----
    downgrade = sorted(v["tag"] for v in edges if not should_skip(v["tag"], v["cat"]))
    skipped = [v for v in edges if should_skip(v["tag"], v["cat"])]
    print(f"擦边档共 {len(edges)} 条; 跳过不上浮 {len(skipped)} 条 -> 降级 {len(downgrade)} 条")
    print("  跳过:", ", ".join(v["tag"] for v in skipped))

    # ---- 2) curated_tags.yaml 字符串级降级(按归一化 tag 匹配, 兼容连字符/下划线原文) ----
    text = CURATED.read_text(encoding="utf-8")
    downgrade_set = set(downgrade)

    def _norm(t: str) -> str:
        return t.strip().lower().replace("_", " ").replace("-", " ")

    # 先扫描原文 r18 条目, 确认每个降级目标都能定位
    tag_rating_re = re.compile(r"(?m)^- tag: (.+)\n  rating: r18\n")
    orig_r18 = {_norm(m.group(1)) for m in tag_rating_re.finditer(text)}
    miss = [t for t in downgrade if _norm(t) not in orig_r18]
    if miss:
        print("  无法定位(不会降级):", miss[:20])

    replaced = 0
    def repl(m: re.Match) -> str:
        nonlocal replaced
        if _norm(m.group(1)) in downgrade_set:
            replaced += 1
            return m.group(0).replace("rating: r18", "rating: r15")
        return m.group(0)
    text = tag_rating_re.sub(repl, text)
    print(f"curated 降级 {replaced} 处 (期望 {len(downgrade)} tag)")

    # ---- 3) KB 改写映射(擦边且 r15 不可见, 未跳过) ----
    rewrites: dict[tuple[str, int], str] = {}
    extra_explicit_rewrites: dict[tuple[str, int], str] = {}
    for v in edges:
        if should_skip(v["tag"], v["cat"]) or not v["kb"]:
            continue
        kb_file, line_no = v["kb"].split("|")
        target = rewrite_target(v["cat"], kb_file, v["tag"])
        if target and not v["r15_visible"]:
            rewrites[(kb_file, int(line_no))] = target
        elif target is None and not v["r15_visible"]:
            print(f"  !! 无法改写: {v['tag']} @ {v['cat']}")
    # 特例: bisected 躯体分割(猎奇)移入排除/猎奇血腥, 维持 r18 评级(仅 r18 但猎奇应全模式排除)
    for v in summary.values():
        if v["cat"] == "画面/元数据" and v["tag"] == "bisected" and v["kb"]:
            kb_file, line_no = v["kb"].split("|")
            extra_explicit_rewrites[(kb_file, int(line_no))] = "排除/猎奇血腥"
    print(f"KB 改写映射 {len(rewrites)} 条; 特判(排除/猎奇血腥) {len(extra_explicit_rewrites)} 条")
    cnt = Counter(rewrites.values())
    for k, c in cnt.most_common():
        print(f"    -> {k}: {c}")

    # ---- 4) 落盘 ----
    CURATED.write_text(text, encoding="utf-8")
    print(f"curated_tags.yaml 已写回 (共 {len(text.splitlines())} 行)")
    if rewrites:
        prefix_of: dict[str, str] = {
            "表情动作": "pose", "物品": "item", "人物": "face",
        }
        by_prefix: dict[str, list[str]] = {}
        for (f, ln), t in rewrites.items():
            pf = prefix_of.get(t.split("/")[0], "pose")
            by_prefix.setdefault(pf, []).append(f"{f}|{ln}|{t}")
        for pf, lines in sorted(by_prefix.items()):
            (WORK / f"map_{pf}_r18_edge.txt").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
            print(f"  落盘 map_{pf}_r18_edge.txt: {len(lines)} 条")
    (WORK / "r18_edge_tags.txt").write_text("\n".join(downgrade) + "\n", encoding="utf-8")
    (WORK / "r18_explicit_tags.txt").write_text(
        "\n".join(sorted(v["tag"] for v in summary.values() if v["tier"] == "explicit")) + "\n",
        encoding="utf-8")

    if miss:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())