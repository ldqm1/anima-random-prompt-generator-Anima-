#!/usr/bin/env python3
"""应用排除项人工分类映射到知识库 v1。

读取 classify_work/map_exclude_*.txt（文件短名|行号|判定）：
- 判定 = 排除/<子类>：把该行 CAT 改写为 排除/<子类>（config.EXCLUDED_CATEGORIES
  含「排除」，分类即排除，load 时整类丢弃）。
- 判定 = 保留：不改写（保留行已恢复原人工分类子类，不再被旧正则误杀）。

按 (文件, 行号) 精确回写，保留行其余部分与行尾换行符。
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")
WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")

LINE_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:)([^\]]+)(\]\s+.*)$")

EXCLUDE_PREFIX = "排除"
VALID_EXCLUDE_SUB = {
    "男性雄性", "兽化非人", "非人肤色", "性行为", "性器官", "性体液",
    "猎奇血腥", "质量词", "光影词", "媒体噪音", "审查类", "画师来源", "其他",
}


def load_maps() -> dict[tuple[str, int], str]:
    maps: dict[tuple[str, int], str] = {}
    for p in sorted(WORK.glob("map_exclude_*.txt")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "|" in ln:
                parts = ln.split("|")
                key = (parts[0], int(parts[1]))
                maps[key] = "|".join(parts[2:]).strip()
    return maps


def apply(maps: dict[tuple[str, int], str]) -> tuple[int, int, list[str]]:
    # 按文件分组
    by_file: dict[str, dict[int, str]] = {}
    for (fname, line_no), verdict in maps.items():
        by_file.setdefault(fname, {})[line_no] = verdict

    applied = 0
    kept = 0
    problems: list[str] = []
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
            verdict = file_maps[idx]
            m = LINE_RE.match(ln.strip())
            if not m:
                problems.append(f"{fname}:{idx} 行格式异常: {ln[:60]}")
                out.append(ln)
                continue
            cat = m.group(2)
            if verdict == "保留":
                kept += 1
                out.append(ln)
                continue
            if not verdict.startswith(EXCLUDE_PREFIX + "/"):
                problems.append(f"{fname}:{idx} 非法判定 {verdict}")
                out.append(ln)
                continue
            sub = verdict.split("/", 1)[1]
            if sub not in VALID_EXCLUDE_SUB:
                problems.append(f"{fname}:{idx} 非法排除子类 {sub}")
                out.append(ln)
                continue
            new_cat = f"{EXCLUDE_PREFIX}/{sub}"
            out.append(ln.replace(f"[CAT:{cat}]", f"[CAT:{new_cat}]", 1))
            applied += 1
        path.write_text("".join(out), encoding="utf-8")
    return applied, kept, problems


def main() -> int:
    maps = load_maps()
    n_ex, n_keep, problems = apply(maps)
    print(f"排除改写: {n_ex} 条, 保留恢复: {n_keep} 条")
    for p in problems[:30]:
        print("!!", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
