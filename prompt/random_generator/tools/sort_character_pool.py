"""角色池 IP 去重与排序工具。

按规范化后的 ``series_tag`` 合并重复 IP，保留角色数最多的拼写作为主条目，
合并开关、权重与角色列表，最后按 ``enabled`` 降序、``character_count`` 降序输出。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from prompt.random_generator import config
from prompt.random_generator.tools.build_character_pool import (
    _normalize_tag,
    save_character_pool,
    save_series_index,
)

POOL_FILE: Path = config.CHARACTER_POOL_FILE
INDEX_FILE: Path = config.CHARACTER_POOL_SERIES_INDEX_FILE


def _norm_series_tag(tag: str) -> str:
    """规范化 series_tag：小写、去首尾空白、下划线改空格。"""
    return tag.strip().lower().replace("_", " ")


def _choose_canonical(entries: list[dict]) -> dict:
    """在重复 IP 中选择角色数最多的条目作为规范条目。"""
    return max(entries, key=lambda e: e.get("character_count", 0))


def main() -> int:
    print(f"加载角色池: {POOL_FILE}")
    pool: list[dict] = json.loads(POOL_FILE.read_text(encoding="utf-8"))

    print(f"加载索引: {INDEX_FILE}")
    index: list[dict] = json.loads(INDEX_FILE.read_text(encoding="utf-8"))

    # 按规范化 series_tag 分组索引条目。
    index_groups: dict[str, list[dict]] = defaultdict(list)
    for entry in index:
        index_groups[_norm_series_tag(entry["series_tag"])].append(entry)

    # 按规范化 series_tag 分组角色。
    role_groups: dict[str, list[dict]] = defaultdict(list)
    for role in pool:
        role_groups[_norm_series_tag(role["series_tag"])].append(role)

    merged_index: list[dict] = []
    merged_pool: list[dict] = []
    duplicate_report: list[dict] = []

    for norm_tag, entries in index_groups.items():
        canonical = _choose_canonical(entries)
        canonical_tag = canonical["series_tag"]
        canonical_name = canonical.get("series_name_cn", "")

        # 合并开关：任意一个开启则开启。
        enabled = any(bool(e.get("enabled", False)) for e in entries)
        # 合并男性过滤：任意一个允许则允许（更宽松）。
        allow_male = any(bool(e.get("allow_male", True)) for e in entries)
        # 合并权重：取已开启条目中的最大权重。重复 IP 通常来自同一作品的不同拼写，
        # 求和会导致权重被意外放大，取最大值更符合“同一 IP 只保留一份配置”的直觉。
        enabled_weights = [
            int(e.get("weight", config.DEFAULT_CHARACTER_POOL_WEIGHT))
            for e in entries
            if e.get("enabled", False)
        ]
        weight = max(enabled_weights) if enabled_weights else config.DEFAULT_CHARACTER_POOL_WEIGHT

        # 合并角色并去重（以规范化 character_tag 为准）。
        roles = role_groups.get(norm_tag, [])
        seen: set[str] = set()
        deduped_roles: list[dict] = []

        # 优先保留规范条目下的角色。
        for role in roles:
            if role["series_tag"] != canonical_tag:
                continue
            norm_char = _normalize_tag(role.get("character_tag", ""))
            if norm_char and norm_char not in seen:
                seen.add(norm_char)
                deduped_roles.append(role)

        # 再补充其他拼写变体中的新角色，并将其归属到规范 IP。
        for role in roles:
            if role["series_tag"] == canonical_tag:
                continue
            norm_char = _normalize_tag(role.get("character_tag", ""))
            if norm_char and norm_char not in seen:
                seen.add(norm_char)
                role["series_tag"] = canonical_tag
                role["series_name_cn"] = canonical_name
                deduped_roles.append(role)

        merged_entry = {
            "series_tag": canonical_tag,
            "series_name_cn": canonical_name,
            "enabled": enabled,
            "allow_male": allow_male,
            "weight": weight,
            "character_count": len(deduped_roles),
            "migrated_from": canonical.get("migrated_from"),
        }
        merged_index.append(merged_entry)
        merged_pool.extend(deduped_roles)

        if len(entries) > 1:
            duplicate_report.append(
                {
                    "canonical": canonical_tag,
                    "merged_character_count": len(deduped_roles),
                    "enabled": enabled,
                    "weight": weight,
                    "sources": [
                        {
                            "series_tag": e["series_tag"],
                            "series_name_cn": e.get("series_name_cn", ""),
                            "character_count": e.get("character_count", 0),
                            "enabled": bool(e.get("enabled", False)),
                            "weight": int(e.get("weight", config.DEFAULT_CHARACTER_POOL_WEIGHT)),
                        }
                        for e in entries
                    ],
                }
            )

    # 排序：开启项在前，同状态下按角色数降序。
    merged_index.sort(key=lambda item: (-int(item["enabled"]), -item["character_count"]))

    save_character_pool(merged_pool, POOL_FILE)
    save_series_index(merged_index, INDEX_FILE)

    print(f"\n去重前: {len(pool)} 角色 / {len(index)} IP")
    print(f"去重后: {len(merged_pool)} 角色 / {len(merged_index)} IP")
    print(f"合并重复 IP 组: {len(duplicate_report)}")

    if duplicate_report:
        duplicate_report.sort(key=lambda d: -d["merged_character_count"])
        print("\n主要重复 IP（按合并后角色数降序）:")
        for d in duplicate_report[:20]:
            srcs = ", ".join(
                f"{s['series_tag']}({s['character_count']})" for s in d["sources"]
            )
            print(f"  {d['canonical']}: {d['merged_character_count']} 角色 <- {srcs}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
