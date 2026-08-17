#!/usr/bin/env python3
"""应用"未细粒度分类"补判映射到知识库 v1。

读取 classify_work/map_<前缀>_*.txt，格式：文件短名|行号|目标CAT
（目标CAT 如 镜头/特写镜头 或 物品/动物；行号为知识库原 txt 行号）。
把该行 CAT 改写为目标 CAT。按 (文件, 行号) 精确回写，保留行其余部分与行尾。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")

LINE_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:)([^\]]+)(\]\s+.*)$")

# 池前缀 -> 允许的目标 CAT 集合（用于校验）
VALID_TARGETS: dict[str, set[str]] = {
    "shot": {f"镜头/{s}" for s in {
        "人物构图", "人物视觉朝向", "其他沟通", "效果", "构图法则", "特写镜头", "镜头角度",
    }},
    "bkg": {f"画面/{s}" for s in {
        "简单模糊背景", "纯色背景", "渐变多彩背景", "图案背景", "主题元素背景",
        "实景背景", "特效氛围背景",
    }},
    "env": {f"环境/{s}" for s in {
        "大自然", "天空", "天气", "水", "氛围", "季节", "云",
    }},
    "face": {f"表情动作/{s}" for s in {
        "微笑喜悦", "害羞脸红", "惊讶恐惧", "愤怒不满", "悲伤哭泣", "冷淡思考",
        "状态反应", "其他表情", "笑", "哭", "生气", "不开心", "蔑视", "其他",
    }} | {f"人物/{s}" for s in {
        "面部细节", "嘴巴", "面部", "眼睛", "非人特征", "身体标记", "身体状态",
        "皮肤肤色", "发色", "发型", "肢体", "胸部", "身材体态", "体型年龄", "其他",
    }} | {f"排除/{s}" for s in {"男性雄性", "兽化非人", "性行为", "猎奇血腥", "其他"}},
    "pose": {f"表情动作/{s}" for s in {
        "手部动作", "手部拿着某物", "基础动作", "手放在某地", "腿部动作", "静止姿态",
        "手抓着某物", "手势肢体", "动态动作", "人物交互", "职业活动", "其他动作", "其他",
    }} | {f"排除/{s}" for s in {"男性雄性", "兽化非人", "性行为", "猎奇血腥", "其他"}},
    "item": {f"物品/{s}" for s in {
        "其他物品", "食物", "动物", "武器", "数码设备", "植物", "乐器", "餐具",
        "学习用品", "家具", "箱包容器", "玩具玩偶", "工具机械", "装饰摆件", "运动器材",
        "医疗用品", "卫生用品", "布料织品", "其他",
    }},
}


def load_maps(prefix: str) -> dict[tuple[str, int], str]:
    maps: dict[tuple[str, int], str] = {}
    for p in sorted(WORK.glob(f"map_{prefix}_*.txt")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "|" in ln:
                parts = ln.split("|")
                maps[(parts[0], int(parts[1]))] = "|".join(parts[2:]).strip()
    return maps


def apply(prefix: str, maps: dict[tuple[str, int], str]) -> tuple[int, list[str]]:
    by_file: dict[str, dict[int, str]] = {}
    for (fname, line_no), target in maps.items():
        by_file.setdefault(fname, {})[line_no] = target
    applied = 0
    problems: list[str] = []
    valid = VALID_TARGETS.get(prefix, set())
    for fname, file_maps in by_file.items():
        path = KB / fname
        if not path.exists():
            problems.append(f"文件不存在: {fname}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        out: list[str] = []
        for idx, ln in enumerate(lines, start=1):
            if idx not in file_maps:
                out.append(ln)
                continue
            target = file_maps[idx]
            m = LINE_RE.match(ln.strip())
            if not m:
                problems.append(f"{fname}:{idx} 行格式异常")
                out.append(ln)
                continue
            if target not in valid:
                problems.append(f"{fname}:{idx} 目标不在 {prefix} 合法集合: {target}")
                out.append(ln)
                continue
            out.append(ln.replace(f"[CAT:{m.group(2)}]", f"[CAT:{target}]", 1))
            applied += 1
        path.write_text("".join(out), encoding="utf-8")
    return applied, problems


def main() -> int:
    import sys
    prefixes = sys.argv[1:] or sorted(VALID_TARGETS)
    for prefix in prefixes:
        maps = load_maps(prefix)
        if not maps:
            print(f"{prefix}: 无映射文件，跳过")
            continue
        n, problems = apply(prefix, maps)
        print(f"{prefix}: 应用 {n} 条")
        for p in problems[:30]:
            print("  !!", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())