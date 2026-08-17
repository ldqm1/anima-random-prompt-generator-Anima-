#!/usr/bin/env python3
"""汇总 r18 分类 subagent 的 6 个结果文件,校验全量覆盖并输出两档清单。

输入: classify_work/r18_classify_g{1..6}.json  {tag: "edge"|"explicit"}
辅助: classify_work/r18_inventory.json
输出:
  - r18_classify_summary.json  {tag: {档位, kb, cat, r15_visible, topic}}
  - stdout 统计
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORK = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\tools\classify_work")


def main() -> int:
    inv = json.loads((WORK / "r18_inventory.json").read_text(encoding="utf-8"))
    inv_by_tag = {r["tag"]: r for r in inv}

    merged: dict[str, str] = {}
    for g in range(1, 7):
        p = WORK / f"r18_classify_g{g}.json"
        if not p.exists():
            print(f"缺失: {p.name}", file=sys.stderr)
            return 1
        data = json.loads(p.read_text(encoding="utf-8"))
        for tag, tier in data.items():
            if tag not in inv_by_tag:
                print(f"!! {g} 中未知 tag: {tag}", file=sys.stderr)
                continue
            if tier not in ("edge", "explicit"):
                print(f"!! {g} 中非法档位: {tag} -> {tier!r}", file=sys.stderr)
                return 1
            if tag in merged and merged[tag] != tier:
                print(f"!! 冲突判定: {tag} -> {merged[tag]} vs {tier}", file=sys.stderr)
            merged[tag] = tier

    missing = [r["tag"] for r in inv if r["tag"] not in merged]
    if missing:
        print(f"!! 未判定 {len(missing)} 条: {missing[:30]}", file=sys.stderr)
        return 1

    summary = {
        tag: {**inv_by_tag[tag], "tier": tier}
        for tag, tier in merged.items()
    }
    (WORK / "r18_classify_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    n_edge = sum(1 for v in summary.values() if v["tier"] == "edge")
    n_exp = sum(1 for v in summary.values() if v["tier"] == "explicit")
    print(f"合计 {len(summary)} 条: 擦边(edge)={n_edge}  直接暴露(explicit)={n_exp}")
    # 擦边档里 r15 不可见的(需要 KB 改写)
    need_rewrite = [v for v in summary.values() if v["tier"] == "edge" and not v["r15_visible"]]
    print(f"擦边且 r15 不可见(需 KB 改写): {len(need_rewrite)}")
    from collections import Counter
    for k, c in Counter(v["cat"] for v in need_rewrite).most_common():
        print(f"    {k:24s} {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())