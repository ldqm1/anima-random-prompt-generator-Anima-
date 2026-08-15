"""抽样结果组装、冲突消解与提交给 DeepSeek 前的预处理。"""

from __future__ import annotations

from typing import Any

from . import config


def _normalize_tag(tag: str) -> str:
    """统一 tag 的空白/下划线格式，用于比较。"""
    return tag.strip().replace("_", " ").lower()


#: 从 ``Anima_prompt_template.md`` §3.1 编码得到的互斥规则表。
#:
#: 每条规则包含：
#: - ``type``: 冲突类别（``view`` / ``identity`` / ``clothing`` / ``action`` / ``detail``）。
#: - ``tags``: 参与互斥的 tag 列表；对于 ``clothing`` 中的 ``completely nude`` 规则，
#:   该列表仅含触发 tag，实际作用范围由 ``category_to_drop`` 指定。
#: - ``reason``: 冲突原因。
#: - ``strategy``: 消解策略（``drop_all_but_one`` / ``drop_b`` / ``rewrite``）。
#: - ``category_to_drop`` / ``max_keep``: 可选的额外控制字段。
CONFLICT_RULES: list[dict[str, Any]] = [
    # ---------- view（视角） ----------
    {
        "type": "view",
        "tags": ["from front", "from behind"],
        "reason": "物理矛盾",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "view",
        "tags": ["from above", "from below"],
        "reason": "物理矛盾",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "view",
        "tags": ["looking at viewer", "facing away"],
        "reason": "视线矛盾",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "view",
        "tags": ["pov", "full body"],
        "reason": "POV 不可能看到自己全身",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "view",
        "tags": ["close-up", "full body"],
        "reason": "景别矛盾",
        "strategy": "drop_all_but_one",
    },
    # ---------- identity（身份） ----------
    {
        "type": "identity",
        "tags": ["solo", "hetero", "1boy", "yuri"],
        "reason": "单人不存在互动",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "identity",
        "tags": ["femdom", "male-on-female rape"],
        "reason": "逻辑矛盾（主导方冲突）",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "identity",
        "tags": ["sleeping", "unconscious", "looking at viewer"],
        "reason": "无意识不可能直视",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "identity",
        "tags": ["blindfold", "heart-shaped pupils", "rolling eyes"],
        "reason": "看不到眼睛",
        "strategy": "drop_all_but_one",
    },
    # ---------- clothing（服装） ----------
    {
        "type": "clothing",
        "tags": ["completely nude"],
        "reason": "全裸不穿衣",
        "strategy": "drop_b",
        "category_to_drop": "clothing_state",
    },
    {
        "type": "clothing",
        "tags": ["pantyhose", "barefoot"],
        "reason": "穿了丝袜不可能光脚（除非 torn pantyhose）",
        "strategy": "drop_b",
    },
    {
        "type": "clothing",
        "tags": ["blindfold", "glasses"],
        "reason": "物理冲突",
        "strategy": "drop_b",
    },
    {
        "type": "clothing",
        "tags": [
            "cat lingerie",
            "lace lingerie",
            "babydoll",
            "negligee",
            "chemise",
            "no panties",
            "bottomless",
        ],
        "reason": "内衣套装隐含包含内裤，模型优先解析套装忽略暴露标签",
        "strategy": "drop_b",
    },
    # ---------- action（动作） ----------
    {
        "type": "action",
        "tags": ["standing sex", "lying", "on back"],
        "reason": "体位矛盾",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "action",
        "tags": ["missionary", "doggystyle"],
        "reason": "不可能同时两个体位",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "action",
        "tags": ["cowgirl position", "prone bone"],
        "reason": "体位矛盾",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "action",
        "tags": ["fellatio", "cunnilingus"],
        "reason": "嘴只有一张",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "prop",
        "tags": ["gun", "rifle", "pistol", "spear", "wooden sword", "energy sword", "knife", "dagger"],
        "reason": "同一画面通常不应同时出现多种武器",
        "strategy": "drop_all_but_one",
        "max_keep": 2,
    },
    # ---------- environment（场景/地点一致性） ----------
    {
        "type": "environment",
        "tags": [
            "bedroom",
            "classroom",
            "changing room",
            "kitchen",
            "bathroom",
            "living room",
            "dining room",
            "office",
            "library",
        ],
        "reason": "同一画面不应同时出现多个具体室内房间",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "environment",
        "tags": [
            "forest",
            "street",
            "beach",
            "mountain",
            "park",
            "city",
            "road",
            "meadow",
            "field",
            "desert",
            "river",
            "lake",
            "ocean",
        ],
        "reason": "同一画面不应同时出现多个具体户外场景",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "environment",
        "tags": [
            "on bed",
            "on table",
            "on roof",
            "on stairs",
            "on stump",
            "on chair",
            "on couch",
            "on floor",
            "on grass",
        ],
        "reason": "同一角色不可能同时位于多个支撑面/位置",
        "strategy": "drop_all_but_one",
    },
    # ---------- detail（细节过度） ----------
    {
        "type": "detail",
        "tags": ["spread toes", "toe scrunch", "toes curling"],
        "reason": "舒展 vs 蜷缩，物理矛盾",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["spread toes", "feet together"],
        "reason": "分趾需要空间，合拢则压缩",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["spread fingers", "clenched fist", "gripping"],
        "reason": "张开 vs 握拳",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["bouncing breasts", "breasts squeeze together"],
        "reason": "弹跳 vs 挤压，动态矛盾",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["open mouth", "clenched teeth", "closed mouth"],
        "reason": "张嘴 vs 闭嘴",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["rolling eyes", "looking at viewer"],
        "reason": "翻白眼 vs 直视",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": ["spread legs", "legs together"],
        "reason": "分开 vs 并拢",
        "strategy": "drop_b",
    },
    {
        "type": "detail",
        "tags": [
            "foot focus",
            "footjob",
            "toe scrunch",
            "spread toes",
            "barefoot",
            "soles",
            "feet together",
        ],
        "reason": "过度细化导致脚趾/脚掌畸形",
        "strategy": "drop_all_but_one",
        "max_keep": 2,
    },
    # ---------- content_rating（R15 审查与冲突消解） ----------
    {
        "type": "content_rating",
        "tags": [
            "pussy",
            "vagina",
            "penis",
            "anus",
            "clitoris",
            "sex",
            "penetration",
            "fellatio",
            "cunnilingus",
            "intercourse",
        ],
        "reason": "R15 硬上限下性器官/性行为直述词不应同时出现",
        "strategy": "drop_all_but_one",
        # 当 max_rating 高于 r15（如 r18）时禁用本规则，允许成人 tag 同时出现。
        "enabled_up_to": "r15",
    },
    {
        "type": "content_rating",
        "tags": [
            "school",
            "classroom",
            "pussy",
            "vagina",
            "penis",
            "anus",
            "clitoris",
            "sex",
            "penetration",
            "fellatio",
            "cunnilingus",
            "intercourse",
            "loli",
            "shota",
        ],
        # 仅当校园/教室或未成年暗示词出现时才触发，避免无校园词时
        # 误消解 r18 模式下的成人 tag。
        "trigger_tags": ["school", "classroom", "loli", "shota"],
        "reason": "校园/教室场景或未成年暗示与 explicit tag 共存会触发审查",
        "strategy": "drop_all_but_one",
    },
    {
        "type": "clothing",
        "tags": ["underwear", "lingerie", "completely nude"],
        "reason": "穿着内衣与全裸状态矛盾",
        "strategy": "drop_all_but_one",
    },
]

#: 内部类别到展示用中文名的映射。
CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "count_gender": "人数与性别",
    "appearance": "外貌",
    "clothing_state": "服装与穿着状态",
    "pose_action_sex": "姿势/动作/体位",
    "expression_reaction": "表情与反应",
    "camera_shot": "镜头/景别/构图",
    "scene_environment": "场景与环境",
    "detail_mood": "画面质感/氛围",
    "character_series": "二次元角色",
}


def detect_conflicts(
    tag_list: list[str],
    rules: list[dict] | None = None,
) -> list[dict]:
    """检测 tag 集合中的互斥冲突。

    Args:
        tag_list: 待检测的 tag 列表。
        rules: 自定义冲突规则；默认使用 :data:`CONFLICT_RULES`。

    Returns:
        冲突列表，每项包含 ``rule``、``triggered_tags`` 与 ``indices``。
        其中 ``triggered_tags`` 与 ``indices`` 按在 ``tag_list`` 中出现的顺序排列。
    """
    rules = rules or CONFLICT_RULES
    conflicts: list[dict] = []

    for rule in rules:
        tags = rule.get("tags", [])
        if not tags:
            continue

        # ``completely nude`` 规则依赖类别上下文，在纯 tag 列表中无法判断具体服装。
        if rule.get("category_to_drop"):
            continue

        rule_tags = {_normalize_tag(t) for t in tags}
        triggered: list[str] = []
        indices: list[int] = []
        for idx, tag in enumerate(tag_list):
            if _normalize_tag(tag) in rule_tags:
                triggered.append(tag)
                indices.append(idx)

        if len(triggered) >= 2:
            conflicts.append(
                {
                    "rule": rule,
                    "triggered_tags": triggered,
                    "indices": indices,
                }
            )

    return conflicts


def resolve_conflicts(
    tag_list: list[str],
    rules: list[dict] | None = None,
    context: dict | None = None,
    max_rating: str = "r15",
) -> tuple[list[str], list[dict]]:
    """消解 tag 集合中的互斥冲突。

    Args:
        tag_list: 原始 tag 列表。
        rules: 自定义冲突规则；默认使用 :data:`CONFLICT_RULES`。
        context: 可选上下文，支持以下键：
            - ``category_map``: ``{normalized_tag: category}``，用于 ``completely nude``
              规则识别应被移除的服装 tag。
            - ``partial_nudity``: 若为真，``completely nude`` 与服装共存时改写为
              ``partially undressed`` 而非直接丢弃服装。
        max_rating: 内容分级上限；标有 ``enabled_up_to`` 且上限低于当前分级的
            规则会被跳过（例如 r18 模式下的成人内容互斥规则）。

    Returns:
        ``(resolved_tags, log)``。``resolved_tags`` 为消解后的 tag 列表；``log``
        记录每条规则的处理结果，包含 ``rule``、``dropped_tags``、``kept_tags``、
        ``reason`` 等字段。
    """
    rules = rules or CONFLICT_RULES
    if max_rating in config.RATING_ORDER:
        max_index = config.RATING_ORDER.index(max_rating)
        rules = [
            rule
            for rule in rules
            if not rule.get("enabled_up_to")
            or config.RATING_ORDER.index(rule["enabled_up_to"]) >= max_index
        ]
    context = context or {}
    category_map: dict[str, str] = context.get("category_map", {})
    partial_nudity: bool = bool(context.get("partial_nudity", False))

    resolved = list(tag_list)
    log: list[dict] = []

    for rule in rules:
        rule_tags = {_normalize_tag(t) for t in rule.get("tags", [])}
        if not rule_tags:
            continue

        # 可选触发条件：仅当 trigger_tags 中至少一个词存在于当前 tag 集合时
        # 才应用该规则（用于校园场景等需配合特定上下文才生效的防审查规则）。
        trigger_tags = {_normalize_tag(t) for t in rule.get("trigger_tags", [])}
        if trigger_tags and not any(
            _normalize_tag(t) in trigger_tags for t in resolved
        ):
            continue

        # 特殊处理：completely nude 与任何具体服装标签冲突。
        if rule.get("category_to_drop") and "completely nude" in rule_tags:
            nude_idx: int | None = None
            for idx, tag in enumerate(resolved):
                if _normalize_tag(tag) == "completely nude":
                    nude_idx = idx
                    break
            if nude_idx is None:
                continue

            target_category = rule.get("category_to_drop", "clothing_state")
            clothing_indices = [
                idx
                for idx, tag in enumerate(resolved)
                if idx != nude_idx and category_map.get(_normalize_tag(tag)) == target_category
            ]
            if not clothing_indices:
                continue

            dropped = [resolved[i] for i in clothing_indices]
            if partial_nudity:
                new_resolved: list[str] = []
                for idx, tag in enumerate(resolved):
                    if idx not in clothing_indices:
                        new_resolved.append(tag)
                    if idx == nude_idx:
                        new_resolved.append("partially undressed")
                resolved = new_resolved
                log.append(
                    {
                        "rule": rule,
                        "dropped_tags": dropped,
                        "kept_tag": resolved[nude_idx] if nude_idx < len(resolved) else "completely nude",
                        "rewritten_to": "partially undressed",
                        "reason": rule.get("reason"),
                    }
                )
            else:
                resolved = [tag for idx, tag in enumerate(resolved) if idx not in clothing_indices]
                log.append(
                    {
                        "rule": rule,
                        "dropped_tags": dropped,
                        "kept_tag": "completely nude",
                        "reason": rule.get("reason"),
                    }
                )
            continue

        triggered: list[tuple[int, str]] = []
        for idx, tag in enumerate(resolved):
            if _normalize_tag(tag) in rule_tags:
                triggered.append((idx, tag))

        if len(triggered) < 2:
            continue

        max_keep = rule.get("max_keep", 1)
        if len(triggered) <= max_keep:
            continue

        keep = triggered[:max_keep]
        drop = triggered[max_keep:]
        drop_indices = {idx for idx, _ in drop}
        kept_tags = [tag for _, tag in keep]
        dropped_tags = [tag for _, tag in drop]

        resolved = [tag for idx, tag in enumerate(resolved) if idx not in drop_indices]
        log.append(
            {
                "rule": rule,
                "dropped_tags": dropped_tags,
                "kept_tags": kept_tags,
                "reason": rule.get("reason"),
                "strategy": rule.get("strategy", "drop_all_but_one"),
            }
        )

    return resolved, log


def build_prompt_payload(
    sampled_tags: dict[str, list[dict]],
    rules: list[dict] | None = None,
    max_rating: str = "r15",
) -> dict:
    """将抽样 tag 与规则组装为 DeepSeek 请求载荷。

    Args:
        sampled_tags: 按内部类别分组的抽样结果，形如
            ``{"appearance": [{"tag": "long hair", ...}, ...], ...}``。
        rules: 自定义冲突规则；默认使用 :data:`CONFLICT_RULES`。
        max_rating: 内容分级上限，透传给 :func:`resolve_conflicts`。

    Returns:
        包含以下键的字典：
        - ``resolved_tags``: 冲突消解后的 tag 列表。
        - ``category_map``: ``{normalized_tag: category}`` 映射。
        - ``conflict_log``: 冲突消解日志。
        - ``character_pool_info``: 若 ``character_series`` 来自 Excel 角色池，
          包含角色列表等附加信息。
    """
    tag_list: list[str] = []
    category_map: dict[str, str] = {}

    for category, items in sampled_tags.items():
        for item in items:
            tag = item.get("tag", "") if isinstance(item, dict) else str(item)
            if not tag:
                continue
            tag_list.append(tag)
            category_map[_normalize_tag(tag)] = category

    resolved_tags, conflict_log = resolve_conflicts(
        tag_list,
        rules=rules,
        context={"category_map": category_map},
        max_rating=max_rating,
    )

    # 收集 Excel 角色池中的角色附加信息，供 prompt 渲染使用。
    character_pool_info: list[dict] | None = None
    char_items = sampled_tags.get("character_series", [])
    if char_items and any(item.get("source") == "character_pool" for item in char_items):
        character_pool_info = [
            {
                "tag": item.get("tag", ""),
                "series_tag": item.get("series_tag", ""),
                "trigger_tags": list(item.get("trigger_tags", [])),
                "core_appearance_tags": list(item.get("core_appearance_tags", [])),
                "core_clothing_tags": list(item.get("core_clothing_tags", [])),
            }
            for item in char_items
            if item.get("source") == "character_pool"
        ]

    return {
        "resolved_tags": resolved_tags,
        "category_map": category_map,
        "conflict_log": conflict_log,
        "character_pool_info": character_pool_info,
    }


def format_tags_for_llm(payload: dict) -> str:
    """将组装后的载荷格式化为按类别分组的自然语言字符串。

    Args:
        payload: :func:`build_prompt_payload` 返回的字典。

    Returns:
        适合放入 DeepSeek user prompt 的 tag 分组文本。
    """
    resolved_tags: list[str] = payload.get("resolved_tags", [])
    category_map: dict[str, str] = payload.get("category_map", {})

    groups: dict[str, list[str]] = {}
    unknown: list[str] = []

    for tag in resolved_tags:
        category = category_map.get(_normalize_tag(tag))
        if category:
            groups.setdefault(category, []).append(tag)
        else:
            unknown.append(tag)

    lines: list[str] = []
    for category, display_name in CATEGORY_DISPLAY_NAMES.items():
        tags = groups.get(category)
        if not tags:
            continue
        lines.append(f"【{display_name}】")
        lines.append(", ".join(tags))
        lines.append("")

    if unknown:
        lines.append("【其他】")
        lines.append(", ".join(unknown))
        lines.append("")

    return "\n".join(lines).rstrip()


if __name__ == "__main__":
    # 简单冒烟测试：覆盖 view / identity / clothing / action / detail 五类冲突。
    sampled: dict[str, list[dict]] = {
        "count_gender": [{"tag": "solo"}, {"tag": "1boy"}],
        "appearance": [{"tag": "long hair"}, {"tag": "blue eyes"}],
        "clothing_state": [{"tag": "completely nude"}, {"tag": "school uniform"}],
        "pose_action_sex": [{"tag": "missionary"}, {"tag": "doggystyle"}],
        "expression_reaction": [{"tag": "open mouth"}, {"tag": "closed mouth"}],
        "camera_shot": [{"tag": "from front"}, {"tag": "from behind"}],
        "scene_environment": [{"tag": "bedroom"}],
        "detail_mood": [{"tag": "dramatic tension"}],
    }

    print("=== 冲突检测 ===")
    flat_tags = [item["tag"] for items in sampled.values() for item in items]
    conflicts = detect_conflicts(flat_tags)
    for conflict in conflicts:
        rule = conflict["rule"]
        print(
            f"[{rule['type']}] {conflict['triggered_tags']} -> {rule['reason']}"
        )

    print("\n=== 冲突消解 ===")
    payload = build_prompt_payload(sampled)
    print("resolved_tags:", payload["resolved_tags"])
    print("conflict_log entries:", len(payload["conflict_log"]))
    for entry in payload["conflict_log"]:
        rule = entry["rule"]
        print(
            f"  [{rule['type']}] dropped={entry.get('dropped_tags', [])} "
            f"kept={entry.get('kept_tags') or entry.get('kept_tag')}"
        )

    print("\n=== LLM 格式化 ===")
    print(format_tags_for_llm(payload))
