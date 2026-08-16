"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import assembler, client, config, postprocess, retrieval


def _load_yaml_config(path: str | None) -> dict[str, Any]:
    """加载 YAML 配置文件；若未提供则返回空字典。"""
    if not path:
        return {}
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required for --config. Install it via requirements.txt."
        ) from exc
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_generation_config(path: str | None = None) -> dict[str, Any]:
    """加载生成器默认配置；未指定路径时尝试加载 generation_config.yaml。"""
    if path:
        return _load_yaml_config(path)
    if config.GENERATION_CONFIG_FILE.exists():
        return _load_yaml_config(str(config.GENERATION_CONFIG_FILE))
    return {}


def _format_focus_weights(weights: dict[str, Any]) -> str:
    """将 focus_weights 转换为自然语言提示文本。"""
    if not weights:
        return ""
    return ", ".join(f"{key} ~{value}%" for key, value in weights.items())


def _adjust_focus_weights_for_multi(
    focus_weights: dict[str, Any], bonus: int | float
) -> dict[str, Any]:
    """多角色时调整生成侧重点权重。

    ``character`` 增加 ``bonus``（百分比），并从 ``background`` 与 ``other``
    中按各自权重比例扣减相同额度。若缺少 ``character`` 键，或
    ``background`` 与 ``other`` 权重之和为 0，则原样返回。
    """
    weights = dict(focus_weights)
    if "character" not in weights:
        return weights
    background = float(weights.get("background", 0) or 0)
    other = float(weights.get("other", 0) or 0)
    total = background + other
    if total <= 0:
        return weights
    weights["character"] = weights["character"] + bonus
    weights["background"] = round(background - bonus * background / total)
    weights["other"] = round(other - bonus * other / total)
    return weights


def _resolve_sample_constraints(
    is_multi_character: bool,
    min_tags: int,
    max_tags: int,
    focus_weights: dict[str, Any],
    multi_character_cfg: dict[str, Any],
) -> tuple[int, int, str]:
    """根据是否多角色计算样本实际生效的 tag 数量区间与 focus 文本。

    多角色触发时：
    - ``min_tags`` 与 ``max_tags`` 各增加 ``tag_count_bonus``（n）；
    - ``focus_weights`` 中 ``character`` 增加 ``focus_character_bonus``（m），
      并从 ``background`` / ``other`` 按比例扣减。

    Returns:
        ``(有效 min_tags, 有效 max_tags, 有效 focus_text)``。
    """
    if not is_multi_character:
        return min_tags, max_tags, _format_focus_weights(focus_weights)

    tag_bonus = int(multi_character_cfg.get("tag_count_bonus", 0) or 0)
    char_bonus = multi_character_cfg.get("focus_character_bonus", 0) or 0

    eff_min_tags = min_tags + tag_bonus
    eff_max_tags = max_tags + tag_bonus
    adjusted = _adjust_focus_weights_for_multi(focus_weights, char_bonus)
    return eff_min_tags, eff_max_tags, _format_focus_weights(adjusted)


def _collect_exclude_map(pool: dict[str, Any]) -> dict[str, set[str]]:
    """收集所有条目的互斥声明：条目文本 -> 被其排除的其他条目文本集合。

    支持 mutex_groups 与 optional_items 中的任意条目通过可选字段 ``excludes``
    声明与其他条目互斥（文本精确匹配）。
    """
    exclude_map: dict[str, set[str]] = {}
    for group in pool.get("mutex_groups") or []:
        for item in group.get("items", []):
            excludes = item.get("excludes")
            if excludes:
                exclude_map[item["text"]] = set(excludes)
    for item in pool.get("optional_items") or []:
        excludes = item.get("excludes")
        if excludes:
            exclude_map[item["text"]] = set(excludes)
    return exclude_map


def _item_conflicts(
    exclude_map: dict[str, set[str]], candidate: str, selected: list[str]
) -> bool:
    """判断候选条目与已选条目是否存在互斥（双向检查）。"""
    for sel in selected:
        if candidate in exclude_map.get(sel, set()):
            return True
        if sel in exclude_map.get(candidate, set()):
            return True
    return False


def sample_extra_requirements(pool: dict[str, Any]) -> str:
    """从 extra_requirements_pool 中抽样额外要求文本。

    Args:
        pool: extra_requirements_pool 配置块。

    Returns:
        抽样得到的文本，多条以换行符连接；未启用或为空时返回空字符串。

    行为说明：
    - mutex_groups：每组按 weight 加权抽 1 项；skip_probability 表示整组跳过。
    - optional_items：每项按自身 probability 独立决定是否加入。
    - 条目级互斥：条目可通过 ``excludes`` 声明与已抽中的其他条目互斥，
      冲突候选会被过滤；互斥组内全部候选冲突时整组跳过。
    """
    if not pool or not pool.get("enabled"):
        return ""

    selected: list[str] = []
    exclude_map = _collect_exclude_map(pool)

    for group in pool.get("mutex_groups") or []:
        skip_probability = group.get("skip_probability", 0.0)
        if random.random() < skip_probability:
            continue
        items = group.get("items", [])
        if not items:
            continue
        candidates = [
            item
            for item in items
            if not _item_conflicts(exclude_map, item["text"], selected)
        ]
        if not candidates:
            continue
        weights = [item.get("weight", 1) for item in candidates]
        chosen = random.choices(candidates, weights=weights, k=1)[0]
        selected.append(chosen["text"])

    for item in pool.get("optional_items") or []:
        probability = item.get("probability", 1.0)
        if random.random() >= probability:
            continue
        if _item_conflicts(exclude_map, item["text"], selected):
            continue
        selected.append(item["text"])

    return "\n".join(selected)


def _normalize_tag(tag: str) -> str:
    """统一 tag 格式用于比较。"""
    return tag.strip().replace("_", " ").lower()


def _is_multi_character(sampled_tags_text: str) -> bool:
    """根据抽样 tag 文本判断是否包含多人场景标记。

    统一 '_'、'-' 与 ',' 为空白后按词匹配，以兼容换行、逗号等多种分隔，
    避免 tag 分组标题（如 ``【人数与性别】``）与目标标记位于同一行时漏检。
    """
    multi_markers = {
        "2girls",
        "3girls",
        "2boys",
        "3boys",
        "multiple girls",
        "multiple boys",
    }
    normalized = (
        sampled_tags_text.replace("_", " ")
        .replace("-", " ")
        .replace(",", " ")
        .lower()
    )
    words = normalized.split()
    for word in words:
        if word in multi_markers:
            return True
    for i in range(len(words) - 1):
        if f"{words[i]} {words[i + 1]}" in multi_markers:
            return True
    return False


def _build_fallback_character_pool_info(
    sampled_tags_text: str,
    character_tag: str,
    sampled: dict[str, Any],
) -> dict[str, Any] | None:
    """当没有 Excel 角色池信息但检测到多人场景时，构造兼容的角色池结构。

    优先使用 sampled['character_series'] 中的条目；若不可用但 character_tag
    包含逗号分隔的多个角色名，则按逗号拆分。
    """
    if not _is_multi_character(sampled_tags_text):
        return None

    characters: list[dict[str, Any]] = []
    if sampled.get("character_series"):
        for item in sampled["character_series"]:
            characters.append(
                {
                    "tag": item["tag"],
                    "series_tag": item.get("series_tag", ""),
                    "core_appearance_tags": [],
                    "core_clothing_tags": [],
                }
            )
    elif character_tag and "," in character_tag:
        for name in character_tag.split(","):
            name = name.strip()
            if name:
                characters.append(
                    {
                        "tag": name,
                        "series_tag": "",
                        "core_appearance_tags": [],
                        "core_clothing_tags": [],
                    }
                )

    if not characters:
        return None
    return {
        "characters": characters,
        "clothing_strategy": "sampled_only",
    }


def _resolve_api_profile(
    args: argparse.Namespace,
) -> tuple[str | None, str | None, str | None, Any]:
    """合并 API 平台配置：命令行显式参数优先，其次 ``--api-config`` 配置文件。

    ``api_key`` 来源依次为：命令行 ``--api-key`` > 配置文件中 ``api_key`` 字段
    > 配置文件中 ``api_key_env`` 指定的环境变量。``api_base`` / ``model``
    为命令行参数 > 配置文件字段。``temperature`` 仅来自配置文件（可为 ``null``
    表示不发送该参数，适配不支持 temperature 的代理平台）。

    Returns:
        ``(api_key, api_base, model, temperature)``；缺失项为 ``None``，由
        client 层继续回退环境变量与 ``config.py`` 默认值。
    """
    profile = _load_yaml_config(args.api_config) if args.api_config else {}
    api_key = args.api_key if args.api_key is not None else profile.get("api_key")
    if api_key is None and profile.get("api_key_env"):
        api_key = os.environ.get(str(profile["api_key_env"])) or None
    api_base = args.api_base if args.api_base is not None else profile.get("api_base")
    model = args.model if args.model is not None else profile.get("model")
    temperature = profile.get("temperature")
    return api_key, api_base, model, temperature


def _print_progress(current: int, total: int, dry_run: bool = False) -> None:
    """在同一行打印当前进度。

    Args:
        current: 当前已完成数量。
        total: 总数量。
        dry_run: 是否为 dry-run 模式。
    """
    mode = "dry-run" if dry_run else "生成"
    bar_len = 20
    filled = int(bar_len * current / total) if total > 0 else bar_len
    bar = "█" * filled + "-" * (bar_len - filled)
    sys.stdout.write(f"\r[{bar}] {mode} 进度: {current}/{total}")
    if current == total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def _determine_safety(sampled_tags: dict[str, list[dict[str, Any]]]) -> str:
    """根据抽样 tag 自动判定安全标签。

    对每条 tag 按词拆分并做整词匹配，同时支持多词 tag 的完整匹配。
    """
    tags = [
        _normalize_tag(item["tag"])
        for items in sampled_tags.values()
        for item in items
    ]

    explicit = {
        "sex",
        "penetration",
        "penetrated",
        "inserted",
        "stuffed",
        "filled",
        "white fluid",
        "sticky liquid",
        "dripping liquid",
        "fellatio",
        "cunnilingus",
        "missionary",
        "doggystyle",
        "cowgirl position",
        "prone bone",
        "rape",
        "gangbang",
        "anal",
        "vaginal",
        "blowjob",
        "cum",
        "anus",
    }
    nsfw = {
        "nude",
        "completely nude",
        "no clothes",
        "naked",
        "bare body",
        "fully exposed",
        "pussy",
        "vagina",
        "penis",
        "dick",
        "cock",
        "clit",
        "cunt",
    }
    sensitive = {
        "lingerie",
        "swimsuit",
        "bikini",
        "panties",
        "bra",
        "exposed slit",
        "visible slit",
        "wet slit",
        "pink inside",
        "visible bulge",
        "tented shorts",
        "bulge",
        "cleavage",
        "underwear",
        "partially undressed",
    }

    def _matches_any(tag: str, keywords: set[str]) -> bool:
        if tag in keywords:
            return True
        return any(word in keywords for word in tag.split())

    for tag in tags:
        if _matches_any(tag, explicit):
            return "explicit"
    for tag in tags:
        if _matches_any(tag, nsfw):
            return "nsfw"
    for tag in tags:
        if _matches_any(tag, sensitive):
            return "sensitive"
    return "safe"


def _build_config(
    args: argparse.Namespace,
) -> tuple[
    dict[str, int],
    dict[str, Any],
    str,
    dict[str, Any],
    str,
    int,
    int,
    str,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    int,
    str,
    dict[str, Any],
    dict[str, int],
    dict[str, Any],
]:
    """合并命令行参数、默认生成器配置文件与自定义配置文件。"""
    gen_cfg = _load_generation_config()
    user_cfg = _load_yaml_config(args.config)

    # 知识库 v1 每个类别的抽样数量。
    # 配置文件中的 sample_counts 与 knowledge_sample_counts 均视为同一含义，
    # 后者优先级更高。
    knowledge_sample_counts = dict(config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS)
    knowledge_sample_counts.update(gen_cfg.get("sample_counts", {}))
    knowledge_sample_counts.update(user_cfg.get("sample_counts", {}))
    knowledge_sample_counts.update(gen_cfg.get("knowledge_sample_counts", {}))
    knowledge_sample_counts.update(user_cfg.get("knowledge_sample_counts", {}))

    deepseek_cfg: dict[str, Any] = {}
    deepseek_cfg.update(gen_cfg.get("deepseek", {}))
    deepseek_cfg.update(user_cfg.get("deepseek", {}))

    output_dir = user_cfg.get("output_dir") or gen_cfg.get("output_dir") or "output"

    focus_weights = dict(gen_cfg.get("focus_weights", {}))
    focus_weights.update(user_cfg.get("focus_weights", {}))

    extra_requirements = (
        args.extra_requirements
        if args.extra_requirements is not None
        else user_cfg.get("extra_requirements") or gen_cfg.get("extra_requirements") or ""
    )

    extra_requirements_pool = dict(gen_cfg.get("extra_requirements_pool", {}))
    extra_requirements_pool.update(user_cfg.get("extra_requirements_pool", {}))

    # 反趋同：默认词配额（抽样侧词帽 + 模板注入 + postprocess 校验共用同一配置）。
    default_word_quota = dict(gen_cfg.get("default_word_quota", {}))
    default_word_quota.update(user_cfg.get("default_word_quota", {}))

    # 创意锚点池配置（enabled / file）。
    creative_anchors_cfg = dict(gen_cfg.get("creative_anchors", {}))
    creative_anchors_cfg.update(user_cfg.get("creative_anchors", {}))

    max_rating = (
        args.max_rating
        or user_cfg.get("max_rating")
        or gen_cfg.get("max_rating")
        or config.DEFAULT_MAX_RATING
    )

    # r18 模式专用抽样数量：仅 max_rating 为 r18/r18g 时覆盖全局 sample_counts，
    # 用于减少每样本输入 tag 总量，降低 LLM 丢弃压力。非 r18 模式完全不受影响。
    if max_rating in ("r18", "r18g"):
        r18_sample_counts = dict(gen_cfg.get("r18_sample_counts", {}))
        r18_sample_counts.update(user_cfg.get("r18_sample_counts", {}))
        if r18_sample_counts:
            knowledge_sample_counts.update(r18_sample_counts)

    # r18 模式专用生成侧重点权重：仅 max_rating 为 r18/r18g 时覆盖上方 focus_weights。
    # 用于提示 LLM 在最终 prompt 中各类描述的占比（如角色 40%、背景 20%、r18 20%、其他 20%），
    # 不改变任何类别的抽样数量。非 r18 模式完全不受影响。
    if max_rating in ("r18", "r18g"):
        r18_focus_weights = dict(gen_cfg.get("r18_focus_weights", {}))
        r18_focus_weights.update(user_cfg.get("r18_focus_weights", {}))
        if r18_focus_weights:
            focus_weights = r18_focus_weights

    min_tags = int(
        args.min_tags
        if args.min_tags is not None
        else user_cfg.get("min_tags") or gen_cfg.get("min_tags") or 50
    )
    max_tags = int(
        args.max_tags
        if args.max_tags is not None
        else user_cfg.get("max_tags") or gen_cfg.get("max_tags") or 75
    )

    # 深度合并白名单角色池配置：默认 < generation_config.yaml < 用户配置文件。
    character_whitelist = dict(config.DEFAULT_CHARACTER_WHITELIST)
    character_whitelist.update(gen_cfg.get("character_whitelist", {}))
    character_whitelist.update(user_cfg.get("character_whitelist", {}))

    def _normalize_pool_keys(pools: dict[str, Any]) -> dict[str, Any]:
        """将 pools 中的中文类别键名转换为内部英文键名，保留已有的英文键名。"""
        normalized: dict[str, Any] = {}
        for key, value in pools.items():
            internal_key = config.CATEGORY_DISPLAY_NAME_TO_INTERNAL.get(key, key)
            normalized[internal_key] = value
        return normalized

    # 深度合并通用类别白名单池配置：默认 < generation_config.yaml < 用户配置文件。
    category_whitelists: dict[str, Any] = {
        "enabled": config.DEFAULT_CATEGORY_WHITELISTS["enabled"],
        "pools": dict(config.DEFAULT_CATEGORY_WHITELISTS["pools"]),
    }
    gen_cat = gen_cfg.get("category_whitelists", {})
    user_cat = user_cfg.get("category_whitelists", {})
    category_whitelists["enabled"] = user_cat.get("enabled", gen_cat.get("enabled", category_whitelists["enabled"]))

    # 合并时支持中文类别键名。
    gen_pools = _normalize_pool_keys(gen_cat.get("pools", {}))
    user_pools = _normalize_pool_keys(user_cat.get("pools", {}))
    for key in category_whitelists["pools"]:
        pool: list[Any] = list(category_whitelists["pools"][key])
        pool = gen_pools.get(key, pool)
        pool = user_pools.get(key, pool)
        category_whitelists["pools"][key] = pool

    # 保持 character_whitelist 兼容：若 character_series 白名单池为空且旧角色池启用，则复制旧池。
    if (
        not category_whitelists["pools"].get("character_series")
        and character_whitelist.get("enabled")
        and character_whitelist.get("pool")
    ):
        category_whitelists["pools"]["character_series"] = list(character_whitelist["pool"])

    # 深度合并 Excel 角色池配置：默认 < generation_config.yaml < 用户配置文件。
    character_pool = dict(config.DEFAULT_CHARACTER_POOL)
    character_pool.update(gen_cfg.get("character_pool", {}))
    character_pool.update(user_cfg.get("character_pool", {}))

    # 命令行自定义角色池 JSON 优先级最高；提供时强制启用角色池并替换文件路径。
    if args.character_json is not None:
        character_pool["enabled"] = True
        character_pool["file"] = args.character_json

    # 深度合并多角色触发配置：默认 < generation_config.yaml < 用户配置文件。
    multi_character_cfg = dict(config.DEFAULT_MULTI_CHARACTER)
    multi_character_cfg.update(gen_cfg.get("multi_character", {}))
    multi_character_cfg.update(user_cfg.get("multi_character", {}))

    # r18 模式下每个样本至少抽到的 r18 评级 tag 数量（0 表示不强制）。
    min_r18_tags_per_sample = user_cfg.get("min_r18_tags_per_sample")
    if min_r18_tags_per_sample is None:
        min_r18_tags_per_sample = gen_cfg.get("min_r18_tags_per_sample")
    if min_r18_tags_per_sample is None:
        min_r18_tags_per_sample = config.DEFAULT_MIN_R18_TAGS_PER_SAMPLE
    min_r18_tags_per_sample = int(min_r18_tags_per_sample)

    # r18 模式下注入到 LLM 用户提示词的自定义指令文本（默认留空，仅提供机制）。
    r18_instructions = (
        user_cfg.get("r18_instructions")
        or gen_cfg.get("r18_instructions")
        or config.DEFAULT_R18_INSTRUCTIONS
        or ""
    )

    # r18 标签主题控制：默认 < generation_config.yaml < 用户配置文件（topics 逐主题覆盖）。
    # 仅 max_rating 为 r18/r18g 时在抽样链路中生效（见 retrieval.sample_from_knowledge_v1）。
    r18_topic_control: dict[str, Any] = {
        "enabled": bool(config.DEFAULT_R18_TOPIC_CONTROL.get("enabled", True)),
        "topics": dict(config.DEFAULT_R18_TOPIC_CONTROL.get("topics", {})),
    }
    gen_topics_control = gen_cfg.get("r18_topic_control", {})
    user_topics_control = user_cfg.get("r18_topic_control", {})
    if isinstance(gen_topics_control, dict):
        r18_topic_control["enabled"] = bool(
            gen_topics_control.get("enabled", r18_topic_control["enabled"])
        )
    if isinstance(user_topics_control, dict):
        r18_topic_control["enabled"] = bool(
            user_topics_control.get("enabled", r18_topic_control["enabled"])
        )
    merged_topics = dict(r18_topic_control["topics"])
    if isinstance(gen_topics_control, dict):
        merged_topics.update(gen_topics_control.get("topics", {}))
    if isinstance(user_topics_control, dict):
        merged_topics.update(user_topics_control.get("topics", {}))
    r18_topic_control["topics"] = merged_topics

    # 单人场景主题限制合并：默认 < generation_config.yaml < 用户配置文件。
    solo_cfg = dict(config.DEFAULT_R18_TOPIC_CONTROL.get("solo", {}))
    if isinstance(gen_topics_control, dict) and isinstance(
        gen_topics_control.get("solo"), dict
    ):
        solo_cfg.update(gen_topics_control["solo"])
    if isinstance(user_topics_control, dict) and isinstance(
        user_topics_control.get("solo"), dict
    ):
        solo_cfg.update(user_topics_control["solo"])
    if solo_cfg:
        r18_topic_control["solo"] = solo_cfg

    return (
        knowledge_sample_counts,
        deepseek_cfg,
        output_dir,
        focus_weights,
        max_rating,
        min_tags,
        max_tags,
        extra_requirements,
        extra_requirements_pool,
        character_whitelist,
        category_whitelists,
        character_pool,
        multi_character_cfg,
        min_r18_tags_per_sample,
        r18_instructions,
        r18_topic_control,
        default_word_quota,
        creative_anchors_cfg,
    )


def _record_to_jsonl(
    result: dict[str, Any],
    sampled_tags: dict[str, list[dict[str, Any]]],
    v2_only: bool,
    focus_text: str = "",
) -> dict[str, Any]:
    """将生成结果整理为最终保存的记录。"""
    record = dict(result)
    record["sampled_tags"] = {
        category: [item["tag"] for item in items]
        for category, items in sampled_tags.items()
    }
    if focus_text:
        record["focus_text"] = focus_text
    # v2 已关闭（parse_response 不再生成 version_2）：仅当记录中确实存在
    # version_2 时才允许 v2_only 删除 version_1，避免产出空记录。
    if v2_only and "version_2" in record:
        record.pop("version_1", None)
    return record


def _build_rating_map(curated_tags: dict) -> dict[str, str]:
    """从 curated_tags 构建 tag(规范化) -> rating 映射。"""
    rating_map: dict[str, str] = {}
    for cat_tags in curated_tags.values():
        for t in cat_tags:
            rating_map[t["tag"].replace("_", " ").lower()] = t.get("rating", "general")
    return rating_map


def _collect_r18_tags(
    sampled: dict, rating_map: dict[str, str]
) -> list[tuple[str, str]]:
    """收集抽样结果中 rating 恰为 r18 的 (类别, tag)，类别用于占位符槽位编码。"""
    r18_tags: list[tuple[str, str]] = []
    for category, values in sampled.items():
        if not isinstance(values, list):
            continue
        for item in values:
            tag = item.get("tag") if isinstance(item, dict) else item
            if not tag:
                continue
            if rating_map.get(tag.replace("_", " ").lower()) == "r18":
                r18_tags.append((category, tag))
    return r18_tags


def _generate_one_task(
    task: dict[str, Any],
    api_key: str | None,
    api_base: str | None,
    model: str | None,
    artist_blacklist: Any,
    database: Any,
    v2_only: bool,
    v2_enhance: bool = False,
) -> dict[str, Any]:
    """在线程中执行单条 API 调用与后处理。

    所有需要在线程间隔离的调用都在本函数内完成；发生异常时返回错误信息，
    由主线程决定是否跳过。
    """
    try:
        anchor_tags = [
            a.get("tag", "") for a in (task.get("creative_anchor_info") or [])
            if a.get("tag")
        ]
        # 创意锚点保留：若 LLM 丢弃锚点，追加一次带强制锚点的重试。
        anchor_retry = False
        max_anchor_attempts = 2 if anchor_tags else 1
        for attempt in range(max_anchor_attempts):
            result = client.generate_single(
                sampled_tags_text=task["sampled_text"],
                safety=task["safety"],
                min_tags=task["min_tags"],
                max_tags=task["max_tags"],
                theme_hint=task["theme_hint"],
                focus_text=task["focus_text"],
                temperature=task["temperature"],
                max_tokens=task["max_tokens"],
                timeout=task["timeout"],
                max_parse_retries=task["max_parse_retries"],
                subject_control=task["subject_control"],
                forced_tags=task["forced_tags"],
                forbidden_tags=task["forbidden_tags"],
                character_tag=task["character_tag"],
                max_rating=task["max_rating"],
                extra_requirements=task["extra_requirements"],
                character_pool_info=task["character_pool_info"],
                placeholder_meanings=task.get("placeholder_meanings"),
                r18_instructions=task["r18_instructions"],
                reasoning_effort=task["reasoning_effort"],
                creative_anchor_info=task.get("creative_anchor_info"),
                api_key=api_key,
                api_base=api_base,
                model=model,
            )
            result = postprocess.postprocess(
                result,
                artist_blacklist,
                database,
                target_safety=task["safety"],
                max_rating=task["max_rating"],
                max_tags=task.get("max_tags"),
                anchor_tags=anchor_tags if attempt > 0 else None,
            )
            missing_anchors = (
                result.get("postprocess_log", {})
                .get("version_1", {})
                .get("anti_convergence", {})
                .get("missing_anchors", [])
            )
            if not missing_anchors:
                break
            if attempt + 1 < max_anchor_attempts:
                anchor_retry = True
                task["forced_tags"] = (
                    (task.get("forced_tags") or "") + ", " + ", ".join(missing_anchors)
                ).strip(", ")
        # r18 模式占位符：V2 精修保持占位符版本输入（避免 V2 模型按禁词规则改写露骨词），
        # 最后统一将占位符还原为真实 r18 tag。
        ph_map = task.get("r18_placeholder_map") or {}
        if v2_enhance:
            v2_res = client.generate_v2_enhance(
                v1_prompt=result["version_1"],
                safety=task["safety"],
                api_key=api_key,
                api_base=api_base,
                model=model,
                temperature=task["temperature"],
                max_tokens=task["max_tokens"],
                timeout=task["timeout"],
                max_parse_retries=task["max_parse_retries"],
                max_rating=task["max_rating"],
                reasoning_effort=task["reasoning_effort"],
            )
            result["version_2"] = v2_res["version_2"]
            result["reasoning"] = v2_res["reasoning"]
            result["raw_v2"] = v2_res["raw"]
        # V1/V2 输出统一还原占位符。
        if ph_map:
            result["version_1"] = client.restore_r18_placeholders(
                result["version_1"], ph_map
            )
            if result.get("version_2"):
                result["version_2"] = client.restore_r18_placeholders(
                    result["version_2"], ph_map
                )
        record = _record_to_jsonl(result, task["sampled"], v2_only, task["focus_text"])
        record["seed"] = task["seed"]
        if anchor_retry:
            record["anchor_retry"] = True
        return {"ok": True, "record": record, "idx": task["idx"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "idx": task["idx"]}


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="random-generator",
        description="DeepSeek 随机提示词生成器",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="生成随机提示词")
    generate_parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="生成提示词的数量（默认：1）",
    )
    generate_parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件路径（默认：<output_dir>/random_prompts.jsonl）",
    )
    generate_parser.add_argument(
        "--v2-only",
        action="store_true",
        help="仅输出震撼美化版（version_2）",
    )
    generate_parser.add_argument(
        "--v2-enhance",
        action="store_true",
        help="对 v1 额外调用一次 API，按 anima V2 规则精修为震撼美化版（version_2）",
    )
    generate_parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="YAML 配置文件路径，覆盖默认配置",
    )
    generate_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="随机种子，用于可复现抽样",
    )
    generate_parser.add_argument(
        "--theme-hint",
        type=str,
        default="",
        help="场景主题提示，直接传递给 DeepSeek",
    )
    generate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅抽样并渲染提示词，不调用 API，输出到 stdout",
    )
    generate_parser.add_argument(
        "--rebuild-pools",
        action="store_true",
        help="重新构建旧版 curated pools 后再生成",
    )
    generate_parser.add_argument(
        "--rebuild-curated",
        action="store_true",
        help="从 CSV 重新构建 curated_tags.yaml 后再生成",
    )
    generate_parser.add_argument(
        "--max-rating",
        type=str,
        default=None,
        choices=config.RATING_ORDER,
        help="允许抽样的最大年龄分级（默认读取 generation_config.yaml 中的 max_rating）",
    )
    generate_parser.add_argument(
        "--min-tags",
        type=int,
        default=None,
        help="最终提示词最少 tag 数量（默认读取 generation_config.yaml 中的 min_tags）",
    )
    generate_parser.add_argument(
        "--max-tags",
        type=int,
        default=None,
        help="最终提示词最多 tag 数量（默认读取 generation_config.yaml 中的 max_tags）",
    )
    generate_parser.add_argument(
        "--subject-control",
        "-s",
        type=str,
        default="",
        help="外部主题/主体控制文本，直接传递给用户模板",
    )
    generate_parser.add_argument(
        "--forced-tags",
        type=str,
        default="",
        help="强制包含的 tag，逗号分隔",
    )
    generate_parser.add_argument(
        "--forbidden-tags",
        type=str,
        default="",
        help="强制排除的 tag，逗号分隔",
    )
    generate_parser.add_argument(
        "--extra-requirements",
        type=str,
        default=None,
        help="用户自定义额外要求，覆盖配置文件中的 extra_requirements",
    )
    generate_parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="DeepSeek API Key（临时覆盖环境变量与配置文件）",
    )
    generate_parser.add_argument(
        "--api-config",
        type=str,
        default=None,
        help="API 平台配置文件路径（YAML，可含 api_key/api_base/model）；优先级低于 --api-key/--api-base/--model",
    )
    generate_parser.add_argument(
        "--api-base",
        type=str,
        default=None,
        help="DeepSeek API Base URL（临时覆盖环境变量与配置文件）",
    )
    generate_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="DeepSeek 模型名称（临时覆盖模型名）",
    )
    generate_parser.add_argument(
        "--character-json",
        type=str,
        default=None,
        help="自定义角色池 JSON 文件路径；格式与 character_pool.json 相同，启用后将替代默认角色池",
    )
    generate_parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="并发调用 DeepSeek API 的 worker 数量（默认：4）",
    )

    args = parser.parse_args(argv)

    if args.command != "generate":
        return 0

    if args.count <= 0:
        parser.error("--count 必须大于 0")

    (
        knowledge_sample_counts,
        deepseek_cfg,
        output_dir,
        focus_weights,
        max_rating,
        min_tags,
        max_tags,
        extra_requirements,
        extra_requirements_pool,
        character_whitelist,
        category_whitelists,
        character_pool,
        multi_character_cfg,
        min_r18_tags_per_sample,
        r18_instructions,
        r18_topic_control,
        default_word_quota,
        creative_anchors_cfg,
    ) = _build_config(args)
    api_key, api_base, model, profile_temperature = _resolve_api_profile(args)
    # API 配置文件可显式指定 temperature；null 表示不发送该参数（适配
    # 不支持 temperature 的代理平台）。此处按"键是否存在"判断，避免 null 被忽略。
    if args.api_config:
        _profile = _load_yaml_config(args.api_config)
        if "temperature" in _profile:
            deepseek_cfg["temperature"] = _profile.get("temperature")
    output_path = args.output or os.path.join(output_dir, "random_prompts.jsonl")

    # v2 精修开关：命令行 --v2-enhance 优先，其次 generation_config.yaml / 用户配置。
    v2_enhance = bool(
        args.v2_enhance
        or _load_generation_config().get("v2_enhance", False)
        or _load_yaml_config(args.config).get("v2_enhance", False)
    )

    if args.seed is not None:
        random.seed(args.seed)

    database = retrieval.load_tag_database(config.TAG_SOURCE_FILE)
    artist_blacklist = retrieval.build_artist_blacklist(
        config.ARTIST_BLACKLIST_FILES[0],
        config.ARTIST_BLACKLIST_FILES[1],
    )

    # 旧版 curated pools 仍可通过 --rebuild-pools 维护。
    if args.rebuild_pools:
        print("正在重建 curated pools...")
        pools = retrieval.build_curated_pools(
            database,
            top_n=500,
            blacklist=artist_blacklist,
            output_path=config.CURATED_POOLS_FILE,
        )
        print(f"已保存到 {config.CURATED_POOLS_FILE}")
    elif config.CURATED_POOLS_FILE.exists():
        pools = retrieval.load_curated_pools(config.CURATED_POOLS_FILE)
    else:
        pools = None

    # 新版带 age-rating 的 curated tags 是默认采样源。
    if args.rebuild_curated:
        print("正在重建 curated_tags.yaml...")
        from .tools.build_curated_tags import build_curated_tags, save_curated_tags

        curated_tags = build_curated_tags(top_n=500)
        save_curated_tags(curated_tags)
        print(f"已保存到 {config.CURATED_TAGS_FILE}")
    elif config.CURATED_TAGS_FILE.exists():
        curated_tags = retrieval.load_curated_tags(config.CURATED_TAGS_FILE)
    else:
        print("未找到 curated_tags.yaml，正在从 CSV 构建...")
        from .tools.build_curated_tags import build_curated_tags, save_curated_tags

        curated_tags = build_curated_tags(top_n=500)
        save_curated_tags(curated_tags)
        print(f"已保存到 {config.CURATED_TAGS_FILE}")

    rating_map = _build_rating_map(curated_tags)

    # 默认使用知识库 v1 作为采样源。
    knowledge_database = retrieval.load_knowledge_v1_database()
    print("正在预过滤知识库...")
    knowledge_database = retrieval.build_filtered_knowledge_database(
        knowledge_database,
        curated_tags,
        max_rating=max_rating,
    )
    print(f"知识库预过滤完成，共 {sum(len(v) for v in knowledge_database.values())} 条可用 tag。")

    # 创意锚点池（高概念设定，打破场景/动作/道具趋同）。
    creative_anchors: dict[str, list[dict]] = {}
    if creative_anchors_cfg.get("enabled", True):
        creative_anchors = retrieval.load_creative_anchors(
            creative_anchors_cfg.get("file") or config.CREATIVE_ANCHORS_FILE
        )
    if creative_anchors:
        print(
            f"创意锚点池已加载：{sum(len(v) for v in creative_anchors.values())} "
            f"个锚点 / {len(creative_anchors)} 类。"
        )
    else:
        print("创意锚点池未启用或未找到，跳过 creative_anchor 抽样。")

    forced_tags = [
        tag.strip()
        for tag in (args.forced_tags or "").split(",")
        if tag.strip()
    ]
    forbidden_tags = [
        tag.strip()
        for tag in (args.forbidden_tags or "").split(",")
        if tag.strip()
    ]

    records: list[dict[str, Any]] = []

    # 当生成多条时，避免每次抽样都重置种子导致结果重复；
    # 仅在单条生成时透传 seed 以保证单次可复现。
    sample_seed = args.seed if args.count == 1 else None

    # 非 dry-run 时提前打开输出文件，循环内逐条写入并 flush，防止进度丢失。
    jsonl_handle = None
    txt_handle = None
    if not args.dry_run:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        jsonl_handle = Path(output_path).open("a", encoding="utf-8")
        txt_path = str(Path(output_path).with_suffix(".txt"))
        txt_handle = Path(txt_path).open("a", encoding="utf-8")

    try:
        # dry-run 仅做抽样与提示词渲染，不走并发。
        if args.dry_run:
            for idx in range(args.count):
                sampled = retrieval.sample_from_knowledge_v1(
                    knowledge_database,
                    knowledge_sample_counts,
                    curated_tags,
                    seed=sample_seed,
                    max_rating=max_rating,
                    character_whitelist=character_whitelist,
                    category_whitelists=category_whitelists,
                    character_pool=character_pool,
                    pre_filtered=True,
                    min_r18_tags=min_r18_tags_per_sample,
                    r18_topic_control=r18_topic_control,
                    multi_character_cfg=multi_character_cfg,
                    default_word_quota=default_word_quota,
                    creative_anchors=creative_anchors,
                )
                payload = assembler.build_prompt_payload(
                    sampled, max_rating=max_rating
                )
                sampled_text = assembler.format_tags_for_llm(payload)

                # r18 模式：将 r18 tag 替换为占位符，避免 LLM 输出层拒绝露骨词。
                r18_placeholder_map: dict[int, str] = {}
                if max_rating in ("r18", "r18g") and min_r18_tags_per_sample > 0:
                    sampled_text, r18_placeholder_map = client.assign_r18_placeholders(
                        sampled_text, _collect_r18_tags(sampled, rating_map)
                    )

                is_multi = _is_multi_character(sampled_text)
                eff_min_tags, eff_max_tags, eff_focus_text = _resolve_sample_constraints(
                    is_multi, min_tags, max_tags, focus_weights, multi_character_cfg
                )

                character_tag = (
                    sampled["character_series"][0]["tag"]
                    if sampled.get("character_series")
                    else ""
                )

                character_pool_info = None
                if (
                    sampled.get("character_series")
                    and sampled["character_series"][0].get("source") == "character_pool"
                    and character_pool.get("use_core_appearance", True)
                ):
                    probability = float(character_pool.get("use_core_clothing_probability", 0.5))
                    clothing_strategy = "core_mixed" if random.random() < probability else "sampled_only"
                    character_pool_info = {
                        "characters": [
                            {
                                "tag": item["tag"],
                                "series_tag": item.get("series_tag", ""),
                                "core_appearance_tags": list(item.get("core_appearance_tags", [])),
                                "core_clothing_tags": list(item.get("core_clothing_tags", [])),
                            }
                            for item in sampled["character_series"]
                            if item.get("source") == "character_pool"
                        ],
                        "clothing_strategy": clothing_strategy,
                    }

                if not character_pool_info:
                    character_pool_info = _build_fallback_character_pool_info(
                        sampled_text, character_tag, sampled
                    )

                safety = _determine_safety(sampled)

                if args.extra_requirements is None and extra_requirements_pool.get("enabled", False):
                    current_extra_requirements = sample_extra_requirements(extra_requirements_pool)
                else:
                    current_extra_requirements = extra_requirements

                print(f"=== 样本 {idx + 1}/{args.count} ===")
                print("按类别抽样统计：")
                for category, items in sampled.items():
                    print(f"  {category}: {len(items)} tags")
                if category_whitelists.get("enabled"):
                    for category, pool in category_whitelists.get("pools", {}).items():
                        if pool:
                            print(f"使用白名单池 [{category}]: {pool}")
                if character_whitelist.get("enabled") and character_whitelist.get("pool"):
                    print(f"\n使用白名单角色池：{character_whitelist['pool']}")
                print("\ncharacter_tag:", character_tag or "（无）")
                if is_multi:
                    print(
                        f"[多角色触发] tag 数量区间 {min_tags}~{max_tags} -> "
                        f"{eff_min_tags}~{eff_max_tags}"
                        f"{f'，focus: {eff_focus_text}' if eff_focus_text else ''}"
                    )
                print("\n抽样标签：")
                print(sampled_text)
                if r18_placeholder_map:
                    print(
                        f"\n[r18 占位符映射] {len(r18_placeholder_map)} 个 r18 tag "
                        "已替换为占位符（渲染后自动还原）："
                    )
                    for placeholder, tag in sorted(r18_placeholder_map.items()):
                        print(f"  {placeholder} -> {tag}")
                print("\n冲突消解日志：")
                if payload["conflict_log"]:
                    for entry in payload["conflict_log"]:
                        rule = entry["rule"]
                        kept = entry.get("kept_tags") or entry.get("kept_tag")
                        print(
                            f"  - [{rule.get('type')}] "
                            f"dropped={entry.get('dropped_tags', [])}, kept={kept}, "
                            f"reason={rule.get('reason')}"
                        )
                else:
                    print("  （无冲突）")
                print("\n渲染后的用户提示词：")
                user_prompt = client.render_user_prompt(
                    sampled_tags_text=sampled_text,
                    safety=safety,
                    min_tags=eff_min_tags,
                    max_tags=eff_max_tags,
                    theme_hint=args.theme_hint,
                    focus_text=eff_focus_text,
                    subject_control=args.subject_control,
                    forced_tags=forced_tags,
                    forbidden_tags=forbidden_tags,
                    character_tag=character_tag,
                    max_rating=max_rating,
                    extra_requirements=current_extra_requirements,
                    character_pool_info=character_pool_info,
                    placeholder_meanings=(
                        client.build_placeholder_meanings(r18_placeholder_map)
                        if r18_placeholder_map
                        else None
                    ),
                    creative_anchor_info=payload.get("creative_anchor_info"),
                )
                print(user_prompt)
                print()
                _print_progress(idx + 1, args.count, dry_run=True)
            return 0

        # 在线程外顺序完成抽样，避免 random 模块竞争并保证结果可复现。
        tasks: list[dict[str, Any]] = []
        for idx in range(args.count):
            # 每条样本使用独立随机种子，便于复现与调试。
            # 单条且显式 --seed 时使用指定值，否则为每条生成独立种子。
            if args.count == 1 and args.seed is not None:
                task_seed = args.seed
            else:
                task_seed = random.randint(0, 2**32 - 1)
            random.seed(task_seed)
            sampled = retrieval.sample_from_knowledge_v1(
                knowledge_database,
                knowledge_sample_counts,
                curated_tags,
                seed=None,  # 已由上方 random.seed(task_seed) 控制本条随机性
                max_rating=max_rating,
                character_whitelist=character_whitelist,
                category_whitelists=category_whitelists,
                character_pool=character_pool,
                pre_filtered=True,
                min_r18_tags=min_r18_tags_per_sample,
                r18_topic_control=r18_topic_control,
                multi_character_cfg=multi_character_cfg,
                default_word_quota=default_word_quota,
                creative_anchors=creative_anchors,
            )
            payload = assembler.build_prompt_payload(sampled, max_rating=max_rating)
            sampled_text = assembler.format_tags_for_llm(payload)

            # r18 模式：将 r18 tag 替换为占位符，避免 LLM 输出层拒绝露骨词；
            # 输出后在 _generate_one_task 中按映射还原真实 tag。
            r18_placeholder_map: dict[int, str] = {}
            if max_rating in ("r18", "r18g") and min_r18_tags_per_sample > 0:
                sampled_text, r18_placeholder_map = client.assign_r18_placeholders(
                    sampled_text, _collect_r18_tags(sampled, rating_map)
                )

            is_multi = _is_multi_character(sampled_text)
            eff_min_tags, eff_max_tags, eff_focus_text = _resolve_sample_constraints(
                is_multi, min_tags, max_tags, focus_weights, multi_character_cfg
            )

            character_tag = (
                sampled["character_series"][0]["tag"]
                if sampled.get("character_series")
                else ""
            )

            character_pool_info = None
            if (
                sampled.get("character_series")
                and sampled["character_series"][0].get("source") == "character_pool"
                and character_pool.get("use_core_appearance", True)
            ):
                probability = float(character_pool.get("use_core_clothing_probability", 0.5))
                clothing_strategy = "core_mixed" if random.random() < probability else "sampled_only"
                character_pool_info = {
                        "characters": [
                            {
                                "tag": item["tag"],
                                "series_tag": item.get("series_tag", ""),
                                "core_appearance_tags": list(item.get("core_appearance_tags", [])),
                                "core_clothing_tags": list(item.get("core_clothing_tags", [])),
                            }
                            for item in sampled["character_series"]
                            if item.get("source") == "character_pool"
                        ],
                        "clothing_strategy": clothing_strategy,
                    }

            if not character_pool_info:
                character_pool_info = _build_fallback_character_pool_info(
                    sampled_text, character_tag, sampled
                )

            safety = _determine_safety(sampled)

            if args.extra_requirements is None and extra_requirements_pool.get("enabled", False):
                current_extra_requirements = sample_extra_requirements(extra_requirements_pool)
            else:
                current_extra_requirements = extra_requirements

            tasks.append(
                {
                    "idx": idx,
                    "seed": task_seed,
                    "sampled": sampled,
                    "sampled_text": sampled_text,
                    "character_tag": character_tag,
                    "character_pool_info": character_pool_info,
                    "safety": safety,
                    "extra_requirements": current_extra_requirements,
                    "min_tags": eff_min_tags,
                    "max_tags": eff_max_tags,
                    "theme_hint": args.theme_hint,
                    "focus_text": eff_focus_text,
                    "subject_control": args.subject_control,
                    "forced_tags": forced_tags,
                    "forbidden_tags": forbidden_tags,
                    "max_rating": max_rating,
                    "r18_instructions": r18_instructions,
                    "r18_placeholder_map": r18_placeholder_map,
                    "placeholder_meanings": (
                        client.build_placeholder_meanings(r18_placeholder_map)
                        if r18_placeholder_map
                        else None
                    ),
                    "temperature": deepseek_cfg.get("temperature", 0.7),
                    "max_tokens": deepseek_cfg.get("max_tokens", 2000),
                    "timeout": deepseek_cfg.get("timeout", 120),
                    "max_parse_retries": deepseek_cfg.get("max_parse_retries", 2),
                    "reasoning_effort": deepseek_cfg.get("reasoning_effort"),
                    "creative_anchor_info": payload.get("creative_anchor_info"),
                }
            )
            if (idx + 1) % 500 == 0 or idx + 1 == args.count:
                print(f"已准备 {idx + 1}/{args.count} 条抽样任务...")

        # 并发调用 API 与后处理；抽样已在主线程完成，避免线程安全问题。
        write_lock = threading.Lock()
        failed_count = 0
        executor = ThreadPoolExecutor(max_workers=args.workers)
        futures = [
            executor.submit(
                _generate_one_task,
                task,
                api_key,
                api_base,
                model,
                artist_blacklist,
                database,
                args.v2_only,
                v2_enhance,
            )
            for task in tasks
        ]
        try:
            for future in futures:
                try:
                    res = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    print(f"\n第 ? 条生成失败: {exc}")
                    continue

                if not res["ok"]:
                    failed_count += 1
                    print(f"\n第 {res['idx'] + 1} 条生成失败: {res['error']}")
                    continue

                record = res["record"]
                records.append(record)

                # 文件写入与进度打印加锁，保证多线程下输出顺序正确。
                with write_lock:
                    if jsonl_handle is not None:
                        jsonl_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        jsonl_handle.flush()
                    if txt_handle is not None:
                        # v2 已关闭，txt 侧车输出 version_1（原只写 version_2）。
                        version_1 = record.get("version_1", "")
                        if version_1:
                            txt_handle.write(version_1 + "\n")
                            txt_handle.flush()
                    _print_progress(len(records) + failed_count, args.count, dry_run=False)
        except KeyboardInterrupt:
            print("\n收到中断信号，正在取消未完成任务...")
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=False)
    finally:
        if jsonl_handle is not None:
            jsonl_handle.close()
        if txt_handle is not None:
            txt_handle.close()

    if not args.dry_run:
        print(f"\n已追加保存 {len(records)} 条提示词到 {output_path}")
        txt_path = str(Path(output_path).with_suffix(".txt"))
        print(f"已追加保存 {len(records)} 条纯文本提示词到 {txt_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
