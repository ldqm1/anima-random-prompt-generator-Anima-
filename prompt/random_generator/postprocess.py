"""DeepSeek 输出后处理：画师过滤、禁词替换、来源校验、安全标签注入。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import assembler
from . import config


#: ``anima规则.txt`` Tag 区禁词到替代标签的映射。"""
#: 允许 LLM 为了增强互动/环境嵌入而补充的标签。
_ALLOWED_ADDED_TAGS: frozenset[str] = frozenset(
    {
        "looking at each other",
        "holding hands",
        "wind lifting hair",
        "wind blowing hair",
        "standing on roof edge",
        "sitting on stairs",
        "touching flowers",
        "reaching for flower",
        "holding lantern",
        "sharing an umbrella",
        "whispering",
        "leaning on railing",
        "looking at scenery",
        "girls holding hands",
        "girls whispering",
        "sitting together",
        "touching water surface",
        "looking at shooting star",
        "petals falling",
        "embracing",
        "one hand on other's cheek",
        "holding mug together",
        # v2 生成中常见的互动/环境短 tag
        "pointing at something",
        "sitting in shallow water",
        "snow falling",
        "morning glory blooming",
        "digital clock glowing",
        "glitter in the air",
        "playing lute",
        "watching sunset",
        "lying on table",
        "holding stuffed toy",
        "looking up at purple sky",
        "evening light",
        "holding magic wand",
        "surrounded by beach ball and school bag",
        "lonely expression",
        "sitting in water together",
        "holding lily flowers",
        "sharing a lantern",
        "sitting under tree",
        "touching leaves",
        "eating cake",
        "eating ice cream",
        "sitting on rock",
        "wind blowing hair",
        # v2 生成中常见的互动短 tag
        "leaning on each other",
        "wind blowing through hair",
        "holding tails together",
        "sharing a cake slice",
        "sitting under bare tree",
        "holding pocky together",
        "sharing snacks",
        "playing with paper fan",
        "sitting on fence",
        "walking side by side",
        "back to back",
        "shoulder to shoulder",
        "heads together",
        "whispering to each other",
        "laughing together",
        "eating together",
        "sharing a drink",
        "sharing headphones",
        "holding an umbrella together",
        "sheltering from rain",
        "watching the sunset together",
        "chasing butterflies",
        "catching petals",
        "splashing water",
        "sitting by the window",
        "looking out window",
        "leaning on wall",
        "sitting on railing",
        "standing under tree",
        "lying under tree",
        "reading under tree",
        "napping under tree",
        "touching grass",
        "lying on grass",
        "picking flowers",
        "holding a book together",
    }
)

#: 介质/噪音 meta tag 黑名单（共享定义见 config.NOISE_META_TAGS）。
_NOISE_META_TAGS: frozenset[str] = config.NOISE_META_TAGS

#: 后缀规则（共享定义见 config.NOISE_META_SUFFIXES）。
_NOISE_META_SUFFIXES: tuple[str, ...] = config.NOISE_META_SUFFIXES

#: 反趋同校验词表（与 system_prompt.md §9.5 / user_prompt.jinja 保持一致）。
#: 默认氛围词族：按子串匹配（blush 亦匹配 light blush / cheek blush 等变体）。
_DEFAULT_MOOD_FAMILIES: tuple[str, ...] = (
    "soft lighting",
    "warm lighting",
    "blush",
    "cherry blossom",
    "park",
    "window",
    "bokeh",
    "petals",
    "gentle breeze",
    "golden hour",
    "smile",
    "glow",
    "sparkle",
    "soft focus",
)

#: 景别词（shot size），用于构图完整性检查。
_SHOT_SIZE_WORDS: tuple[str, ...] = (
    "close-up", "upper body", "full body", "wide shot", "extreme close-up",
    "headshot", "cowboy shot", "medium shot", "long shot", "waist-up",
    "knee-high", "bust shot", "portrait", "torso", "three-quarter view",
)

#: 机位/角度词，用于构图完整性检查。
_ANGLE_WORDS: tuple[str, ...] = (
    "from above", "from below", "low angle", "high angle", "bird's-eye view",
    "worm's-eye view", "dutch angle", "from side", "from front", "from behind",
    "pov", "eye level", "over-the-shoulder", "top-down", "rear view", "back view",
)

#: 结构性构图法则词，用于构图完整性检查。
_COMPOSITION_RULE_WORDS: tuple[str, ...] = (
    "rule of thirds", "leading lines", "negative space", "frame-in-frame",
    "midground", "foreground focus", "background focus", "symmetrical composition",
    "diagonal composition", "vanishing point", "foreshortening", "deep focus",
    "silhouette", "vignette",
)

#: 非默认情绪词（惊讶/冷淡/负面等），用于表情多样性检查。
_NON_DEFAULT_EXPRESSION_WORDS: tuple[str, ...] = (
    "surprised", "surprise", "confused", "puzzled", "sad", "angry", "sleepy",
    "serious", "smug", "scared", "frightened", "pensive", "determined",
    "flustered", "exasperated", "crying", "tears", "frown", "glare", "nervous",
    "worried", "excited", "startled", "horrified", "depressed", "deadpan",
    "expressionless", "unamused", "annoyed", "irritated", "embarrassed",
    "sweatdrop", "tired", "yawning", "sigh", "flustered", "shy", "awkward",
)


def _check_anti_convergence(tags: list[str]) -> dict[str, Any]:
    """反趋同软校验：默认词配额 / 构图完整性 / 表情多样性。

    只记录检查结果（不自动删改），供上层决定是否重试。
    """
    text = " ".join(t.lower() for t in tags)
    mood_count: dict[str, int] = {}
    for fam in _DEFAULT_MOOD_FAMILIES:
        mood_count[fam] = text.count(fam)
    overused = [fam for fam, c in mood_count.items() if c > 1]

    has_shot = any(w in text for w in _SHOT_SIZE_WORDS)
    has_angle = any(w in text for w in _ANGLE_WORDS)
    has_rule = any(w in text for w in _COMPOSITION_RULE_WORDS)
    has_non_default = any(w in text for w in _NON_DEFAULT_EXPRESSION_WORDS)

    return {
        "default_word_overuse": overused,
        "has_shot_size": has_shot,
        "has_angle": has_angle,
        "has_composition_rule": has_rule,
        "has_non_default_expression": has_non_default,
        "composition_ok": has_shot or has_angle or has_rule,
        "ok": not overused,
    }


_TAG_REPLACEMENTS: dict[str, list[str]] = {
    "penis": ["erection", "visible bulge", "tented shorts", "bulge"],
    "dick": ["erection", "visible bulge", "tented shorts", "bulge"],
    "cock": ["erection", "visible bulge", "tented shorts", "bulge"],
    "pussy": ["spread legs", "exposed slit", "pink inside", "wet slit", "visible slit"],
    "vagina": ["spread legs", "exposed slit", "pink inside", "wet slit", "visible slit"],
    "cunt": ["spread legs", "exposed slit", "pink inside", "wet slit", "visible slit"],
    "clit": ["spread legs", "exposed slit", "pink inside", "wet slit", "visible slit"],
    "cum": ["white fluid", "sticky liquid", "dripping liquid", "wet", "slick", "lubricant"],
}

#: NL 区禁词到间接氛围/体态描写的映射。
_NL_REPLACEMENTS: dict[str, str] = {
    "penis": "hardened arousal",
    "dick": "hardened arousal",
    "cock": "hardened arousal",
    "pussy": "soft pink folds",
    "vagina": "soft pink folds",
    "cunt": "soft pink folds",
    "clit": "sensitive peak",
    "cum": "thick white fluid",
}

#: 所有替代标签集合，用于后处理阶段的来源校验白名单。
_REPLACEMENT_TAGS: frozenset[str] = frozenset(
    tag for tags in _TAG_REPLACEMENTS.values() for tag in tags
)

#: 自然语言区禁止的清单结构模式。
_NL_FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bone\s+with\b"),
    re.compile(r"\banother\s+with\b"),
    re.compile(r"\bone\s+girl\b"),
    re.compile(r"\banother\s+girl\b"),
    re.compile(r"\bwhile\s+the\s+other\b"),
    re.compile(r"\bone\s+hand\b"),
    re.compile(r"\bthe\s+other\s+hand\b"),
]

#: 自然语言短语最大词数。
_MAX_NL_WORDS: int = 8

#: 判断短句是否像完整英文句子的最小 token 数阈值。
_MIN_NL_TOKENS = 5

#: 常见谓语动词集合，用于辅助判断自然语言句。
_SENTENCE_VERBS: frozenset[str] = frozenset(
    {
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "sit",
        "sits",
        "sat",
        "sitting",
        "stand",
        "stands",
        "stood",
        "standing",
        "lie",
        "lies",
        "lay",
        "lying",
        "kneel",
        "kneels",
        "kneeling",
        "hold",
        "holds",
        "holding",
        "look",
        "looks",
        "looking",
        "gaze",
        "gazes",
        "gazing",
        "stare",
        "stares",
        "staring",
        "watch",
        "watches",
        "watching",
        "see",
        "sees",
        "seeing",
        "feel",
        "feels",
        "feeling",
        "touch",
        "touches",
        "touching",
        "run",
        "runs",
        "running",
        "walk",
        "walks",
        "walking",
        "lean",
        "leans",
        "leaning",
        "rest",
        "rests",
        "resting",
        "breathe",
        "breathes",
        "breathing",
        "gasp",
        "gasps",
        "gasping",
        "moan",
        "moans",
        "moaning",
        "whisper",
        "whispers",
        "whispering",
        "say",
        "says",
        "saying",
        "smile",
        "smiles",
        "smiling",
        "blush",
        "blushes",
        "blushing",
        "tremble",
        "trembles",
        "trembling",
        "shiver",
        "shivers",
        "shivering",
        "arch",
        "arches",
        "arching",
        "curl",
        "curls",
        "curling",
        "spread",
        "spreads",
        "spreading",
        "part",
        "parts",
        "parting",
        "glisten",
        "glistens",
        "glistening",
        "glimmer",
        "glimmers",
        "glimmering",
        "shine",
        "shines",
        "shining",
        "filter",
        "filters",
        "filtering",
        "cast",
        "casts",
        "casting",
        "fall",
        "falls",
        "falling",
        "wrap",
        "wraps",
        "wrapping",
        "cling",
        "clings",
        "clinging",
        "press",
        "presses",
        "pressing",
        "pull",
        "pulls",
        "pulling",
        "push",
        "pushes",
        "pushing",
        "open",
        "opens",
        "opening",
        "close",
        "closes",
        "closing",
        "raise",
        "raises",
        "raising",
        "lower",
        "lowers",
        "lowering",
        "turn",
        "turns",
        "turning",
        "face",
        "faces",
        "facing",
        "reach",
        "reaches",
        "reaching",
    }
)


def _normalize_tag(tag: str) -> str:
    """统一 tag 格式：去空白、下划线转空格、小写。"""
    return tag.strip().replace("_", " ").lower()


def _apply_aesthetic_constraints(tags: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """画面美感约束（输出侧兜底）：

    - 排版/分镜类词（LAYOUT_FRAGMENT_TAGS）：剔除——会把单幅插画变成漫画分格/表情表；
    - 风格/画风画面词（STYLE_VISUAL_TAGS）：同一画面最多保留 1 个，防风格漂移；
    - 表情词族（EMOTION_GROUP_TAGS）：同族只保留 1 个、全样本表情词 ≤ 3，防表情分裂；
    - 现实场所词（SCENE_PLACE_TAGS）：同一画面最多保留 1 个，防"机场+书店+火车站"式场景乱炖
      （自然/水域/天空/幻境词不设限，水中森林/浮空岛等跨组创意保留）。

    返回 ``(过滤后tags, [(原因, 被移除tag)])``；保留顺序遵循原列表（靠前的优先）。
    """
    removed: list[tuple[str, str]] = []
    norm = _normalize_tag

    # 1) 排版词剔除
    kept: list[str] = []
    for t in tags:
        if norm(t) in config.LAYOUT_FRAGMENT_TAGS:
            removed.append(("layout", t))
        else:
            kept.append(t)

    # 2) 风格画面词限 1（保留第一个）
    style_seen = False
    after_style: list[str] = []
    for t in kept:
        if norm(t) in config.STYLE_VISUAL_TAGS:
            if style_seen:
                removed.append(("style", t))
                continue
            style_seen = True
        after_style.append(t)

    # 3) 表情词族互斥（同族只留 1）+ 全样本表情词上限 3
    emotion_groups = config.EMOTION_GROUP_TAGS
    group_used: set[str] = set()
    emotion_total = 0
    after_emotion: list[str] = []
    for t in after_style:
        n = norm(t)
        g = next((g for g, s in emotion_groups.items() if n in s), None)
        if g is not None:
            if g in group_used:
                removed.append(("emotion", t))
                continue
            group_used.add(g)
            emotion_total += 1
            if emotion_total > 3:
                removed.append(("emotion_over", t))
                continue
        after_emotion.append(t)

    # 4) 现实场所词限 1（保留第一个）
    place_seen = False
    final: list[str] = []
    for t in after_emotion:
        if norm(t) in config.SCENE_PLACE_TAGS:
            if place_seen:
                removed.append(("scene", t))
                continue
            place_seen = True
        final.append(t)

    return final, removed


def _filter_natural_language(
    prompt: str,
    db_tags: set[str],
    allowed_nl_tags: set[str],
) -> str:
    """过滤 prompt 中的非法自然语言短语。

    对每个逗号分隔的片段：
    - 若存在于数据库或允许的白名单中，保留；
    - 若看起来像自然语言（>4 词或包含常见谓语动词）：
      - 词数超过 _MAX_NL_WORDS 则删除；
      - 命中 _NL_FORBIDDEN_PATTERNS 则删除；
      - 不在 allowed_nl_tags 中则删除；
      - 否则保留。
    - 其他短片段保留。
    """
    tokens = [t.strip() for t in prompt.split(",") if t.strip()]
    kept: list[str] = []
    for token in tokens:
        normalized = _normalize_tag(token)
        if normalized in db_tags or normalized in allowed_nl_tags:
            kept.append(token)
            continue

        words = token.split()
        looks_like_nl = len(words) > 4 or any(
            w.lower() in _SENTENCE_VERBS for w in words
        )
        if not looks_like_nl:
            kept.append(token)
            continue

        if len(words) > _MAX_NL_WORDS:
            continue
        if any(pattern.search(token.lower()) for pattern in _NL_FORBIDDEN_PATTERNS):
            continue
        if normalized not in allowed_nl_tags:
            continue

        kept.append(token)

    return ", ".join(kept)


def _looks_like_sentence(line: str) -> bool:
    """启发式判断一行是否更像自然语言句子而非 tag 列表。

    规则：
    - 以 ``.`` 结尾的行视为句子；
    - 以大写字母开头、token 数不少于阈值且包含常见谓语动词视为句子；
    - 其余视为 tag 行。
    """
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.endswith("."):
        return True
    if stripped[0].isupper():
        tokens = stripped.split()
        if len(tokens) >= _MIN_NL_TOKENS and any(
            t.lower() in _SENTENCE_VERBS for t in tokens
        ):
            return True
    return False


def _split_inline_prompt(line: str) -> tuple[str, str]:
    """将单行 "tag1, tag2, ... . Sentence1. Sentence2." 拆为 (tag_part, sent_part)。

    规则：查找第一个 ``. ``（句点+空格+大写/数字）分隔；若句点前部分为逗号
    分隔的 tag 列表则拆分，否则整行视为纯句子（返回 ``("", line)``）。
    """
    m = re.search(r"\.\s+(?=[A-Z0-9])", line)
    if not m:
        return "", line
    tag_part = line[: m.start()].strip()
    sent_part = line[m.end():].strip()
    if "," not in tag_part:
        return "", line
    return tag_part, sent_part


def _reconstruct_prompt(tags: list[str], nl_sentences: list[str]) -> str:
    """将 tag 列表与自然语言句子重新组装为 prompt 字符串（单行）。

    分隔规则：
    - ``tag`` 区内部用 ``, `` 连接；
    - ``tag`` 区与首个自然语言句之间用 ``, `` 分隔；
    - 自然语言句之间**只加空格**（每句以句号结尾，天然起分隔作用，不再插入逗号）。

    例如：``1girl, solo, white dress, She smiles gently. Petals drift past.``
    """
    tag_part = ", ".join(tags) if tags else ""
    nl_part = " ".join(nl_sentences) if nl_sentences else ""
    if tag_part and nl_part:
        return tag_part + ", " + nl_part
    return tag_part or nl_part


def split_prompt_sections(prompt: str) -> tuple[list[str], list[str]]:
    """将 prompt 拆分为 tag 区与自然语言区。

    每行被视为一个逻辑组。以 ``.`` 结尾或包含主谓结构的大写长句被归为
    自然语言；其余行按逗号拆分为独立 tag。

    Args:
        prompt: 原始 prompt 字符串。

    Returns:
        ``(tag_tokens, nl_sentences)``，其中 ``tag_tokens`` 为所有 tag 的列表，
        ``nl_sentences`` 为自然语言句子列表。
    """
    tag_tokens: list[str] = []
    nl_sentences: list[str] = []

    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _looks_like_sentence(line):
            # 单行可能同时含 tag 区与句子区（system_prompt 要求单行输出：
            # "tag1, tag2. Sentence1. Sentence2."），先尝试行内拆分。
            tag_part, sent_part = _split_inline_prompt(line)
            if tag_part:
                for token in tag_part.split(","):
                    token = token.strip()
                    if token:
                        tag_tokens.append(token)
            if sent_part:
                for s in re.split(r"(?<=[.!?])\s+", sent_part):
                    s = s.strip()
                    if s:
                        nl_sentences.append(s)
            else:
                # 纯句子行（无内联 tag 区）
                nl_sentences.append(line)
        else:
            for token in line.split(","):
                token = token.strip()
                if token:
                    tag_tokens.append(token)

    return tag_tokens, nl_sentences


def remove_artist_tags(prompt: str, artist_blacklist: set[str]) -> str:
    """从 prompt 中移除画师标签。

    对 tag 区按 token 匹配黑名单（不区分大小写、忽略 ``@`` 前缀）；对自然语言区
    使用整词匹配移除画师名。移除后若出现孤立的 ``@`` 前缀，也会一并清理。

    Args:
        prompt: 原始 prompt。
        artist_blacklist: 归一化后的画师名集合，可包含 ``@`` 前缀。

    Returns:
        清理后的 prompt。
    """
    normalized_blacklist = {
        _normalize_tag(tag.lstrip("@")) for tag in artist_blacklist
    }

    def _clean_nl_line(sentence: str) -> str:
        cleaned = sentence
        # 优先匹配较长的画师名，避免短名被长名覆盖。
        for artist in sorted(artist_blacklist, key=len, reverse=True):
            name = artist.lstrip("@")
            if not name:
                continue
            pattern = re.compile(
                r"(?:@\s*)?\b" + re.escape(name) + r"\b", re.IGNORECASE
            )
            cleaned = pattern.sub("", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
        cleaned = re.sub(r"^\s*,\s*|\s*,\s*$", "", cleaned)
        return cleaned

    lines_out: list[str] = []
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line:
            lines_out.append(raw_line)
            continue

        if _looks_like_sentence(line):
            cleaned = _clean_nl_line(line)
            if cleaned:
                lines_out.append(cleaned)
        else:
            tokens = [t.strip() for t in line.split(",") if t.strip()]
            cleaned_tokens: list[str] = []
            for token in tokens:
                bare = token.lstrip("@").strip()
                if not bare:
                    continue
                if _normalize_tag(bare) in normalized_blacklist:
                    continue
                cleaned_tokens.append(token)
            if cleaned_tokens:
                lines_out.append(", ".join(cleaned_tokens))

    return "\n".join(lines_out)


def apply_filter_rules(prompt: str) -> str:
    """应用解剖学禁词替换。

    - 将 ``anima规则.txt`` 中的禁词在 tag 区替换为允许的替代标签；
    - 在自然语言区将禁词改写为间接氛围/体态描述。

    Args:
        prompt: 原始 prompt。

    Returns:
        过滤后的 prompt。
    """
    lines_out: list[str] = []
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line:
            lines_out.append(raw_line)
            continue

        if _looks_like_sentence(line):
            cleaned = line
            for banned, replacement in _NL_REPLACEMENTS.items():
                pattern = re.compile(
                    r"\b" + re.escape(banned) + r"\b", re.IGNORECASE
                )
                cleaned = pattern.sub(replacement, cleaned)
            lines_out.append(cleaned)
        else:
            tokens = [t.strip() for t in line.split(",") if t.strip()]
            cleaned_tokens: list[str] = []
            for token in tokens:
                normalized = _normalize_tag(token)
                if normalized in _TAG_REPLACEMENTS:
                    cleaned_tokens.extend(_TAG_REPLACEMENTS[normalized][:1])
                else:
                    cleaned_tokens.append(token)
            if cleaned_tokens:
                lines_out.append(", ".join(cleaned_tokens))

    return "\n".join(lines_out)


def _is_noise_meta_tag(normalized: str) -> bool:
    """判断归一化后的 tag 是否为介质/噪音 meta tag（委托 config.is_noise_meta_tag）。"""
    return config.is_noise_meta_tag(normalized)


def remove_noise_meta_tags(prompt: str) -> str:
    """移除 tag 区中的介质/噪音 meta tag（与内容分级无关）。

    仅作用于 tag 行：删除独立命中黑名单（含 `` logo`` / `` text`` 后缀规则）
    的 tag；自然语言句子不受影响。r18 模式跳过禁词替换，但该步仍会执行，
    避免无画面语义的 ``manga cover`` / ``page number`` / ``french text``
    等词进入最终提示词。
    """
    lines_out: list[str] = []
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line:
            lines_out.append(raw_line)
            continue
        if _looks_like_sentence(line):
            lines_out.append(raw_line)
            continue
        tokens = [t.strip() for t in line.split(",") if t.strip()]
        kept = [
            token for token in tokens if not _is_noise_meta_tag(_normalize_tag(token))
        ]
        lines_out.append(", ".join(kept))
    return "\n".join(lines_out)


def validate_tag_sources(
    prompt: str,
    database: dict,
    extra_whitelist: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """校验 prompt 中所有 tag 均可追溯来源。

    将 prompt 拆分为 tag 与自然语言后，仅校验 tag 部分。tag 必须存在于
    ``database`` 或 ``extra_whitelist`` 中。

    Args:
        prompt: 待校验 prompt。
        database: tag 数据库，形如 ``{category: [{"tag": ...}, ...], ...}``。
        extra_whitelist: 额外允许的 tag 集合，如质量前缀、安全标签、替代标签等。

    Returns:
        ``(is_valid, unknown_tags)``。
    """
    extra_whitelist = extra_whitelist or set()
    normalized_whitelist = {_normalize_tag(tag) for tag in extra_whitelist}

    normalized_db_tags: set[str] = set()
    for tags in database.values():
        for item in tags:
            normalized_db_tags.add(_normalize_tag(item["tag"]))

    tag_tokens, _ = split_prompt_sections(prompt)
    unknown_tags: list[str] = []
    for tag in tag_tokens:
        if _normalize_tag(tag) not in normalized_db_tags | normalized_whitelist:
            unknown_tags.append(tag)

    return (not unknown_tags, unknown_tags)


def postprocess(
    result: dict,
    artist_blacklist: set[str],
    database: dict,
    target_safety: str | None = None,
    max_rating: str = "r15",
    max_tags: int | None = None,
    anchor_tags: list[str] | None = None,
) -> dict:
    """对 DeepSeek 输出结果执行后处理流水线。

    依次对 ``version_1`` 与 ``version_2`` 执行：画师标签移除、过滤规则、冲突消解、
    长度截断（可选）、反趋同校验与来源校验。结果字典会新增 ``postprocess_log``
    与 ``unknown_tags`` 键。

    Args:
        result: DeepSeek 输出字典，需包含 ``version_1`` 与 ``version_2``。
        artist_blacklist: 画师黑名单。
        database: tag 数据库，用于来源校验。
        target_safety: 已废弃，保留仅为了兼容旧调用签名。
        max_rating: 内容分级上限；为 ``r18`` 时跳过禁词替换，保留成人内容词。
        max_tags: 可选最终 tag 数上限；超限时按顺序截断尾部多余 tag（保留
            前面的高权重 tag），并在 log 记录截断数量。None 表示不截断。
        anchor_tags: 创意锚点核心 tag 列表；校验输出是否保留（丢失的锚点
            记入 ``anti_convergence.missing_anchors``，供上层决定重试）。

    Returns:
        更新后的结果字典。
    """
    extra_whitelist = _REPLACEMENT_TAGS | _ALLOWED_ADDED_TAGS
    normalized_db_tags: set[str] = set()
    for tags in database.values():
        for item in tags:
            normalized_db_tags.add(_normalize_tag(item["tag"]))

    postprocess_log: dict[str, Any] = {}
    all_unknown: set[str] = set()

    for version in ("version_1", "version_2"):
        prompt = result.get(version)
        if not isinstance(prompt, str):
            continue

        version_log: dict[str, Any] = {}

        # 1. 画师标签移除
        original_tags, _ = split_prompt_sections(prompt)
        after_artist = remove_artist_tags(prompt, artist_blacklist)
        after_artist_tags, _ = split_prompt_sections(after_artist)
        removed = [
            tag
            for tag in original_tags
            if _normalize_tag(tag)
            not in {_normalize_tag(t) for t in after_artist_tags}
        ]
        version_log["artist_removed"] = removed

        # 2. 过滤规则（r18 模式下跳过禁词替换，保留成人内容词）
        if max_rating == "r18":
            filtered = after_artist
            version_log["filter_applied"] = False
            version_log["filter_skipped"] = "r18 模式保留成人内容词"
        else:
            filtered = apply_filter_rules(after_artist)
            version_log["filter_applied"] = True

        # 2.1 介质/噪音 meta tag 移除（独立于分级，r18 模式同样执行）
        before_noise_tags, _ = split_prompt_sections(filtered)
        after_noise = remove_noise_meta_tags(filtered)
        after_noise_tags, _ = split_prompt_sections(after_noise)
        version_log["noise_removed"] = [
            tag
            for tag in before_noise_tags
            if _normalize_tag(tag)
            not in {_normalize_tag(t) for t in after_noise_tags}
        ]
        filtered = after_noise

        # 2.5 自然语言短语过滤（仅作用于 tag 行，保留自然语言句子段落）
        filtered_lines: list[str] = []
        for raw_line in filtered.splitlines():
            line = raw_line.strip()
            if not line or _looks_like_sentence(line):
                filtered_lines.append(raw_line)
            else:
                filtered_lines.append(
                    _filter_natural_language(
                        line, normalized_db_tags, extra_whitelist
                    )
                )
        filtered = "\n".join(filtered_lines)

        # 3. 冲突消解
        tags, nl_sentences = split_prompt_sections(filtered)
        resolved_tags, conflict_log = assembler.resolve_conflicts(
            tags, max_rating=max_rating
        )
        version_log["conflict_log"] = conflict_log

        # 3.1 行内重复 tag 去重（安全操作）
        seen_tags: set[str] = set()
        deduped: list[str] = []
        duplicates_removed: list[str] = []
        for t in resolved_tags:
            key = _normalize_tag(t)
            if key in seen_tags:
                duplicates_removed.append(t)
                continue
            seen_tags.add(key)
            deduped.append(t)
        resolved_tags = deduped
        if duplicates_removed:
            version_log["duplicates_removed"] = duplicates_removed

        # 3.1.0 画面美感约束（输出侧兜底）：
        # 排版词剔除 / 风格词限1 / 表情族互斥+上限 / 现实场所词限1。
        resolved_tags, aesthetic_removed = _apply_aesthetic_constraints(resolved_tags)
        if aesthetic_removed:
            version_log["aesthetic_removed"] = [
                {"rule": rule, "tag": tag} for rule, tag in aesthetic_removed
            ]

        # 3.1.1 长度上限截断（可选）：超限时保留顺序靠前的高权重 tag。
        if max_tags and len(resolved_tags) > max_tags:
            version_log["truncated_to_max_tags"] = len(resolved_tags) - max_tags
            resolved_tags = resolved_tags[:max_tags]

        # 3.2 反趋同软校验（记录到 log，不自动删改）
        version_log["anti_convergence"] = _check_anti_convergence(resolved_tags)

        # 3.3 创意锚点保留校验：锚点核心 tag 必须出现在最终输出中。
        if anchor_tags:
            tag_text = " ".join(_normalize_tag(t) for t in resolved_tags)
            missing = [
                t for t in anchor_tags if _normalize_tag(t) not in tag_text
            ]
            version_log["anti_convergence"]["missing_anchors"] = missing
            version_log["anti_convergence"]["anchor_ok"] = not missing

        final_prompt = _reconstruct_prompt(resolved_tags, nl_sentences)
        result[version] = final_prompt

        # 4. 来源校验
        is_valid, unknown = validate_tag_sources(
            final_prompt, database, extra_whitelist=extra_whitelist
        )
        version_log["is_valid"] = is_valid
        version_log["unknown_tags"] = unknown
        all_unknown.update(unknown)

        postprocess_log[version] = version_log

    result["postprocess_log"] = postprocess_log
    result["unknown_tags"] = sorted(all_unknown)
    result.pop("safety", None)

    return result


if __name__ == "__main__":
    # 硬编码冒烟测试数据
    sample_database: dict[str, list[dict[str, str]]] = {
        "count_gender": [{"tag": "1girl"}, {"tag": "solo"}],
        "appearance": [
            {"tag": "long black hair"},
            {"tag": "purple eyes"},
            {"tag": "medium breasts"},
        ],
        "clothing_state": [{"tag": "no clothes"}],
        "pose_action_sex": [
            {"tag": "sitting"},
            {"tag": "spread legs"},
            {"tag": "white fluid"},
            {"tag": "erection"},
        ],
        "expression_reaction": [
            {"tag": "blush"},
            {"tag": "parted lips"},
            {"tag": "looking at viewer"},
            {"tag": "heavy breathing"},
        ],
        "camera_shot": [
            {"tag": "dutch angle"},
            {"tag": "close-up"},
            {"tag": "from front"},
            {"tag": "from behind"},
        ],
        "scene_environment": [{"tag": "bedroom"}, {"tag": "bed sheets"}],
        "detail_mood": [
            {"tag": "cinematic composition"},
            {"tag": "depth of field"},
            {"tag": "dramatic tension"},
            {"tag": "film grain"},
        ],
    }

    sample_blacklist = {"takamine san", "@takamine san"}

    sample_result = {
        "version_1": (
            "best quality, good quality, score_7, score_8, newest, nsfw,\n"
            "1girl, solo, long black hair, purple eyes, medium breasts,\n"
            "@takamine san, no clothes, sitting, spread legs, sunlight, cum,\n"
            "blush, parted lips, looking at viewer,\n"
            "dutch angle, close-up, from front, from behind,\n"
            "bedroom, bed sheets,\n"
            "cinematic composition, depth of field,\n"
            "Her wet pussy glistens with cum as she sits on the bed."
        ),
        "version_2": (
            "masterpiece, best quality, score_9, newest, highres, absurdres, sensitive,\n"
            "1girl, solo, long black hair, purple eyes, medium breasts,\n"
            "no clothes, sitting, spread legs, rim light,\n"
            "blush, parted lips, looking at viewer, heavy breathing,\n"
            "dutch angle, close-up,\n"
            "bedroom, bed sheets,\n"
            "cinematic composition, depth of field, dramatic tension, film grain,\n"
            "Her erect cock is clearly visible."
        ),
        "reasoning": ["Demonstrate post-processing pipeline."],
    }

    processed = postprocess(
        sample_result,
        sample_blacklist,
        sample_database,
        target_safety="explicit",
    )

    print(json.dumps(processed, indent=2, ensure_ascii=False))
