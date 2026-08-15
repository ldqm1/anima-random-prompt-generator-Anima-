"""从 Excel 角色表构建结构化角色池缓存。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import config


# 常见服饰关键词兜底集合（小写空格形式）。
FALLBACK_CLOTHING_TAGS: set[str] = {
    "sleeves", "detached sleeves", "witch hat", "mob cap", "maid headdress",
    "maid", "naval uniform", "hair bow", "hair ribbon", "hair tubes",
    "hairband", "hat", "cape", "dress", "skirt", "shirt", "panties", "bra",
    "socks", "thighhighs", "legwear", "gloves", "necktie", "bowtie",
    "ribbon", "bow", "apron", "uniform", "serafuku", "school uniform",
    "bodysuit", "leotard", "bikini", "swimsuit", "kimono", "yukata",
    "hoodie", "jacket", "coat", "cardigan", "sweater", "vest", "blazer",
    "t-shirt", "sleeveless", "bare shoulders", "off shoulder", "strapless",
    "backless", "halterneck", "collar", "choker", "scarf", "belt", "sash",
    "armor", "capelet", "cloak", "robe", "hood", "long sleeves", "short sleeves",
    "puffy sleeves", "wide sleeves", "detached collar", "sailor collar",
    "white shirt", "black shirt", "collared shirt", "dress shirt", "open shirt",
    "sleeveless shirt", "crop top", "turtleneck", "open jacket", "black jacket",
    "white jacket", "blue jacket", "black dress", "white dress", "red dress",
    "blue dress", "frilled dress", "short dress", "sleeveless dress", "wedding dress",
    "black skirt", "white skirt", "red skirt", "blue skirt", "pleated skirt",
    "miniskirt", "plaid skirt", "black gloves", "white gloves", "elbow gloves",
    "fingerless gloves", "black thighhighs", "white thighhighs", "black pantyhose",
    "white pantyhose", "black socks", "white socks", "kneehighs", "thigh boots",
    "black footwear", "white footwear", "brown footwear", "high heels", "boots",
    "shoes", "sandals", "hair ornament", "headwear", "hair accessory",
    "hair flower", "hairclip", "headband", "black bow", "white bow", "red bow",
    "blue bow", "black ribbon", "white ribbon", "red ribbon", "necklace",
    "bracelet", "ring", "earrings", "jewelry", "neck ribbon", "neckerchief",
    "ascot", "fur trim", "clothing cutout", "see-through clothes", "torn clothes",
    "alternate costume", "official alternate costume", "partially clothed",
    "chinese clothes", "japanese clothes", "military uniform", "naval uniform",
    "cat ears", "rabbit ears", "fox ears", "fake animal ears", "animal ear fluff",
    "wolf ears", "dog ears", "deer ears", "bunny ears", "barefoot", "no shoes",
    "no bra", "no panties", "underwear", "no clothes", "nude", "completely nude",
    "topless", "bottomless", "bare body", "fully exposed", "partially undressed",
}


_KNOWLEDGE_V1_LINE_RE = re.compile(
    r"^\[DOMAIN:标签\]\s+\[CAT:([^\]]+)\]\s+(.+?)\s+\|\s+(.*)$"
)


def _normalize_tag(tag: str) -> str:
    """统一 tag 格式：小写、下划线/连字符转空格、去除首尾空白。"""
    return tag.strip().replace("\\", "").replace("_", " ").replace("-", " ").lower()


def _parse_knowledge_v1_line(line: str) -> dict[str, str] | None:
    """解析知识库 v1 的单行 tag 记录。"""
    line = line.strip()
    if not line:
        return None
    match = _KNOWLEDGE_V1_LINE_RE.match(line)
    if not match:
        return None
    cat_field = match.group(1).strip()
    english = match.group(2).strip()
    if not english:
        return None
    return {
        "category_path": cat_field,
        "tag": english,
    }


def build_clothing_tag_set(clothing_file: Path | None = None) -> set[str]:
    """从服饰知识库文件构建服饰 tag 归一化集合。

    读取 ``知识库/v1/tags_服饰.txt`` 中所有 ``CAT:服饰/...`` 下的英文 tag，
    并合并额外的常见服饰关键词兜底集合。
    """
    clothing_set: set[str] = set(FALLBACK_CLOTHING_TAGS)
    path = clothing_file or config.KNOWLEDGE_V1_DIR / "tags_服饰.txt"
    if not path.exists():
        return clothing_set

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            parsed = _parse_knowledge_v1_line(line)
            if not parsed:
                continue
            cat_path = parsed["category_path"]
            if not cat_path.startswith("服饰"):
                continue
            normalized = _normalize_tag(parsed["tag"])
            if normalized:
                clothing_set.add(normalized)

    return clothing_set


def split_appearance_tags(
    raw: str,
    clothing_set: set[str],
) -> tuple[list[str], list[str]]:
    """将核心外貌描写提示词拆分为外貌 tag 与服饰 tag。

    Args:
        raw: Excel 单元格中的原始文本，逗号分隔。
        clothing_set: 归一化后的服饰 tag 集合。

    Returns:
        (core_appearance_tags, core_clothing_tags)，均保留原始大小写与空格形式。
    """
    appearance_tags: list[str] = []
    clothing_tags: list[str] = []
    for part in raw.split(","):
        tag = part.strip().replace("\\", "")
        if not tag:
            continue
        normalized = _normalize_tag(tag)
        if normalized in clothing_set:
            clothing_tags.append(tag)
        else:
            appearance_tags.append(tag)
    return appearance_tags, clothing_tags


# 男性角色判定标记（小写空格形式）。
_MALE_TAGS: set[str] = {
    "1boy",
    "male focus",
    "male",
    "beard",
    "facial hair",
    "manly",
}

# 全局人数/性别 tag，不应作为单个角色的 core_appearance_tags 注入 prompt。
_GLOBAL_COUNT_GENDER_TAGS: set[str] = {
    "1girl",
    "2girls",
    "3girls",
    "1boy",
    "2boys",
    "3boys",
    "multiple girls",
    "multiple boys",
}


def _is_male_character(core_appearance_tags: list[str]) -> bool:
    """根据核心外貌 tag 判定是否为男性角色。"""
    for tag in core_appearance_tags:
        if _normalize_tag(tag) in _MALE_TAGS:
            return True
    return False


def _filter_global_count_gender_tags(tags: list[str]) -> list[str]:
    """移除全局人数/性别 tag，避免与全局 count/gender 控制冲突。"""
    return [tag for tag in tags if _normalize_tag(tag) not in _GLOBAL_COUNT_GENDER_TAGS]


def build_character_pool(
    excel_path: Path | None = None,
    clothing_file: Path | None = None,
) -> list[dict[str, Any]]:
    """读取 Excel 角色表并构建结构化角色池。"""
    import pandas as pd

    excel_path = excel_path or (
        config.SOURCE_DIR / "D站200图以上角色及作品名单 翻译 角色外貌描写词.xlsx"
    )
    clothing_set = build_clothing_tag_set(clothing_file)

    df = pd.read_excel(excel_path)
    required_columns = {
        "角色中文译名名",
        "角色英文名",
        "作品中文译名",
        "作品英文名",
        "角色触发词",
        "角色核心外貌描写提示词",
    }
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Excel 缺少必要列: {missing}")

    pool: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        character_tag = str(row["角色英文名"]).strip()
        series_tag = str(row["作品英文名"]).strip()
        series_name_cn = str(row["作品中文译名"]).strip() if pd.notna(row["作品中文译名"]) else ""
        if not character_tag or not series_tag:
            continue

        trigger_raw = str(row["角色触发词"]) if pd.notna(row["角色触发词"]) else ""
        trigger_tags = [
            tag.strip().replace("\\", "")
            for tag in trigger_raw.split(",")
            if tag.strip()
        ]

        core_raw = str(row["角色核心外貌描写提示词"]) if pd.notna(row["角色核心外貌描写提示词"]) else ""
        core_appearance_tags, core_clothing_tags = split_appearance_tags(
            core_raw, clothing_set
        )
        is_male = _is_male_character(core_appearance_tags)
        core_appearance_tags = _filter_global_count_gender_tags(core_appearance_tags)

        pool.append(
            {
                "character_tag": character_tag,
                "series_tag": series_tag,
                "series_name_cn": series_name_cn,
                "trigger_tags": trigger_tags,
                "core_appearance_tags": core_appearance_tags,
                "core_clothing_tags": core_clothing_tags,
                "is_male": is_male,
            }
        )

    return pool


def save_character_pool(
    pool: list[dict[str, Any]],
    output_path: Path | None = None,
) -> Path:
    """将角色池保存为 JSON 文件。"""
    output_path = output_path or config.CHARACTER_POOL_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    return output_path


def build_series_index(
    pool: list[dict[str, Any]],
    existing_index: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """按 ``series_tag`` 聚合角色池，生成 IP 级索引。

    Args:
        pool: 角色池列表，每条记录应包含 ``series_tag`` 与可选的
            ``series_name_cn`` 字段。
        existing_index: 已存在的索引列表；若提供，则保留其中相同
            ``series_tag`` 的 ``enabled``、``allow_male`` 与 ``weight`` 值。

    Returns:
        先按 ``enabled`` 降序、再按 ``character_count`` 降序排列的
        IP 级索引列表。
    """
    existing_settings: dict[str, dict[str, Any]] = {}
    if existing_index:
        for item in existing_index:
            series_tag = str(item.get("series_tag", "")).strip()
            if not series_tag:
                continue
            existing_settings[series_tag] = {
                "enabled": bool(item.get("enabled", True)),
                "allow_male": bool(item.get("allow_male", True)),
            }
            if "weight" in item:
                existing_settings[series_tag]["weight"] = int(item["weight"])

    by_series: dict[str, dict[str, Any]] = {}
    for role in pool:
        series_tag = str(role.get("series_tag", "")).strip()
        if not series_tag:
            continue
        if series_tag not in by_series:
            by_series[series_tag] = {
                "series_tag": series_tag,
                "series_name_cn": str(role.get("series_name_cn", "")).strip(),
                "character_count": 0,
            }
        by_series[series_tag]["character_count"] += 1
        # 若当前记录携带了中文名且之前为空，则补齐。
        if not by_series[series_tag]["series_name_cn"]:
            name_cn = str(role.get("series_name_cn", "")).strip()
            if name_cn:
                by_series[series_tag]["series_name_cn"] = name_cn

    index: list[dict[str, Any]] = []
    for series_tag, agg in by_series.items():
        settings = existing_settings.get(series_tag, {})
        index.append(
            {
                "series_tag": agg["series_tag"],
                "series_name_cn": agg["series_name_cn"],
                "enabled": settings.get("enabled", True),
                "allow_male": settings.get("allow_male", True),
                "weight": settings.get("weight", config.DEFAULT_CHARACTER_POOL_WEIGHT),
                "character_count": agg["character_count"],
            }
        )

    index.sort(key=lambda item: (-int(item["enabled"]), -item["character_count"]))
    return index


def save_series_index(
    index: list[dict[str, Any]],
    output_path: Path | None = None,
) -> Path:
    """将 IP 级索引保存为 JSON 文件。"""
    output_path = output_path or config.CHARACTER_POOL_SERIES_INDEX_FILE
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return output_path


def main() -> int:
    """命令行入口：构建并保存角色池缓存与 IP 级索引。"""
    pool = build_character_pool()
    output_path = save_character_pool(pool)
    print(f"已生成角色池缓存: {output_path}")
    print(f"角色总数: {len(pool)}")
    if pool:
        sample = pool[0]
        print("示例记录:")
        print(json.dumps(sample, ensure_ascii=False, indent=2))

    # 生成/更新 IP 级索引，保留用户手动修改的开关状态。
    existing_index: list[dict[str, Any]] = []
    if config.CHARACTER_POOL_SERIES_INDEX_FILE.exists():
        try:
            with config.CHARACTER_POOL_SERIES_INDEX_FILE.open(
                "r", encoding="utf-8"
            ) as f:
                existing_index = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing_index = []

    index = build_series_index(pool, existing_index)
    index_path = save_series_index(index)
    print(f"已生成 IP 级索引: {index_path}")
    print(f"IP 总数: {len(index)}")
    if index:
        print("TOP 5 IP:")
        for item in index[:5]:
            print(
                f"  {item['series_tag']} ({item['series_name_cn']}): "
                f"{item['character_count']} 角色"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
