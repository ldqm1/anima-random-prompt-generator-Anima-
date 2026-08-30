"""高级页汉化与章节分组（PySide6 版）。

- ``SECTIONS``：左侧章节导航 —— 逻辑分组（12 章），每章包含若干 yaml 顶层键；
- ``FIELD_NAMES``：叶子字段汉化映射（键 = 英文键名，值 = 中文显示名）；
- ``SECTION_NAMES`` / ``KEY_NAMES``：章节与顶层键中文名；
- ``VALUE_LABELS``：枚举/布尔值的中文标签。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 章节分组（左侧导航）：章节标题 → 该章包含的 yaml 顶层键
# ---------------------------------------------------------------------------
SECTIONS: list[tuple[str, list[str]]] = [
    ("基础设置", ["max_rating", "min_tags", "max_tags", "output_dir", "extra_requirements", "creative_anchors", "min_r18_tags_per_sample"]),
    ("抽样数量", ["sample_counts", "r18_sample_counts"]),
    ("子类配额", ["subcategory_quotas"]),
    ("反趋同词配额", ["default_word_quota"]),
    ("生成侧重点", ["focus_weights", "r18_focus_weights"]),
    ("多角色", ["multi_character"]),
    ("r18 控制", ["r18_topic_control", "r18_instructions"]),
    ("API 参数", ["deepseek"]),
    ("额外要求池", ["extra_requirements_pool"]),
    ("角色池", ["character_pool", "character_whitelist"]),
    ("类别白名单", ["category_whitelists"]),
    ("创意锚点池", ["__anchors__"]),
]

# 顶层键 → 中文名
KEY_NAMES: dict[str, str] = {
    "max_rating": "内容分级上限",
    "min_tags": "最少 tag 数",
    "max_tags": "最多 tag 数",
    "output_dir": "默认输出目录",
    "extra_requirements": "额外要求",
    "creative_anchors": "创意锚点开关",
    "min_r18_tags_per_sample": "r18 最小 tag 数",
    "sample_counts": "抽样数量",
    "r18_sample_counts": "r18 抽样数量",
    "subcategory_quotas": "子类配额",
    "default_word_quota": "反趋同词配额",
    "focus_weights": "生成侧重点",
    "r18_focus_weights": "r18 生成侧重点",
    "multi_character": "多角色",
    "r18_topic_control": "r18 主题控制",
    "r18_instructions": "r18 指令",
    "deepseek": "API 参数",
    "extra_requirements_pool": "额外要求池",
    "character_pool": "角色池",
    "character_whitelist": "白名单角色池",
    "category_whitelists": "类别白名单",
}

# ---------------------------------------------------------------------------
# 叶子字段汉化映射（键 = 英文键名，值 = 中文显示名）
# ---------------------------------------------------------------------------
FIELD_NAMES: dict[str, str] = {
    # 通用
    "enabled": "启用",
    "probability": "出现概率",
    "weight": "权重",
    "count": "数量",
    "mode": "模式",
    "min": "最少",
    "max": "最多",
    "file": "文件路径",
    "text": "文本内容",
    "excludes": "互斥项",
    "tags": "配套标签",
    "narrative": "叙事要点",
    "cn": "中文说明",
    "id": "标识",
    "name": "名称",
    "pool": "角色池",
    "skip_probability": "跳过概率",
    "items": "条目",
    # 基础设置
    "temperature": "温度",
    "max_tokens": "最大输出 token",
    "reasoning_effort": "思考模式",
    "timeout": "超时秒数",
    "max_parse_retries": "解析重试次数",
    "tag_count_bonus": "tag 数量加成",
    "focus_character_bonus": "角色权重加成",
    "use_core_appearance": "注入核心外貌",
    "use_core_clothing_probability": "核心服饰概率",
    "prefer_same_ip_for_multiple": "多人同作品优先",
    "series_index_file": "IP 索引文件",
    "linked_topics": "联动主题",
    "link_probability": "联动概率",
    "disabled_topics": "禁用主题",
    "topics": "主题表",
    "solo": "单人场景限制",
    "mutex_groups": "互斥组",
    "optional_items": "可选特效",
    "character": "角色占比",
    "background": "背景占比",
    "r18": "r18 内容占比",
    "other": "其他占比",
    "count_gender": "人数与性别",
    "appearance": "外貌",
    "clothing_state": "服装",
    "pose_action_sex": "姿势动作",
    "expression_reaction": "表情反应",
    "camera_shot": "镜头",
    "scene_environment": "场景环境",
    "detail_mood": "画面质感",
    "creative_anchor": "创意锚点",
    "character_series": "角色系列",
    "soft lighting": "柔光",
    "warm lighting": "暖光",
    "blush": "脸红",
    "cherry blossom": "樱花",
    "park": "公园",
    "window": "窗户",
    "bokeh": "散景",
    "petals": "花瓣",
    "gentle breeze": "微风",
    "golden hour": "黄金时刻",
    "smile": "微笑",
    "cat": "猫",
    "flower": "花",
    "glow": "发光",
    "sparkle": "闪烁",
    "soft focus": "柔焦",
}

# 值标签（枚举）
VALUE_LABELS: dict[str, str] = {
    "none": "关闭",
    "low": "低",
    "medium": "中",
    "high": "高",
    "fixed": "固定出现",
    "probabilistic": "概率出现",
    "weighted": "加权出现",
    "general": "全年龄",
    "pg12": "12+",
    "r15": "15+",
    "r18": "18+",
    "r18g": "18+ 重口",
}

# 反向：中文标签 → 原值（收集回 dict 时用）
VALUE_REVERSE: dict[str, str] = {v: k for k, v in VALUE_LABELS.items()}


def field_label(key: str, fallback: str | None = None) -> str:
    """字段显示名：优先汉化映射，其次原文。"""
    return FIELD_NAMES.get(key, fallback if fallback is not None else key)


def key_label(key: str) -> str:
    """顶层键显示名：优先 KEY_NAMES。"""
    return KEY_NAMES.get(key, key)


def value_label(value: Any) -> Any:
    """值显示：枚举/布尔 → 中文标签；其他原样。"""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str) and value in VALUE_LABELS:
        return VALUE_LABELS[value]
    return value


def value_restore(label: Any, original_type: Any) -> Any:
    """从中文标签还原原值。"""
    if isinstance(original_type, bool):
        if label == "是":
            return True
        if label == "否":
            return False
        return bool(label)
    if isinstance(label, str):
        rev = VALUE_REVERSE.get(label)
        if rev is not None:
            return rev
    return label
