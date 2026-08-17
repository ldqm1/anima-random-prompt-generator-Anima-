"""知识库与 CSV 数据源检索、抽样、画师黑名单构建。"""

from __future__ import annotations

import csv
import functools
import json
import math
import random
import re
from pathlib import Path
from typing import Any

import yaml

from . import config


# 预编译排除正则，避免每次重复编译。
_COMPILED_EXCLUDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern) for pattern in config.EXCLUDE_PATTERNS
]


@functools.lru_cache(maxsize=None)
def _normalize_tag(tag: str) -> str:
    """统一 tag 的空白/下划线/连字符格式，用于比较。

    将下划线与连字符替换为空格，去除首尾空白并转小写。
    使用 lru_cache 避免在抽样循环中重复规范化同一 tag。
    """
    return tag.strip().replace("_", " ").replace("-", " ").lower()


#: 男性相关词正则，用于少女向过滤。
_MALE_MATURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b\d+boys?\b"),
    re.compile(r"\bboy\b"),
    re.compile(r"\bboys\b"),
    re.compile(r"\b\d*males?\b"),
    re.compile(r"\b\d*men\b"),
    re.compile(r"\b\d*man\b"),
    re.compile(r"\bfather\b"),
    re.compile(r"\buncle\b"),
    re.compile(r"\bgrandfather\b"),
    re.compile(r"\bhusband\b"),
    re.compile(r"\bgentleman\b"),
    re.compile(r"\bshota\b"),
    re.compile(r"\btrap\b"),
    re.compile(r"\bfemboy\b"),
    re.compile(r"\bcuntboy\b"),
    re.compile(r"\bdickgirl\b"),
    re.compile(r"\bfutanari\b"),
    re.compile(r"\bfuta\b"),
    re.compile(r"\bbara\b"),
    re.compile(r"\bshemale\b"),
    re.compile(r"\bgynomorph\b"),
    re.compile(r"\bandromorph\b"),
    re.compile(r"\bintersex\b"),
    re.compile(r"\bsweaty[- ]?boy\b"),
    re.compile(r"\bherm\b"),
    re.compile(r"\bhermaphrodite\b"),
    re.compile(r"\bbeard\b"),
    re.compile(r"\bbearded\b"),
    re.compile(r"\bfacial hair\b"),
    re.compile(r"\bpectorals\b"),
    re.compile(r"\bpectoral\b"),
    re.compile(r"\bmuscular male\b"),
    re.compile(r"\bmuscular man\b"),
    re.compile(r"\bmuscular men\b"),
    re.compile(r"[- ]kun\b"),
    re.compile(r"\bon human\b"),
]


@functools.lru_cache(maxsize=None)
def _is_female_only_tag_normalized(normalized: str) -> bool:
    """检查规范化后的 tag 是否包含男性或成熟女性含义。

    返回 True 表示该 tag 适合少女向生成，False 表示应排除。
    """
    for pattern in _MALE_MATURE_PATTERNS:
        if pattern.search(normalized):
            return False
    return True


def _is_female_only_tag(tag: str) -> bool:
    """检查 tag 是否包含男性或成熟女性含义。"""
    return _is_female_only_tag_normalized(_normalize_tag(tag))


#: 纯兽人/非人/深肤/非人肤色相关词正则。
# 允许兽耳、兽尾、角（头饰）与翅膀等穿戴/装饰类兽类特征，
# 仅排除完整兽人、深/非人肤色、鸟类/鱼类/爬行类等明显非人形态。
_NON_HUMAN_PATTERNS: list[re.Pattern[str]] = [
    # 深肤色/黑色皮肤 + 非人肤色（明确奇幻肤色）；保留 white/brown/tan 等人类常见肤色。
    re.compile(r"\b(very )?dark[- ]?skin(ned)?\b"),
    re.compile(r"\bblack[- ]?skin(ned)?\b"),
    re.compile(r"\bdark[- ]?skinned\b"),
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray)[- ]?skin(ned)?\b"),
    # 非人毛发/体表
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray|white|brown|tan|black)[- ]?fur\b"),
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray|white|brown|tan|black)[- ]?body\b"),
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray|white|brown|tan|black)[- ]?scales?\b"),
    re.compile(r"\bmulticolored[- ]?(skin|fur|body|scales?)\b"),
    re.compile(r"\btwo[- ]?tone[- ]?(skin|fur|body)\b"),
    # 兽人/非人形态
    re.compile(r"\banthro\b"),
    re.compile(r"\bfurry\b"),
    re.compile(r"\bkemono\b"),
    re.compile(r"\btaur\b"),
    re.compile(r"\banimal head\b"),
    re.compile(r"\bwerewolf\b"),
    re.compile(r"\bmuzzle\b"),
    re.compile(r"\bsnout\b"),
    re.compile(r"\bbeak\b"),
    re.compile(r"\bscaly\b"),
    re.compile(r"\bhoof\b"),
    re.compile(r"\bhooves\b"),
    re.compile(r"\bhooved\b"),
    re.compile(r"\bfurred\b"),
    re.compile(r"\bskunk girl\b"),
    re.compile(r"\bgator girl\b"),
    re.compile(r"\bcrocodilian\b"),
    # 非可爱/野性动物娘（保留猫/狗/狐/狼/兔/鹿等常见兽耳娘）
    re.compile(r"\bfish[- ]?tail\b"),
    re.compile(r"\bmermaid\b"),
    re.compile(r"\bfull[- ]?body[- ]?fur\b"),
    re.compile(r"\bfur[- ]?covered\b"),
    re.compile(r"\bdetailed fur\b"),
    re.compile(r"\brealistic fur\b"),
    re.compile(r"\bwet fur\b"),
    re.compile(r"\bdry fur\b"),
    re.compile(r"\bfluffy fur\b"),
    re.compile(r"\bsoft fur\b"),
    re.compile(r"\bneck fur\b"),
    re.compile(r"\bchest fur\b"),
    re.compile(r"\bbody fur\b"),
    re.compile(r"\bmonotone fur\b"),
    re.compile(r"\bmulti[- ]?colored fur\b"),
    re.compile(r"\bmulti[- ]?tone fur\b"),
    re.compile(r"\bmulti[- ]?leg\b"),
    re.compile(r"\bmultiple legs\b"),
    re.compile(r"\bextra leg\b"),
    re.compile(r"\bextra legs\b"),
    re.compile(r"\bscaled\b"),
    re.compile(r"\bfeathered\b"),
    re.compile(r"\bferal\b"),
    re.compile(r"\bspotted[- ]?skin\b"),
    re.compile(r"\b\d+ toes?\b"),
    re.compile(r"\bsimple eyes\b"),
    # 其他常见非人/畸形肢体与体表
    re.compile(r"\b(spotted|striped|multicolored|two[- ]?tone)[- ]?(leg|legs|arm|arms|body|skin)\b"),
    re.compile(r"\b\d+[- ]?arms?\b"),
    re.compile(r"\bextra[- ]?arms?\b"),
    re.compile(r"\bmultiple[- ]?arms?\b"),
    re.compile(r"\bmulti[- ]?arms?\b"),
    re.compile(r"\bbody[- ]?hair\b"),
    re.compile(r"\bchest[- ]?hair\b"),
    re.compile(r"\bthick[- ]?chest[- ]?hair\b"),
    re.compile(r"\bleg[- ]?hair\b"),
    re.compile(r"\b\d+[- ]?eyes?\b"),
    re.compile(r"\bextra[- ]?eyes?\b"),
    re.compile(r"\bmultiple[- ]?eyes?\b"),
    re.compile(r"\b(heart|star|animal)[- ]?nose\b"),
    re.compile(r"\b(black|dark|blue|green|red|purple|pink|orange|yellow|grey|gray|brown|tan|white)[- ]?nose\b"),
    re.compile(r"\b(snake|lizard|bird|fish|shark|frog|insect|animal)[- ]?mouth\b"),
    re.compile(r"\bcephalopod[- ]?eyes?\b"),
    re.compile(r"\bfiery[- ]?hair\b"),
    re.compile(r"\bflaming[- ]?hair\b"),
    re.compile(r"\bfeather[- ]?hair\b"),
    re.compile(r"\balternate[- ]?skin[- ]?color\b"),
    re.compile(r"\bmerman\b"),
    re.compile(r"\bmerfolk\b"),
    re.compile(r"\bdetached[- ]?(hair|ahoge|bangs|sidelocks)\b"),
    re.compile(r"\bmane[- ]?hair\b"),
    re.compile(r"\bno[- ]?feet\b"),
    re.compile(r"\bcountershade[- ]?(hands?|feet|foot|body|face|torso)\b"),
    re.compile(r"\bstomach[- ]?hair\b"),
    re.compile(r"\babdominal[- ]?hair\b"),
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray|brown|tan|black|white)[- ]?feet\b"),
    re.compile(r"\b(blue|green|red|purple|pink|orange|yellow|grey|gray|brown|tan|black|white)[- ]?foot\b"),
    re.compile(r"\b(huge|large|big|small|tiny)[- ]?feet\b"),
    re.compile(r"\b(huge|large|big|small|tiny)[- ]?foot\b"),
    re.compile(r"\b(metal|metallic|chrome|steel|iron|gold|silver)[- ]?skin\b"),
    re.compile(r"\bcybernetic[- ]?(leg|arm|hand|foot|eye|body)\b"),
    re.compile(r"\bmechanical[- ]?(leg|arm|hand|foot|eye|body)\b"),
    re.compile(r"\b(prosthetic|robotic)[- ]?(leg|arm|hand|foot|eye|body)\b"),
    re.compile(r"\b\d+[- ]?legs?\b"),
    re.compile(r"\bextra[- ]?legs?\b"),
    re.compile(r"\bmultiple[- ]?legs?\b"),
    re.compile(r"\bshort[- ]?fur\b"),
    re.compile(r"\blong[- ]?fur\b"),
    re.compile(r"\bscuted\b"),
    re.compile(r"\bwinged[- ]?(arm|leg|body)s?\b"),
    re.compile(r"\bhairy[- ]?legs?\b"),
    re.compile(r"\bdirty[- ]?feet\b"),
    re.compile(r"\bforearm[- ]?hair\b"),
    re.compile(r"\bcrotch[- ]?shot\b"),
    re.compile(r"\bnotquitehuman\b"),
    re.compile(r"\bmulti[- ]?mouth\b"),
    re.compile(r"\bflabby[- ]?arms?\b"),
    re.compile(r"\bwrinkled[- ]?skin\b"),
    re.compile(r"\bhumanoid\b"),
    re.compile(r"\bprotogen\b"),
    re.compile(r"\bbawdy\b"),
    re.compile(r"\bmissing[- ]?leg\b"),
    re.compile(r"\bstitched[- ]?(eye|face)\b"),
    re.compile(r"\btalking to pred\b"),
    re.compile(r"\barm[- ]?hair\b"),
    re.compile(r"\bmultiple[- ]?hands?\b"),
    re.compile(r"\bskeletal[- ]?(hand|hands|arm|arms)\b"),
    re.compile(r"\bholding[- ]?(cigar|whip)\b"),
    re.compile(r"\bbruise[- ]?on[- ]?face\b"),
    re.compile(r"\bbad[- ]?leg\b"),
    re.compile(r"\banimal[- ]?nose\b"),
    re.compile(r"\bno[- ]?nose\b"),
    re.compile(r"\bfaceless\b"),
    re.compile(r"\bextra[- ]?ears\b"),
    re.compile(r"\bfeatureless face\b"),
    re.compile(r"\btaur\b"),
    # 非少女向/怪物化外貌细节
    re.compile(r"\bleaf hair\b"),
    re.compile(r"\bliving hair\b"),
    re.compile(r"\bliving (clothes|weapon|plant|flower|bow|ribbon)\b"),
    re.compile(r"\bfeather hands?\b"),
    re.compile(r"\bhand hair\b"),
    re.compile(r"\bpaw (shoes|boots|gloves)\b"),
    re.compile(r"\bevil eyes?\b"),
    re.compile(r"\bvertical bar eyes?\b"),
    re.compile(r"\bsharp fangs?\b"),
    re.compile(r"\bfangs out\b"),
    re.compile(r"\bmonotone feet\b"),
    re.compile(r"\bplanted legs?\b"),
    re.compile(r"\bprehensile[- ]?hair\b"),
    re.compile(r"\b(blank|empty|solid circle|dashed|dotted|line|button|stitched)[- ]?eyes?\b"),
    re.compile(r"\b(wishbone|hair)[- ]?mouth\b"),
    re.compile(r"\bsucker face\b"),
    re.compile(r"\b(black|blood|colored)[- ]?tears?\b"),
    re.compile(r"\bcrying blood\b"),
    re.compile(r"\b(vacant|false|painful|creepy)[- ]?smile\b"),
    re.compile(r"\bthird eye\b"),
    re.compile(r"\bear eyes\b"),
    re.compile(r"\bcheek bulge\b"),
    re.compile(r"\bneck blush\b"),
    re.compile(r"\bbig nose\b"),
    re.compile(r"\bhuge mouth\b"),
    re.compile(r"\b(huge|puffy|thick)[- ]?lips?\b"),
    re.compile(r"\bkissy face\b"),
    re.compile(r"\bnotquitehuman\b"),
    re.compile(r"\bhumanoid\b"),
    re.compile(r"\bprotogen\b"),
    re.compile(r"\bbawdy\b"),
    # 本轮 dry-run 中新发现的非人/畸形/非少女向 tag
    re.compile(r"\bx[- ]?navel\b"),
    re.compile(r"\bsparse[- ]?navel[- ]?hair\b"),
    re.compile(r"\bx[- ]?arms?\b"),
    re.compile(r"\bextra[- ]?mouth\b"),
    re.compile(r"\bderp[- ]?eyes?\b"),
    re.compile(r"\bdevilish[- ]?grin\b"),
    re.compile(r"\bcigarette\b"),
    re.compile(r"\bx[- ]?ray[- ]?view\b"),
    re.compile(r"\bfake[- ]?box[- ]?art\b"),
    re.compile(r"\bsad[- ]?cat[- ]?dance\b"),
    re.compile(r"\bsad[- ]?zarya\b"),
    re.compile(r"\bv ap art\b"),
    re.compile(r"\bchina[- ]?comic\b"),
    re.compile(r"\bholding[- ]?skull\b"),
    re.compile(r"\bsword[- ]?of[- ]?hisou\b"),
    re.compile(r"\bpleading[- ]?face[- ]?emoji\b"),
    re.compile(r"\blaughing[- ]?at\b"),
    re.compile(r"\bclock eyes?\b"),
    re.compile(r"\bdot mouth\b"),
    re.compile(r"\byurie mouth\b"),
    re.compile(r"\beye in mouth\b"),
    re.compile(r"\blipstick mark on face\b"),
    re.compile(r"\bsweaty abs\b"),
    re.compile(r"\bstated young\b"),
    re.compile(r"\bside sitting split\b"),
    re.compile(r"\binvisible chair\b"),
    re.compile(r"\bplant pred\b"),
    re.compile(r"\bboned meat\b"),
    re.compile(r"\bdusk ball\b"),
    re.compile(r"\bblue drop\b"),
    re.compile(r"\bbitesize art\b"),
    re.compile(r"\bslorp art\b"),
    re.compile(r"\bfleischer style toon\b"),
    re.compile(r"\btaut shirt\b"),
    re.compile(r"\bo-ring top\b"),
    re.compile(r"\bpant suit\b"),
    re.compile(r"\bpride color patch\b"),
    re.compile(r"\bpet food\b"),
    re.compile(r"\bhospital bed\b"),
    re.compile(r"\bcountershade[- ]?legs?\b"),
    re.compile(r"\b(red|blue|green|purple|pink|orange|yellow|grey|gray|black|white|brown|tan)[- ]?arms?\b"),
    re.compile(r"\b(red|blue|green|purple|pink|orange|yellow|grey|gray|black|white|brown|tan)[- ]?legs?\b"),
    re.compile(r"\b(aqua|teal|cyan|magenta|violet|indigo|lavender|coral|salmon|rose|lilac|plum|mint|charcoal|ash|maroon|burgundy|navy|olive|mustard)[- ]?skin\b"),
    re.compile(r"\b(brown|teal|aqua|cyan|magenta|violet|indigo|lavender|coral|salmon|rose|lilac|plum|mint|charcoal|ash|maroon|burgundy|navy|olive|mustard)[- ]?(mouth|lips|face)\b"),
    re.compile(r"\bhuge hands?\b"),
    re.compile(r"\bslutty[- ]?face\b"),
    re.compile(r"\badult[- ]?on[- ]?baby\b"),
    re.compile(r"\bdetached[- ]?arm\b"),
    re.compile(r"\bmechanical[- ]?tail\b"),
    re.compile(r"\btroll[- ]?face\b"),
    re.compile(r"\bvent[- ]?art\b"),
    re.compile(r"\blow[- ]?res[- ]?art\b"),
    re.compile(r"\bart\.eje\b"),
    re.compile(r"\billustration\.media\b"),
    re.compile(r"\bpet[- ]?bowl\b"),
    re.compile(r"\bobject[- ]?shot\b"),
    re.compile(r"\bholding[- ]?with[- ]?feet\b"),
    re.compile(r"\barrow[- ]?in[- ]?body\b"),
    re.compile(r"\bconvenient[- ]?leg\b"),
    re.compile(r"\bfat[- ]?arms?\b"),
    re.compile(r"\bgoogly[- ]?eyes?\b"),
    re.compile(r"\bhand[- ]?on[- ]?another's[- ]?leg\b"),
    re.compile(r"\bhand[- ]?on[- ]?another's[- ]?arm\b"),
    re.compile(r"\bgrabbing[- ]?another's[- ]?arm\b"),
    re.compile(r"\bfisheye\b"),
    re.compile(r"\bfused[- ]?legs?\b"),
    re.compile(r"\bwhite[- ]?lips?\b"),
    re.compile(r"\bthick[- ]?arms?\b"),
    re.compile(r"\bamerican[- ]?flag[- ]?dress\b"),
    re.compile(r"\bunderwear[- ]?only\b"),
    re.compile(r"\bpog[- ]?face\b"),
    re.compile(r"\bpainted[- ]?on[- ]?face\b"),
    re.compile(r"\bmayhem[- ]?art\b"),
    re.compile(r"\bholding[- ]?riding[- ]?crop\b"),
    re.compile(r"\bhair[- ]?hand\b"),
    re.compile(r"\bneck[- ]?bulge\b"),
    re.compile(r"\bdreamworks[- ]?smirk\b"),
    re.compile(r"\bcreepy[- ]?face\b"),
    re.compile(r"\bbodily[- ]?fluids[- ]?from[- ]?mouth\b"),
    re.compile(r"\bunusual[- ]?tears?\b"),
    re.compile(r"\bmechanical[- ]?(leg|arm|hand|foot|eye|body)s?\b"),
    # 本轮生成后残留的非人/非少女向 tag
    re.compile(r"\bneck[- ]?gills?\b"),
    re.compile(r"\bdeep[- ]?skin\b"),
    re.compile(r"\bflaming[- ]?eyes?\b"),
    re.compile(r"\bpale[- ]?fur\b"),
    re.compile(r"\bswimsuit[- ]?aside\b"),
    re.compile(r"\bbimbo[- ]?lips?\b"),
    re.compile(r"\bholding[- ]?down\b"),
    re.compile(r"\bwide[- ]?spread[- ]?legs?\b"),
    re.compile(r"\bslapping\b"),
    re.compile(r"\btwintails[- ]?day\b"),
    re.compile(r"\bpiranha[- ]?plant\b"),
    re.compile(r"\bsea[- ]?eagle\b"),
    re.compile(r"\b(grey|gray|yellow)[- ]?lips?\b"),
    re.compile(r"\blight[- ]?mouth\b"),
]


@functools.lru_cache(maxsize=None)
def _is_human_like_tag_normalized(normalized: str) -> bool:
    """检查规范化后的 tag 是否暗示纯兽人/非人或深肤。

    返回 True 表示适合“人类少女 + 允许兽耳/兽尾/角”的生成目标，False 表示应排除。
    """
    for pattern in _NON_HUMAN_PATTERNS:
        if pattern.search(normalized):
            return False
    return True


def _is_human_like_tag(tag: str) -> bool:
    """检查 tag 是否暗示纯兽人/非人或深肤。"""
    return _is_human_like_tag_normalized(_normalize_tag(tag))


def _build_rating_map(curated_tags: dict[str, list[dict]] | str | Path) -> dict[str, str]:
    """从 curated_tags 构建 tag -> rating 映射。"""
    if isinstance(curated_tags, (str, Path)):
        curated_tags = load_curated_tags(curated_tags)

    rating_map: dict[str, str] = {}
    for items in curated_tags.values():
        for item in items:
            tag = (item.get("tag") or "").strip()
            if not tag:
                continue
            rating_map[_normalize_tag(tag)] = (item.get("rating") or "general").strip()
    return rating_map


def _rating_ok(tag: str, rating_map: dict[str, str], max_rating: str) -> bool:
    """判断 tag 的年龄分级是否在允许范围内。"""
    max_index = config.RATING_ORDER.index(max_rating)
    rating = rating_map.get(_normalize_tag(tag), "general")
    return config.RATING_ORDER.index(rating) <= max_index


@functools.lru_cache(maxsize=None)
def _load_semantic_exclude() -> tuple[frozenset[str], frozenset[str]]:
    """加载语义排除清单。

    返回 ``(always, r18g_tier)`` 两个规范化 tag 集合：
    - ``always``：所有模式一律排除（男性特征/器官、非人形态、武器、皮肤瑕疵等）；
    - ``r18g_tier``：仅低于 r18g 的分级排除（猎奇/死亡/尸骸/生肉/吞食等 r18g 级
      内容），r18g 模式放行。

    清单仅作用于未入池的知识库残留 tag；入池 tag（curated_tags.yaml）按语义
    人工/审核判定，不受本清单影响。
    """
    always: set[str] = set()
    r18g_tier: set[str] = set()
    path = Path(config.SEMANTIC_EXCLUDE_FILE)
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("always", []) or []:
            if isinstance(item, dict):
                tag = _normalize_tag(str(item.get("tag", "")))
                if tag:
                    always.add(tag)
        for item in data.get("r18g_tier", []) or []:
            if isinstance(item, dict):
                tag = _normalize_tag(str(item.get("tag", "")))
                if tag:
                    r18g_tier.add(tag)
    return frozenset(always), frozenset(r18g_tier)


def _is_semantically_excluded(tag: str, max_rating: str | None) -> bool:
    """语义排除清单判定（仅针对未入池 tag）。

    ``always`` 集合在所有模式一律排除；``r18g_tier`` 仅在低于 r18g 的分级下
    排除（与 max_rating=r18 自动排除 r18g 的评级体系保持一致）。
    """
    always, r18g_tier = _load_semantic_exclude()
    normalized = _normalize_tag(tag)
    if normalized in always:
        return True
    if normalized in r18g_tier and max_rating != "r18g":
        return True
    return False


def _tag_passes_filters(
    tag: str,
    category: str | None,
    rating_map: dict[str, str],
    max_rating: str,
    classified_kb: bool = False,
) -> bool:
    """判断单个 tag 是否通过采样前的全部清洗规则。

    Args:
        classified_kb: 为 True 表示 tag 来自已人工分类的知识库 v1
            （排除项已改写为 ``排除/<子类>`` CAT，保留项按子类正常保留），
            此时跳过旧正则/精确串/语义清单检查——分类即排除，避免
            ``facial mark``/``cat paws``/``feathered wings`` 等误杀；
            仅保留年龄评级与人数限定。curated 池/旧库等未分类来源仍走旧检查。
    """
    if not _rating_ok(tag, rating_map, max_rating):
        return False
    # 已人工分类的知识库 v1：不再套用旧正则/噪音/语义清单（分类已接管）。
    if classified_kb:
        # 括号消歧检查是精确白名单判定（非模糊正则），保留——
        # 角色/作品 cosplay（如 x (kancolle) (cosplay)）仍须排除。
        if not _is_paren_disambiguated(_normalize_tag(tag)):
            return False
        if (
            category == "count_gender"
            and _normalize_tag(tag) not in config.DEFAULT_COUNT_GENDER_TAGS
        ):
            return False
        return True
    # 介质/噪音 meta tag 无条件排除（对已入池的 curated 池 tag 同样生效，
    # 不依赖「是否入池」判定——噪音词混入 curated 池时会直接进 LLM 输入）。
    if config.is_noise_meta_tag(_normalize_tag(tag)):
        return False
    # 已入池的 tag（rating_map 中）已按语义人工/审核判定，不再套用旧脚本筛选；
    # 仅对未入池的知识库残留 tag 套用「语义排除清单 + 旧脚本防护（男性/非人/噪声）」。
    if _normalize_tag(tag) not in rating_map:
        if _is_semantically_excluded(tag, max_rating):
            return False
        if is_noisy_tag(tag):
            return False
        if not _is_female_only_tag(tag):
            return False
        if not _is_human_like_tag(tag):
            return False
    if (
        category == "count_gender"
        and _normalize_tag(tag) not in config.DEFAULT_COUNT_GENDER_TAGS
    ):
        return False
    return True


def build_filtered_knowledge_database(
    database: dict[str, list[dict]],
    curated_tags: dict[str, list[dict]] | str | Path,
    max_rating: str = "r15",
) -> dict[str, list[dict]]:
    """预过滤知识库，每个类别只保留符合当前分级与清洗规则的 tag。

    该函数应在批量生成前调用一次，避免在每次抽样时重复遍历全部 tag。

    知识库 v1 主池（appearance/clothing/detail/pose/expression/camera/scene
    /count_gender）已人工细粒度分类，排除项改写为 ``排除/<子类>`` CAT，
    分类即排除——此处不再套用旧正则/语义清单（``classified_kb=True``）。
    ``character_series`` 由角色池独立管理（用户确认角色不分类），保留旧检查兜底。
    """
    rating_map = _build_rating_map(curated_tags)
    filtered: dict[str, list[dict]] = {}
    for category, tags in database.items():
        classified_kb = category != "character_series"
        if category == "character_series":
            role_tags = [
                t
                for t in tags
                if t.get("subcategory") == "角色"
                and _tag_passes_filters(
                    t.get("tag", ""), category, rating_map, max_rating,
                    classified_kb=classified_kb,
                )
            ]
            series_tags = [
                t
                for t in tags
                if t.get("subcategory") == "作品"
                and _tag_passes_filters(
                    t.get("tag", ""), category, rating_map, max_rating,
                    classified_kb=classified_kb,
                )
            ]
            filtered[category] = role_tags + series_tags
        else:
            filtered[category] = [
                t
                for t in tags
                if _tag_passes_filters(
                    t.get("tag", ""), category, rating_map, max_rating,
                    classified_kb=classified_kb,
                )
            ]
    return filtered


#: 知识库 v1 单条 tag 行正则。
_KNOWLEDGE_V1_LINE_RE = re.compile(
    r"^\[DOMAIN:标签\]\s+\[CAT:([^\]]+)\]\s+(.+?)\s+\|\s+(.*)$"
)


def parse_knowledge_v1_line(line: str) -> dict | None:
    """解析 ``知识库/v1/*.txt`` 的一行 tag 记录。

    输入格式::

        [DOMAIN:标签] [CAT:category/subcategory] english | chinese

    返回::

        {
            "tag": <english（下划线已转空格）>,
            "chinese": <chinese>,
            "category": <CAT 主类别>,
            "subcategory": <CAT 子类别>,
        }
    """
    line = line.strip()
    if not line:
        return None

    match = _KNOWLEDGE_V1_LINE_RE.match(line)
    if not match:
        return None

    cat_field = match.group(1).strip()
    english = match.group(2).strip()
    chinese = match.group(3).strip()
    if not english:
        return None

    if "/" in cat_field:
        category, subcategory = cat_field.split("/", 1)
    else:
        category, subcategory = cat_field, ""

    # 与 CSV 处理保持一致：下划线视为空格。
    if english.startswith("score_"):
        tag = english
    else:
        tag = english.replace("_", " ")

    return {
        "tag": tag,
        "chinese": chinese,
        "category": category,
        "subcategory": subcategory,
    }


def map_knowledge_v1_to_internal(category: str, subcategory: str) -> str | None:
    """将知识库 v1 的 (category, subcategory) 映射到内部类别。

    - ``二次元角色/角色`` 与 ``二次元角色/作品`` -> ``character_series``
    - ``二次元角色/元数据``、``艺术家``、``无法分类`` -> ``None``
    - 其余复用 ``config.resolve_internal_category``。
    """
    if category == "二次元角色":
        if subcategory in ("角色", "作品"):
            return "character_series"
        return None
    if category in ("艺术家", "无法分类"):
        return None
    return config.resolve_internal_category(category, subcategory)


def load_character_pool(path: str | Path | None = None) -> list[dict[str, Any]]:
    """加载 Excel 角色池 JSON 缓存。

    Args:
        path: 角色池 JSON 路径。为 ``None`` 时使用 ``config.CHARACTER_POOL_FILE``。

    Returns:
        角色记录列表，每条记录包含 ``character_tag``、``series_tag``、
        ``trigger_tags``、``core_appearance_tags``、``core_clothing_tags``。
        记录还可能包含 ``is_male`` 字段，用于男性角色过滤。
    """
    path = Path(path or config.CHARACTER_POOL_FILE)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def load_creative_anchors(path: str | Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """加载创意锚点池 YAML。

    Args:
        path: 锚点池 YAML 路径。为 ``None`` 时使用 ``config.CREATIVE_ANCHORS_FILE``。

    Returns:
        按类别分组的锚点字典，形如 ``{"surreal_scene": [{"id", "name", "cn",
        "tags", "narrative"}, ...], ...}``。
    """
    path = Path(path or config.CREATIVE_ANCHORS_FILE)
    if not path.exists():
        return {}
    import yaml

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: dict[str, list[dict[str, Any]]] = {}
    for cat, items in data.items():
        if isinstance(items, list):
            out[str(cat)] = [
                dict(i) for i in items
                if isinstance(i, dict) and i.get("enabled", True) is not False
            ]
    return out


def load_character_pool_series_index(path: str | Path | None = None) -> list[dict[str, Any]]:
    """加载角色池 IP 级索引。

    Args:
        path: 索引 JSON 路径。为 ``None`` 时使用 ``config.CHARACTER_POOL_SERIES_INDEX_FILE``。

    Returns:
        索引条目列表，条目包含 ``series_tag``、``enabled``、``allow_male`` 等字段。
        若文件不存在或格式错误，返回空列表。
    """
    path = Path(path or config.CHARACTER_POOL_SERIES_INDEX_FILE)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return data


def _parse_character_count(count_gender_tags: list[dict]) -> int:
    """从 count_gender 抽样结果中解析需要抽取的角色数量。

    支持 ``1girl``、``2girls``、``solo``、``duo``、``multiple girls`` 等常见写法。
    若无法解析则默认返回 ``1``。
    """
    if not count_gender_tags:
        return 1

    count = 1
    for item in count_gender_tags:
        tag = _normalize_tag(item.get("tag", ""))
        if not tag:
            continue

        # 数字前缀，如 1girl、2girls、6+girls
        digit_match = re.match(r"^(\d+)\+?(girls?|boys?|others?)\b", tag)
        if digit_match:
            count = max(count, int(digit_match.group(1)))
            continue

        # 常见人数词
        if tag == "solo" or tag == "1other":
            count = max(count, 1)
        elif tag == "duo" or tag == "2others":
            count = max(count, 2)
        elif tag == "trio" or tag == "3others":
            count = max(count, 3)
        elif tag in {"4others", "5others", "6others"}:
            count = max(count, int(tag[0]))
        elif tag == "group":
            count = max(count, 3)
        elif tag == "multiple girls" or tag == "multiple boys" or tag == "multiple others":
            count = max(count, 2)

    return count


#: count_gender 中表示出现男性角色（或异性/混合场景）的标记。
#: 当前系统人数/性别仅支持 1girl/2girls（``config.DEFAULT_COUNT_GENDER_TAGS``），
#: 命中这些标记才允许角色池抽取男性角色，否则一律全局排除。
_MALE_COUNT_GENDER_MARKERS: frozenset[str] = frozenset({
    "1boy",
    "2boys",
    "3boys",
    "4boys",
    "5boys",
    "6+boys",
    "multiple boys",
    "hetero",
    "male focus",
    "male only",
    "mixed",
})


def _scene_allows_male_character(count_gender_tags: list[dict]) -> bool:
    """根据 count_gender 抽样结果判断场景是否允许男性角色。

    Args:
        count_gender_tags: count_gender 类别的抽样结果。

    Returns:
        只要人数/性别中出现男性或异性标记（1boy/2boys/hetero 等）即返回
        ``True``；纯女性场景（1girl/2girls 等）返回 ``False``。
    """
    for item in count_gender_tags:
        if _normalize_tag(item.get("tag", "")) in _MALE_COUNT_GENDER_MARKERS:
            return True
    return False


def _sample_character_pool(
    pool: list[dict[str, Any]],
    num_chars: int,
    prefer_same_ip: bool,
    whitelist: list[Any] | None = None,
    series_index: list[dict[str, Any]] | None = None,
    strict_same_ip: bool = False,
    exclude_male: bool = False,
) -> list[dict[str, Any]]:
    """从角色池中抽样指定数量的角色。

    Args:
        pool: 角色池列表。
        num_chars: 需要抽取的角色数量。
        prefer_same_ip: 是否优先从同一作品中抽取多个角色。
        whitelist: 可选角色白名单，非空时只从名单中筛选。
        series_index: 可选 IP 级索引，非空时只保留 ``enabled=true`` 的 IP，
            并根据 ``allow_male`` 开关过滤男性角色。
        strict_same_ip: 为 ``True`` 时，多角色场景必须来自同一 IP；
            若无法在同 IP 中凑齐 ``num_chars`` 个角色，则返回空列表。
        exclude_male: 为 ``True`` 时，全局排除男性角色（例如单少女场景）。

    Returns:
        抽中的角色记录（含 ``source`` 等附加字段）。
    """
    # 先按 enabled 过滤 IP
    if series_index:
        enabled_series = {
            entry.get("series_tag", "")
            for entry in series_index
            if entry.get("enabled", False)
        }
        pool = [
            role
            for role in pool
            if role.get("series_tag", "") in enabled_series
        ]

    # 构建 IP 权重映射（仅 enabled 的 IP）
    weight_map: dict[str, int] = {}
    if series_index:
        weight_map = {
            entry.get("series_tag", ""): entry.get("weight", config.DEFAULT_CHARACTER_POOL_WEIGHT)
            for entry in series_index
            if entry.get("enabled", False)
        }

    # 再按 allow_male 过滤男性角色
    if series_index:
        allow_male_map = {
            entry.get("series_tag", ""): entry.get("allow_male", True)
            for entry in series_index
        }
        pool = [
            role
            for role in pool
            if allow_male_map.get(role.get("series_tag", ""), True)
            or not role.get("is_male", False)
        ]

    # 单少女场景全局排除男性角色
    if exclude_male:
        pool = [role for role in pool if not role.get("is_male", False)]

    # 最后应用角色白名单
    if whitelist:
        whitelist_norms = {_normalize_tag(str(tag)) for tag in whitelist}
        pool = [
            role
            for role in pool
            if _normalize_tag(role.get("character_tag", "")) in whitelist_norms
        ]

    if not pool:
        return []

    chosen: list[dict[str, Any]] = []
    if prefer_same_ip and num_chars > 1:
        # 按作品分组
        by_series: dict[str, list[dict[str, Any]]] = {}
        for role in pool:
            series = role.get("series_tag", "")
            if not series:
                continue
            by_series.setdefault(series, []).append(role)

        if by_series:
            def _series_weight(series: str) -> float:
                w = weight_map.get(series, config.DEFAULT_CHARACTER_POOL_WEIGHT)
                if w <= 0:
                    return 0.0
                count = len(by_series.get(series, []))
                if count <= 0:
                    return 0.0
                # 使用角色数的对数乘权重，使角色多的 IP 更易被抽到但不至于过度主导。
                return math.log(count) * float(w)

            # strict_same_ip 模式下，只选择拥有足够角色的作品。
            if strict_same_ip:
                eligible_series = [
                    series
                    for series, roles in by_series.items()
                    if len(roles) >= num_chars
                ]
                if not eligible_series:
                    return []
                weights = [_series_weight(s) for s in eligible_series]
                if not any(weights):
                    return []
                series_tag = random.choices(eligible_series, weights=weights, k=1)[0]
            else:
                all_series = list(by_series.keys())
                weights = [_series_weight(s) for s in all_series]
                if not any(weights):
                    return []
                series_tag = random.choices(all_series, weights=weights, k=1)[0]

            series_roles = by_series[series_tag]
            k = min(num_chars, len(series_roles))
            chosen.extend(random.sample(series_roles, k))

            # 非严格模式下，若该作品角色不足，从剩余角色中补充。
            if not strict_same_ip:
                remaining = num_chars - len(chosen)
                if remaining > 0:
                    chosen_tags = {_normalize_tag(r.get("character_tag", "")) for r in chosen}
                    rest = [
                        role
                        for role in pool
                        if _normalize_tag(role.get("character_tag", "")) not in chosen_tags
                    ]
                    k_rest = min(remaining, len(rest))
                    if k_rest > 0:
                        chosen.extend(random.sample(rest, k_rest))
    else:
        k = min(num_chars, len(pool))
        if k > 0:
            chosen.extend(random.sample(pool, k))

    # 转换为统一的抽样结果格式
    result: list[dict[str, Any]] = []
    for role in chosen:
        result.append(
            {
                "tag": role["character_tag"],
                "series_tag": role["series_tag"],
                "trigger_tags": list(role.get("trigger_tags", [])),
                "core_appearance_tags": list(role.get("core_appearance_tags", [])),
                "core_clothing_tags": list(role.get("core_clothing_tags", [])),
                "category": "二次元角色",
                "subcategory": "角色",
                "source": "character_pool",
            }
        )
    return result


def load_knowledge_v1_database(v1_dir: Path | None = None) -> dict[str, list[dict]]:
    """加载 ``知识库/v1`` 并映射到内部类别。

    Args:
        v1_dir: 知识库 v1 目录。若为 ``None``，则使用 ``config.KNOWLEDGE_TAG_FILES``
            中声明的文件；否则读取 ``v1_dir`` 下所有 ``.txt``。

    Returns:
        包含 8 个内部类别 + ``character_series`` 的分组字典。
    """
    target_dir = Path(v1_dir or config.KNOWLEDGE_V1_DIR)

    database: dict[str, list[dict]] = {
        key: [] for key in config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS
    }
    database["character_series"] = []

    if v1_dir is None:
        files_to_read: set[str] = set()
        for files in config.KNOWLEDGE_TAG_FILES.values():
            files_to_read.update(files)
        paths = [target_dir / fname for fname in sorted(files_to_read)]
    else:
        paths = sorted(target_dir.glob("*.txt"))

    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                parsed = parse_knowledge_v1_line(line)
                if not parsed:
                    continue
                internal = map_knowledge_v1_to_internal(
                    parsed["category"], parsed["subcategory"]
                )
                if internal is None or internal not in database:
                    continue
                database[internal].append(parsed)

    return database


def sample_from_knowledge_v1(
    database: dict[str, list[dict]],
    counts: dict[str, int],
    curated_tags: dict[str, list[dict]] | str | Path,
    seed: int | None = None,
    max_rating: str = "r15",
    character_whitelist: dict[str, Any] | None = None,
    category_whitelists: dict[str, Any] | None = None,
    character_pool: dict[str, Any] | None = None,
    pre_filtered: bool = False,
    min_r18_tags: int = 0,
    r18_topic_control: dict[str, Any] | None = None,
    multi_character_cfg: dict[str, Any] | None = None,
    default_word_quota: dict[str, int] | None = None,
    creative_anchors: dict[str, list[dict]] | None = None,
    subcategory_quotas: dict[str, Any] | None = None,
) -> dict[str, list[dict]]:
    """从知识库 v1 中按类别抽样，并应用 R15 过滤与现有清洗规则。

    Args:
        database: ``load_knowledge_v1_database`` 返回的分组数据。
        counts: 每类抽样数量，例如 ``config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS``。
        curated_tags: 已加载的 curated tags 字典，或 ``curated_tags.yaml`` 路径。
        seed: 可选随机种子。
        max_rating: 最大允许分级，默认 ``r15``。
        character_whitelist: 白名单角色池配置；为 None 时使用默认配置。
        category_whitelists: 通用类别白名单池配置；为 None 时使用默认配置。
        character_pool: Excel 角色池配置；为 None 时使用默认配置。
        pre_filtered: 是否已调用 ``build_filtered_knowledge_database`` 对 database
            进行预过滤；为 True 时跳过内部重复过滤以提升批量生成速度。
        min_r18_tags: 仅当 ``max_rating == "r18"`` 时生效。抽样完成后若 r18 评级
            tag 数量不足该值，从各分类剩余 r18 候选（未抽中、通过全部清洗规则）
            中随机补充；候选不足时尽力而为。
        r18_topic_control: r18 标签主题控制配置（仅 ``max_rating`` 为 r18/r18g
            时生效）。结构为 ``{enabled, topics: {主题名: {enabled, mode, count,
            probability, weight, linked_topics, link_probability}}}``。启用后：
            disabled 或概率未命中的主题 tag 在主抽样与 r18 补充中都不出现；
            ``mode: fixed`` 主题保证出现 count 个；其余激活主题按 weight 加权。
            为 None 或未启用时保持原有完全随机行为。
        multi_character_cfg: 多角色配置，结构为 ``{enabled, probability,
            tag_count_bonus, focus_character_bonus}``。``enabled: false`` 时关闭
            双人/多人角色：人数/性别（count_gender）强制为 ``1girl``，后续角色
            抽取与 r18 主题激活都按单人场景处理。``probability``（0-1，默认 0.5）
            即多人角色占比：每条样本按该概率掷骰，命中则 count_gender 为
            ``2girls``，否则为 ``1girl``。为 None 时使用
            ``config.DEFAULT_MULTI_CHARACTER``。

    Returns:
        与 ``counts`` 同结构的抽样结果，每个 tag 字典额外包含 ``source`` 字段。
    """
    if character_whitelist is None:
        character_whitelist = config.DEFAULT_CHARACTER_WHITELIST
    if category_whitelists is None:
        category_whitelists = config.DEFAULT_CATEGORY_WHITELISTS
    if character_pool is None:
        character_pool = config.DEFAULT_CHARACTER_POOL
    if multi_character_cfg is None:
        multi_character_cfg = config.DEFAULT_MULTI_CHARACTER

    # 解析通用类别白名单配置。
    cat_whitelist_enabled = bool(category_whitelists.get("enabled", False))
    cat_whitelist_pools: dict[str, list[Any]] = category_whitelists.get("pools", {}) if cat_whitelist_enabled else {}

    # 解析 Excel 角色池配置。
    pool_enabled = bool(character_pool.get("enabled", False))
    pool_file = character_pool.get("file") or config.CHARACTER_POOL_FILE
    pool_data = load_character_pool(pool_file) if pool_enabled else []
    series_index_file = character_pool.get("series_index_file")
    if series_index_file is None:
        series_index_file = Path(pool_file).with_suffix(".json").with_name(
            Path(pool_file).stem + "_series_index.json"
        )
    series_index = (
        load_character_pool_series_index(series_index_file) if pool_enabled else []
    )
    prefer_same_ip = bool(character_pool.get("prefer_same_ip_for_multiple", True))

    if seed is not None:
        random.seed(seed)

    # 双人/多人角色频率：enabled 关闭 → 恒 1girl；否则按 probability 掷骰决定
    # 本条样本是多人（2girls）还是单人（1girl）——probability 即多人占比。
    # 掷骰放在 seed 之后保证可复现。
    multi_enabled = bool(multi_character_cfg.get("enabled", True))
    multi_probability = min(
        1.0, max(0.0, float(multi_character_cfg.get("probability", 0.5)))
    )
    use_multi = multi_enabled and random.random() < multi_probability
    _allowed_count_gender: frozenset[str] = (
        frozenset({"2girls"}) if use_multi else frozenset({"1girl"})
    )

    if isinstance(curated_tags, (str, Path)):
        curated_tags = load_curated_tags(curated_tags)

    if max_rating not in config.RATING_ORDER:
        raise ValueError(
            f"Invalid max_rating {max_rating!r}; "
            f"expected one of {config.RATING_ORDER}"
        )
    max_index = config.RATING_ORDER.index(max_rating)

    # 若 database 已经 ``build_filtered_knowledge_database`` 预过滤，
    # 则本函数内部不再重复执行耗时清洗。
    rating_map = _build_rating_map(curated_tags)

    # r18 主题控制：先解析配置；激活掷骰延后到人数/性别确定后执行
    # （单人场景按 solo 限制排除部分主题，见 _refresh_r18_topic_ctx）。
    r18_topic_ctx: dict[str, Any] = {"enabled": False}
    r18_topics_cfg: dict[str, dict[str, Any]] = {}
    if max_rating in ("r18", "r18g"):
        enabled, topics_cfg = _resolve_r18_topic_control(r18_topic_control)
        if enabled:
            r18_topics_cfg = topics_cfg

    excluded_norms: set[str] = set()

    def _refresh_r18_topic_ctx() -> None:
        """按当前样本人数/性别刷新 r18 主题激活状态（主抽样与 r18 补充共用）。

        多人场景（2girls 等）不限制；单人场景禁用 ``solo.disabled_topics``
        中列出的主题，其 tag 与未激活主题一并进入 ``excluded_norms``。
        """
        nonlocal r18_topic_ctx, excluded_norms
        if not r18_topics_cfg:
            return
        topic_tag_map = _build_topic_tag_map()
        solo_disabled = _resolve_solo_disabled_topics(
            r18_topic_control, sampled.get("count_gender", [])
        )
        activated, fixed_quotas, excluded_norms = _decide_r18_topic_activation(
            r18_topics_cfg, topic_tag_map, disabled_topics=solo_disabled
        )
        r18_topic_ctx = {
            "enabled": True,
            "topics_cfg": r18_topics_cfg,
            "topic_tag_map": topic_tag_map,
            "activated": activated,
            "fixed_quotas": fixed_quotas,
            "excluded_norms": excluded_norms,
        }

    def _filter_tags(tags: list[dict], category: str | None = None) -> list[dict]:
        if excluded_norms:
            tags = [
                item
                for item in tags
                if _normalize_tag(item.get("tag", "")) not in excluded_norms
            ]
        if pre_filtered:
            # 预过滤库已按「分类即排除」构建（排除项为 排除/<子类> CAT，保留项
            # 已恢复子类）；此处仅按 r18 主题排除，不再套用噪音黑名单——
            # 噪音/元数据词已由 detail 分类（画面/元数据 配额）与人工保留判定接管。
            return list(tags)
        # 非预过滤路径：知识库 v1 已人工分类，跳过旧正则/语义清单（分类已接管）。
        return [
            item
            for item in tags
            if _tag_passes_filters(
                item.get("tag", ""), category, rating_map, max_rating,
                classified_kb=category != "character_series",
            )
        ]

    def _with_source(item: dict) -> dict:
        copied = dict(item)
        copied["source"] = "knowledge_v1"
        return copied

    sampled: dict[str, list[dict]] = {}

    # 预抽样人数/性别与角色：角色抽样可能把多人场景降级为单人
    # （同 IP 角色不足时降级为 1girl），须先确定最终人数/性别，
    # 再决定 r18 主题激活（单人场景按 solo 限制排除部分主题）。
    for category in ("count_gender", "character_series"):
        n = counts.get(category, 0)
        if n <= 0:
            sampled[category] = []
            continue

        # 人数/性别只抽 1 个，从 1girl/2girls 中随机决定
        if category == "count_gender":
            n = 1

        # 优先使用通用类别白名单池（若已启用且当前类别 pool 非空）。
        whitelist_pool = cat_whitelist_pools.get(category, [])
        if whitelist_pool:
            pool = list(dict.fromkeys(whitelist_pool))
            # 过滤掉明显不适合少女向生成的男性/非人 tag。
            pool = [
                tag for tag in pool
                if _is_female_only_tag(tag) and _is_human_like_tag(tag)
            ]
            # 人数/性别白名单仅保留 1girl/2girls（关闭双人时仅 1girl）
            if category == "count_gender":
                pool = [
                    tag for tag in pool
                    if _normalize_tag(tag) in _allowed_count_gender
                ]
            k = min(n, len(pool))
            sampled[category] = [
                {
                    "tag": tag,
                    "category": category,
                    "subcategory": "whitelist",
                    "source": "category_whitelist",
                }
                for tag in (random.sample(pool, k) if k > 0 else [])
            ]
            continue

        tags = database.get(category, [])
        if category == "character_series":
            # 优先使用 Excel 角色池（若已启用且成功加载）。
            if pool_data:
                num_chars = _parse_character_count(sampled.get("count_gender", []))
                whitelist = cat_whitelist_pools.get("character_series") if cat_whitelist_enabled else None

                if num_chars > 1 and prefer_same_ip:
                    # 严格同 IP 抽样：若某作品角色不足，则降级为 1girl。
                    chosen = _sample_character_pool(
                        pool_data,
                        num_chars,
                        prefer_same_ip,
                        whitelist=whitelist,
                        series_index=series_index,
                        strict_same_ip=True,
                        exclude_male=not _scene_allows_male_character(
                            sampled.get("count_gender", [])
                        ),
                    )
                    if len(chosen) < num_chars:
                        # 同 IP 角色不足，降级为单角色场景。
                        sampled["count_gender"] = [
                            {
                                "tag": "1girl",
                                "category": "count_gender",
                                "subcategory": "人数",
                                "source": "knowledge_v1",
                            }
                        ]
                        num_chars = 1
                        chosen = _sample_character_pool(
                            pool_data,
                            num_chars,
                            False,
                            whitelist=whitelist,
                            series_index=series_index,
                            exclude_male=True,
                        )
                    sampled[category] = chosen
                else:
                    sampled[category] = _sample_character_pool(
                        pool_data,
                        num_chars,
                        prefer_same_ip,
                        whitelist=whitelist,
                        series_index=series_index,
                        exclude_male=not _scene_allows_male_character(
                            sampled.get("count_gender", [])
                        ),
                    )
                continue

            # 如果启用了白名单角色池且 pool 非空，则优先从白名单中抽取。
            if character_whitelist.get("enabled") and character_whitelist.get("pool"):
                pool = list(dict.fromkeys(character_whitelist["pool"]))
                # 过滤掉明显不适合少女向生成的男性/非人角色。
                pool = [
                    role
                    for role in pool
                    if _is_female_only_tag(role) and _is_human_like_tag(role)
                ]
                k = min(n, len(pool))
                chosen: list[dict] = []
                if k:
                    chosen.extend(
                        {
                            "tag": role,
                            "category": "二次元角色",
                            "subcategory": "角色",
                            "source": "character_whitelist",
                        }
                        for role in random.sample(pool, k)
                    )
                sampled[category] = chosen
                continue

            if pre_filtered:
                role_tags = [t for t in tags if t.get("subcategory") == "角色"]
                series_tags = [t for t in tags if t.get("subcategory") == "作品"]
            else:
                role_tags = _filter_tags(
                    [t for t in tags if t.get("subcategory") == "角色"],
                    category=category,
                )
                series_tags = _filter_tags(
                    [t for t in tags if t.get("subcategory") == "作品"],
                    category=category,
                )

            chosen = []
            k_role = min(n, len(role_tags))
            if k_role:
                chosen.extend(_with_source(t) for t in random.sample(role_tags, k_role))

            remaining = n - len(chosen)
            if remaining > 0:
                chosen_norms = {_normalize_tag(t["tag"]) for t in chosen}
                available = [
                    t for t in series_tags
                    if _normalize_tag(t["tag"]) not in chosen_norms
                ]
                k_series = min(remaining, len(available))
                if k_series:
                    chosen.extend(
                        _with_source(t) for t in random.sample(available, k_series)
                    )
            sampled[category] = chosen
        else:
            filtered = _filter_tags(tags, category=category)
            # 未命中多人掷骰 → 人数/性别强制 1girl；命中 → 强制 2girls
            # （预过滤库中本类仅含 1girl/2girls）
            if category == "count_gender":
                filtered = [
                    item for item in filtered
                    if _normalize_tag(item.get("tag", "")) in _allowed_count_gender
                ]
            k = min(n, len(filtered))
            sampled[category] = (
                [_with_source(t) for t in random.sample(filtered, k)] if k > 0 else []
            )

    # 激活决策：依据最终人数/性别刷新 r18 主题激活状态。
    if r18_topics_cfg:
        _refresh_r18_topic_ctx()

    # 主循环：其余类别（count_gender 与 character_series 已在预抽样阶段处理）。
    for category, n in counts.items():
        if n <= 0:
            sampled[category] = []
            continue

        if category in ("count_gender", "character_series"):
            continue

        # 创意锚点：从锚点池随机抽 1-2 个高概念设定（展开 name+tags），
        # 走"forced"语义——LLM 必须保留（模板段另做强制说明）。
        if category == "creative_anchor":
            sampled[category] = _sample_creative_anchors(creative_anchors, n)
            continue

        # 优先使用通用类别白名单池（若已启用且当前类别 pool 非空）。
        whitelist_pool = cat_whitelist_pools.get(category, [])
        if whitelist_pool:
            pool = list(dict.fromkeys(whitelist_pool))
            # 过滤掉明显不适合少女向生成的男性/非人 tag。
            pool = [
                tag for tag in pool
                if _is_female_only_tag(tag) and _is_human_like_tag(tag)
            ]
            k = min(n, len(pool))
            sampled[category] = [
                {
                    "tag": tag,
                    "category": category,
                    "subcategory": "whitelist",
                    "source": "category_whitelist",
                }
                for tag in (random.sample(pool, k) if k > 0 else [])
            ]
            continue

        tags = database.get(category, [])
        filtered = _filter_tags(tags, category=category)
        k = min(n, len(filtered))
        sub_quotas = (subcategory_quotas or {}).get(category)
        if sub_quotas:
            chosen = _sample_with_subcategory_quotas(filtered, k, sub_quotas)
            sampled[category] = [_with_source(t) for t in chosen]
        else:
            sampled[category] = (
                [_with_source(t) for t in random.sample(filtered, k)] if k > 0 else []
            )

    if max_rating == "r18" and min_r18_tags > 0:
        _supplement_r18_tags(
            sampled, database, rating_map, min_r18_tags, pre_filtered, r18_topic_ctx
        )

    if default_word_quota:
        _apply_default_word_quota(sampled, default_word_quota)

    return sampled


def _sub_short(subcategory: str) -> str:
    """取子类短名：'表情动作/微笑喜悦' -> '微笑喜悦'。"""
    return (subcategory or "").rsplit("/", 1)[-1]


def _sample_with_subcategory_quotas(
    candidates: list[dict], k: int, quotas: dict[str, Any]
) -> list[dict]:
    """按子类配额抽样：先满足各子类 min，再从剩余候选（受 max 约束）补足 k 个。

    Args:
        candidates: 候选 item 列表（含 ``subcategory`` 字段）。
        k: 目标抽样数量。
        quotas: ``{子类短名: {"min": int, "max": int}}``；未列出的子类不设限。

    Returns:
        抽样结果列表（未做 _with_source 包装）。
    """
    if not quotas or k <= 0:
        return list(candidates[:k])
    groups: dict[str, list[dict]] = {}
    for item in candidates:
        groups.setdefault(_sub_short(item.get("subcategory", "")), []).append(item)

    chosen: list[dict] = []
    picked: set[int] = set()

    # 1. 各子类 min 配额
    for sc, q in quotas.items():
        n_min = int(q.get("min", 0) or 0)
        pool = [it for it in groups.get(sc, []) if id(it) not in picked]
        take = random.sample(pool, min(n_min, len(pool)))
        for it in take:
            chosen.append(it)
            picked.add(id(it))

    # 2. 剩余名额（受 max 约束）
    remaining = k - len(chosen)
    if remaining > 0:
        # 每个受配额子类最多再贡献 (max - 已选) 个，保证 max 硬约束；
        # 未列入配额的子类不设限。
        capped_pool: list[dict] = []
        for sc, q in quotas.items():
            n_max = int(q.get("max", 1 << 30))
            cur = sum(
                1
                for c in chosen
                if _sub_short(c.get("subcategory", "")) == sc
            )
            cap = max(0, n_max - cur)
            if cap <= 0:
                continue
            pool = [it for it in groups.get(sc, []) if id(it) not in picked]
            capped_pool.extend(random.sample(pool, min(cap, len(pool))))
        unlisted = [
            it
            for it in candidates
            if id(it) not in picked
            and _sub_short(it.get("subcategory", "")) not in quotas
        ]
        pool = capped_pool + unlisted
        take = random.sample(pool, min(remaining, len(pool)))
        chosen.extend(take)

    return chosen


def _sample_creative_anchors(
    anchors: dict[str, list[dict]] | None, k: int
) -> list[dict]:
    """从创意锚点池随机抽取 k 个锚点（跨类别不重复），展开为 tag 条目。

    每个条目包含 ``tag``（锚点核心名）、``anchor_id``/``anchor_cn``/
    ``anchor_tags``/``anchor_narrative`` 元数据，供模板段强制保留与叙事句参考。
    """
    if not anchors or k <= 0:
        return []
    cats = list(anchors.keys())
    chosen: list[dict] = []
    used_ids: set[str] = set()
    attempts = 0
    while len(chosen) < k and attempts < k * 20:
        attempts += 1
        cat = random.choice(cats)
        pool = anchors.get(cat, [])
        if not pool:
            continue
        cand = [a for a in pool if a.get("id") not in used_ids]
        if not cand:
            continue
        a = random.choice(cand)
        used_ids.add(a.get("id", ""))
        tags = [t for t in ([a.get("name", "")] + list(a.get("tags", []))) if t]
        chosen.append(
            {
                "tag": tags[0] if tags else str(a.get("id", "")),
                "category": "creative_anchor",
                "source": "creative_anchor",
                "anchor_id": a.get("id", ""),
                "anchor_cn": a.get("cn", ""),
                "anchor_tags": tags,
                "anchor_narrative": a.get("narrative", ""),
            }
        )
    return chosen


def _apply_default_word_quota(
    sampled: dict[str, list[dict]], quota: dict[str, int]
) -> None:
    """抽样侧默认词帽：同一批内默认词（如 soft lighting/blush/park）出现次数
    超过配额时，随机丢弃多余的，避免同一批样本反复携带同几个默认词。

    直接就地修改 ``sampled``。quota 形如 ``{"soft lighting": 1, "blush": 1, ...}``，
    key 为小写 tag 精确名。
    """
    seen: dict[str, int] = {}
    for category, items in sampled.items():
        kept: list[dict] = []
        for item in items:
            tag = item.get("tag", "") if isinstance(item, dict) else str(item)
            norm = tag.strip().lower()
            limit = quota.get(norm)
            if limit is not None:
                if seen.get(norm, 0) >= limit:
                    continue  # 超过配额，丢弃本批多余的默认词
                seen[norm] = seen.get(norm, 0) + 1
            kept.append(item)
        sampled[category] = kept


def _supplement_r18_tags(
    sampled: dict[str, list[dict]],
    database: dict[str, list[dict]],
    rating_map: dict[str, str],
    min_r18_tags: int,
    pre_filtered: bool,
    r18_topic_ctx: dict[str, Any] | None = None,
) -> None:
    """在 r18 模式下补充指定数量的 r18 评级 tag。

    仅从 ``database`` 中 rating 恰为 ``r18``、未抽中且通过全部清洗规则
    （男性/扶她/福瑞等禁用类别仍会被拦截）的候选里随机补充，直到满足
    ``min_r18_tags`` 或候选耗尽。补充的 tag 归入其原始内部类别，并标记
    ``source="r18_supplement"``。

    ``r18_topic_ctx`` 非空时按主题控制补充（见 ``sample_from_knowledge_v1``）：
    - 未激活主题（disabled / 概率未命中 / 联动未命中）的 tag 全部排除；
    - ``mode: fixed`` 的主题先抽满配额（扣除主抽样已出现的数量），
      即使主抽样已满足 ``min_r18_tags`` 也会补齐缺口；
    - 其余激活主题先各分配 1 个保证名额，再按各自 ``weight`` 加权补足。
    """
    def _is_r18_tag(item: dict) -> bool:
        norm = _normalize_tag(item.get("tag", ""))
        return rating_map.get(norm, "general") == "r18"

    current = sum(
        1
        for items in sampled.values()
        for item in items
        if _is_r18_tag(item)
    )

    # 主题控制启用时，need 至少覆盖未满足的 fixed 配额：
    # 即使主抽样已满足 min_r18_tags，仍要保证 fixed 主题按配额出现。
    topic_tag_map = (r18_topic_ctx or {}).get("topic_tag_map", {})
    current_by_topic: dict[str, int] = {}
    if r18_topic_ctx and r18_topic_ctx.get("enabled"):
        for items in sampled.values():
            for item in items:
                norm = _normalize_tag(item.get("tag", ""))
                if rating_map.get(norm, "general") == "r18":
                    topic = topic_tag_map.get(norm)
                    if topic:
                        current_by_topic[topic] = current_by_topic.get(topic, 0) + 1
        fixed_gap = sum(
            max(0, quota - current_by_topic.get(topic, 0))
            for topic, quota in (r18_topic_ctx.get("fixed_quotas", {}) or {}).items()
        )
        need = max(min_r18_tags - current, fixed_gap)
        if need <= 0:
            return
    else:
        if current >= min_r18_tags:
            return
        need = min_r18_tags - current

    sampled_norms = {
        _normalize_tag(item.get("tag", ""))
        for items in sampled.values()
        for item in items
    }

    excluded_norms = set(r18_topic_ctx.get("excluded_norms", set()) or set())

    candidates: list[tuple[str, dict]] = []
    for category, tags in database.items():
        if category in ("count_gender", "character_series"):
            continue
        for item in tags:
            tag = item.get("tag", "")
            norm = _normalize_tag(tag)
            if norm in sampled_norms:
                continue
            if config.is_noise_meta_tag(norm):
                continue
            if not _is_r18_tag(item):
                continue
            if norm in excluded_norms:
                continue
            if pre_filtered:
                # 预过滤库已通过全部清洗规则，仅需 rating 精确为 r18。
                candidates.append((category, item))
            elif _tag_passes_filters(tag, category, rating_map, "r18"):
                candidates.append((category, item))

    if not candidates:
        return

    if r18_topic_ctx and r18_topic_ctx.get("enabled"):
        picked = _sample_r18_by_topic_control(
            candidates,
            need,
            topics_cfg=r18_topic_ctx.get("topics_cfg", {}),
            activated=r18_topic_ctx.get("activated", set()),
            fixed_quotas=r18_topic_ctx.get("fixed_quotas", {}),
            topic_tag_map=topic_tag_map,
            current_by_topic=current_by_topic,
        )
    else:
        k = min(need, len(candidates))
        picked = random.sample(candidates, k)

    for category, item in picked:
        copied = dict(item)
        copied["source"] = "r18_supplement"
        sampled.setdefault(category, []).append(copied)


@functools.lru_cache(maxsize=None)
def load_r18_topics() -> dict[str, list[str]]:
    """加载 r18 标签主题分类表（r18_topics.yaml）。

    Returns:
        ``{主题名: [tag, ...]}``；文件不存在时返回空字典。
    """
    path = config.R18_TOPICS_FILE
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    result: dict[str, list[str]] = {}
    for topic, tags in data.items():
        if isinstance(tags, list):
            result[str(topic)] = [str(tag) for tag in tags]
    return result


@functools.lru_cache(maxsize=None)
def _build_topic_tag_map() -> dict[str, str]:
    """构建 normalized tag -> 主题名 反向映射（带缓存）。"""
    return {
        _normalize_tag(tag): topic
        for topic, tags in load_r18_topics().items()
        for tag in tags
    }


def _resolve_r18_topic_control(
    topic_control: dict[str, Any] | None,
) -> tuple[bool, dict[str, dict[str, Any]]]:
    """规范化 r18 主题控制配置。

    Returns:
        ``(是否启用, 规范化后的 主题名 -> 配置 字典)``。``topics`` 为空或
        未启用时第一项为 ``False``。
    """
    if not isinstance(topic_control, dict) or not topic_control.get("enabled", True):
        return False, {}
    raw_topics = topic_control.get("topics") or {}
    if not isinstance(raw_topics, dict):
        return False, {}
    topics_cfg: dict[str, dict[str, Any]] = {}
    for topic, raw in raw_topics.items():
        if not isinstance(raw, dict):
            continue
        topics_cfg[str(topic)] = {
            "enabled": bool(raw.get("enabled", True)),
            "mode": raw.get("mode", "weighted"),
            "count": max(1, int(raw.get("count", 1) or 1)),
            "probability": float(raw.get("probability", 0.5) or 0),
            "weight": max(0.0, float(raw.get("weight", 1) or 1)),
            "linked_topics": [str(t) for t in (raw.get("linked_topics") or [])],
            "link_probability": float(raw.get("link_probability", 0.8) or 0),
        }
    return bool(topics_cfg), topics_cfg


#: 多人场景标记（与 cli._is_multi_character 保持一致）。
_MULTI_CHARACTER_MARKERS: frozenset[str] = frozenset(
    {
        "2girls",
        "3girls",
        "2boys",
        "3boys",
        "multiple girls",
        "multiple boys",
    }
)


def _resolve_solo_disabled_topics(
    topic_control: dict[str, Any] | None,
    count_gender_tags: list[dict],
) -> set[str]:
    """解析单人场景禁用的 r18 主题集合。

    配置位于 ``r18_topic_control.solo``：``enabled`` 是否启用限制，
    ``disabled_topics`` 为单人场景（非多人标记）下禁用的主题列表，
    例如 ``["oral", "penetration", "positions"]``。多人场景返回空集合。
    """
    if not isinstance(topic_control, dict):
        return set()
    solo_cfg = topic_control.get("solo") or {}
    if not isinstance(solo_cfg, dict) or not solo_cfg.get("enabled", True):
        return set()
    for item in count_gender_tags:
        tag = item.get("tag", "") if isinstance(item, dict) else str(item)
        if _normalize_tag(tag) in _MULTI_CHARACTER_MARKERS:
            return set()
    return {
        str(t)
        for t in (solo_cfg.get("disabled_topics") or [])
        if str(t).strip()
    }


def _decide_r18_topic_activation(
    topics_cfg: dict[str, dict[str, Any]],
    topic_tag_map: dict[str, str],
    disabled_topics: set[str] | None = None,
) -> tuple[set[str], dict[str, int], set[str]]:
    """在抽样前一次性掷骰，决定本次样本的主题激活结果。

    供主抽样与 r18 补充共用，保证同一主题在全链路中状态一致：
    - ``mode: fixed``：必激活，配额 = count；
    - ``mode: probabilistic``：按 probability 掷骰激活；
    - 其余（weighted/默认）：总是激活，仅按 weight 调节抽样权重；
    - 已激活主题的 ``linked_topics`` 以 ``link_probability`` 联动激活；
    - 未配置的主题按默认（weighted, weight=1）处理；
    - ``disabled_topics`` 中的主题强制不激活（如单人场景限制），
      其 tag 同样进入排除集合。

    Returns:
        ``(激活主题集合, fixed 主题配额, 未激活主题的全部 tag 规范化集合)``。
    """
    all_topics = set(topic_tag_map.values())
    hard_disabled = set(disabled_topics or set())
    activated: set[str] = set()
    fixed_quotas: dict[str, int] = {}
    for topic in all_topics:
        if topic in hard_disabled:
            continue
        cfg = topics_cfg.get(topic, {})
        if not cfg.get("enabled", True):
            continue
        mode = cfg.get("mode", "weighted")
        if mode == "fixed":
            activated.add(topic)
            fixed_quotas[topic] = cfg.get("count", 1)
        elif mode == "probabilistic":
            if random.random() < cfg.get("probability", 0.5):
                activated.add(topic)
        else:
            activated.add(topic)

    # 联动激活（仅在目标主题已激活时生效）。
    for topic in list(activated):
        cfg = topics_cfg.get(topic, {})
        if random.random() >= cfg.get("link_probability", 0.8):
            continue
        for linked in cfg.get("linked_topics", []):
            if linked in all_topics and linked not in activated:
                activated.add(linked)

    excluded_norms = {
        _normalize_tag(tag)
        for tag, topic in topic_tag_map.items()
        if topic not in activated
    }
    return activated, fixed_quotas, excluded_norms


def _weighted_sample_without_replacement(
    pool: list[Any], weights: list[float], k: int
) -> list[Any]:
    """按权重不放回抽样 k 个元素（轮盘实现，适用于小规模候选池）。"""
    indices = list(range(len(pool)))
    picked: list[Any] = []
    for _ in range(min(k, len(pool))):
        total = sum(weights[i] for i in indices)
        if total <= 0:
            break
        r = random.random() * total
        acc = 0.0
        idx = indices[-1]
        for i in indices:
            acc += weights[i]
            if r <= acc:
                idx = i
                break
        picked.append(pool[idx])
        indices.remove(idx)
    return picked


def _sample_r18_by_topic_control(
    candidates: list[tuple[str, dict]],
    need: int,
    topics_cfg: dict[str, dict[str, Any]],
    activated: set[str],
    fixed_quotas: dict[str, int],
    topic_tag_map: dict[str, str],
    current_by_topic: dict[str, int],
) -> list[tuple[str, dict]]:
    """按激活主题与配额从 r18 候选池中抽样（不放回）。

    - 先为每个 ``mode: fixed`` 主题抽满配额（扣除主抽样已出现数量）；
    - 再按主题权重从高到低为其余激活主题按各自 ``count`` 分配名额
      （主题类可配置 count>1 集中出现，非主题类固定小数量）；
    - 剩余名额从所有激活主题的剩余候选按主题 ``weight`` 加权补足。
    """
    if need <= 0 or not candidates:
        return []

    pools: dict[str, list[tuple[str, dict]]] = {}
    for category, item in candidates:
        topic = topic_tag_map.get(_normalize_tag(item.get("tag", "")), "")
        pools.setdefault(topic, []).append((category, item))

    selected: list[tuple[str, dict]] = []
    selected_norms: set[str] = set()

    def _available(topic: str) -> list[tuple[str, dict]]:
        return [
            c
            for c in pools.get(topic, [])
            if _normalize_tag(c[1].get("tag", "")) not in selected_norms
        ]

    def _mark(picked: list[tuple[str, dict]]) -> None:
        selected.extend(picked)
        selected_norms.update(_normalize_tag(c[1].get("tag", "")) for c in picked)

    # 1) fixed 主题：扣除主抽样已出现数量后尽力抽满。
    for topic in sorted(fixed_quotas):
        if topic not in pools:
            continue
        quota = max(0, fixed_quotas[topic] - current_by_topic.get(topic, 0))
        if quota <= 0:
            continue
        available = _available(topic)
        k = min(quota, len(available), need - len(selected))
        if k <= 0:
            continue
        _mark(random.sample(available, k))

    # 2) 为激活主题（非 fixed）按各自 count 分配名额：按主题权重从高到低
    #    依次满足，使主题类（如 bondage count=3）可以作为 r18 主题集中出现，
    #    非主题类（如 reactions fixed count=2）则固定小数量出现。
    step2_topics = sorted(activated - set(fixed_quotas))
    remaining = need - len(selected)
    if remaining > 0 and step2_topics:
        ordered = sorted(
            step2_topics,
            key=lambda t: -topics_cfg.get(t, {}).get("weight", 1.0),
        )
        for topic in ordered:
            if remaining <= 0:
                break
            quota = min(
                int(topics_cfg.get(topic, {}).get("count", 1)),
                remaining,
            )
            available = _available(topic)
            k = min(quota, len(available))
            if k <= 0:
                continue
            _mark(random.sample(available, k))
            remaining = need - len(selected)

    # 3) 剩余名额按主题权重补足。
    remaining = need - len(selected)
    if remaining > 0:
        pool: list[tuple[str, dict]] = []
        weights: list[float] = []
        for topic in step2_topics:
            for c in _available(topic):
                pool.append(c)
                weights.append(topics_cfg.get(topic, {}).get("weight", 1.0))
        k = min(remaining, len(pool))
        if k > 0:
            if len(set(weights)) <= 1:
                picked = random.sample(pool, k)
            else:
                picked = _weighted_sample_without_replacement(pool, weights, k)
            _mark(picked)

    return selected


def _normalize_artist_tag(tag: str) -> str:
    """归一化画师 tag：小写、下划线转空格、还原被转义的括号。"""
    normalized = tag.strip().replace("_", " ").lower()
    normalized = normalized.replace("\\(", "(").replace("\\)", ")")
    return normalized


def _is_paren_disambiguated(normalized: str) -> bool:
    """判断尾括号是否为常见消歧义词（True=可保留）。

    括号内若不是常见消歧义词（或含 ``/``），视为角色/作品名而丢弃。
    该检查是精确白名单判定（非模糊正则），对已人工分类的知识库 v1 同样生效，
    避免 ``z3 max schultz (kancolle) (cosplay)`` 等角色 cosplay 混入池中。
    """
    paren_match = re.search(r"\(([^)]+)\)$", normalized)
    if paren_match:
        inner = paren_match.group(1).lower().strip()
        if "/" in inner or inner not in config.PAREN_DISAMBIGUATION_OK:
            return False
    return True


def is_noisy_tag(tag: str, blacklist: set[str] | None = None) -> bool:
    """判断 tag 是否为噪声（画师名、梗、随机字符、角色名等）。

    Args:
        tag: 原始或归一化后的 tag 字符串。
        blacklist: 额外精确黑名单（归一化形式）。

    Returns:
        True 表示应丢弃。
    """
    normalized = _normalize_tag(tag)
    if not normalized:
        return True

    # 长度过滤
    if len(normalized) < config.MIN_TAG_LEN or len(normalized) > config.MAX_TAG_LEN:
        return True

    if blacklist and normalized in blacklist:
        return True

    if normalized in config.EXACT_EXCLUDE_TAGS:
        return True

    lower = normalized.lower()
    for keyword in config.EXCLUDE_KEYWORDS:
        if keyword in lower:
            return True

    for pattern in _COMPILED_EXCLUDE_PATTERNS:
        if pattern.search(normalized):
            return True

    # 括号内若不是常见消歧义词，则视为角色/作品名而丢弃。
    if not _is_paren_disambiguated(normalized):
        return True

    return False


def _quality_score(tag: str) -> float:
    """简单的 tag 质量分：太短或太长的 tag 排名靠后，常见短词更优。"""
    score = 100.0
    length = len(tag)

    # 过短（多为缩写/颜文字）和过长（多为具体描述/噪声）都降权
    if length < 4:
        score -= 50
    elif length > 22:
        score -= (length - 22) * 2

    core = tag.replace(" ", "")
    if core.isalpha() and tag.islower():
        score += 5

    # 常见人数/性别 tag（如 1girl, 2girls, 1other）给予补偿
    if re.match(r"^\d+(girl|boy|other)s?$", tag):
        score += 8

    score -= sum(c.isdigit() for c in tag) * 2
    score -= sum(1 for c in tag if not c.isalnum() and c not in " ()-") * 6
    score -= tag.count(" ") * 0.5
    return score


def load_tag_database(csv_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """读取 danbooru tag CSV 并按内部类别分组。

    Args:
        csv_path: CSV 文件路径，需包含 english、chinese、category、subcategory 列。

    Returns:
        按内部类别分组的字典：
        ``{internal_category: [{"tag": ..., "chinese": ..., "category": ..., "subcategory": ...}, ...]}``。
    """
    csv_path = Path(csv_path)
    database: dict[str, list[dict[str, Any]]] = {key: [] for key in config.DEFAULT_SAMPLE_COUNTS}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row_index, row in enumerate(reader):
            english = (row.get("english") or "").strip()
            if not english:
                continue

            # 保留 score_* 这类质量标签的下划线，其它 tag 的下划线统一为空格
            if english.startswith("score_"):
                tag = english
            else:
                tag = english.replace("_", " ")

            category = (row.get("category") or "").strip()
            subcategory = (row.get("subcategory") or "").strip()
            internal_category = config.resolve_internal_category(category, subcategory)

            # tag 级覆盖：解决 subcategory 粒度不足
            tag_override = config.TAG_TO_CATEGORY_OVERRIDES.get(_normalize_tag(tag))
            if tag_override:
                internal_category = tag_override

            # 只保留 config 中定义的内部类别，其余丢弃
            if internal_category not in database:
                continue

            database[internal_category].append(
                {
                    "tag": tag,
                    "chinese": (row.get("chinese") or "").strip(),
                    "category": category,
                    "subcategory": subcategory,
                    "index": row_index,
                }
            )

    return database


def build_artist_blacklist(
    animadex_path: str | Path,
    artists_path: str | Path,
) -> set[str]:
    """从 animadex_index 与 artists 文件构建画师黑名单集合。

    Args:
        animadex_path: animadex_index.csv 路径（JSON Lines，每行包含
            ``source_kind`` 与 ``tag`` 字段）。
        artists_path: artists.csv 路径（JSON Lines，每行包含 ``tag`` 字段）。

    Returns:
        归一化后的画师 tag 集合，包含普通形式与 ``@`` 前缀形式。
    """
    blacklist: set[str] = set()

    def _add_artist_variants(raw_tag: str) -> None:
        normalized = _normalize_artist_tag(raw_tag)
        if not normalized:
            return
        blacklist.add(normalized)
        blacklist.add("@" + normalized)

    for path in (animadex_path, artists_path):
        path = Path(path)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                tag = record.get("tag")
                if not tag or not isinstance(tag, str):
                    continue

                # animadex_index 中仅保留 source_kind == "artist" 的记录
                if "source_kind" in record and record.get("source_kind") != "artist":
                    continue

                _add_artist_variants(tag)

    return blacklist


def _compile_category_patterns() -> dict[str, list[re.Pattern[str]]]:
    """预编译类别级正则白名单。"""
    return {
        category: [re.compile(pattern) for pattern in patterns]
        for category, patterns in config.CATEGORY_TAG_PATTERNS.items()
    }


_COMPILED_CATEGORY_PATTERNS = _compile_category_patterns()


def _matches_category_patterns(tag: str, category: str) -> bool:
    """检查 tag 是否满足该类别的白名单正则（未配置则直接通过）。"""
    patterns = _COMPILED_CATEGORY_PATTERNS.get(category)
    if not patterns:
        return True
    normalized = _normalize_tag(tag)
    return any(pattern.match(normalized) for pattern in patterns)


def _meaningful_chinese(chinese: str | None) -> bool:
    """检查 chinese 字段是否为有效翻译（非空且不只是省略号）。"""
    if not config.REQUIRE_NON_EMPTY_CHINESE:
        return True
    text = (chinese or "").strip()
    return bool(text) and text != "..."


def build_curated_pools(
    database: dict[str, list[dict[str, Any]]],
    top_n: int = 500,
    blacklist: set[str] | None = None,
    output_path: str | Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """为每个内部类别构建高质量 curated pool。

    按质量分排序，过滤噪声 tag，并将结果保存到 JSON 以供复用。

    Args:
        database: ``load_tag_database`` 返回的完整类别分组数据。
        top_n: 每个类别保留的 tag 数量。
        blacklist: 可选画师黑名单，额外过滤。
        output_path: 输出 JSON 路径，默认 ``config.CURATED_POOLS_FILE``。

    Returns:
        与 ``database`` 同结构的 curated pool。
    """
    output_path = Path(output_path or config.CURATED_POOLS_FILE)
    pools: dict[str, list[dict[str, Any]]] = {}

    for category, tags in database.items():
        filtered = [
            item
            for item in tags
            if not is_noisy_tag(item["tag"], blacklist)
            and _matches_category_patterns(item["tag"], category)
            and _meaningful_chinese(item.get("chinese", ""))
            and item.get("index", 0) < config.MAX_TAG_INDEX
            and _is_female_only_tag(item["tag"])
            and _is_human_like_tag(item["tag"])
        ]
        scored = sorted(
            filtered,
            key=lambda item: (
                -_quality_score(item["tag"]),
                item.get("index", 0),
            ),
        )
        pools[category] = scored[:top_n]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(pools, f, ensure_ascii=False, indent=2)

    return pools


def load_curated_pools(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """从 JSON 加载 curated pool。"""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_curated_tags(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """从 YAML 加载带年龄分级的 curated tags。

    Args:
        path: YAML 文件路径，结构为 ``{category: [{tag, rating, chinese}, ...]}``。

    Returns:
        按内部类别分组的字典。
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    result: dict[str, list[dict[str, Any]]] = {
        key: [] for key in config.DEFAULT_SAMPLE_COUNTS
    }
    for category, items in data.items():
        if category not in result:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            tag = (item.get("tag") or "").strip()
            if not tag:
                continue
            result[category].append(
                {
                    "tag": tag,
                    "rating": (item.get("rating") or "general").strip(),
                    "chinese": (item.get("chinese") or "").strip(),
                }
            )
    return result


def filter_by_rating(
    tags: list[dict[str, Any]],
    max_rating: str,
) -> list[dict[str, Any]]:
    """过滤出 rating 不超过 ``max_rating`` 的 tag。

    Args:
        tags: tag 字典列表，每个字典需包含 ``rating`` 字段。
        max_rating: 最大允许分级，需为 ``config.RATING_ORDER`` 中的一项。

    Returns:
        过滤后的 tag 列表。

    Raises:
        ValueError: 若 ``max_rating`` 不是合法分级。
    """
    if max_rating not in config.RATING_ORDER:
        raise ValueError(
            f"Invalid max_rating {max_rating!r}; "
            f"expected one of {config.RATING_ORDER}"
        )
    max_index = config.RATING_ORDER.index(max_rating)
    return [
        item
        for item in tags
        if config.RATING_ORDER.index(item.get("rating", "general")) <= max_index
    ]


def sample_tags_by_category(
    database: dict[str, list[dict[str, Any]]],
    counts: dict[str, int],
    seed: int | None = None,
    artist_blacklist: set[str] | None = None,
    pools: dict[str, list[dict[str, Any]]] | None = None,
    curated_tags: dict[str, list[dict[str, Any]]] | None = None,
    max_rating: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """按类别随机抽样 tag。

    Args:
        database: ``load_tag_database`` 返回的类别分组数据（兼容性保留）。
        counts: 每类期望抽样数量，形如 ``{"appearance": 4, ...}``。
        seed: 可选随机种子，用于结果可复现。
        artist_blacklist: 可选画师黑名单；命中黑名单的 tag 不会被抽中。
        pools: 可选旧版 curated pool；提供时从 pool 中抽样。
        curated_tags: 可选带 age-rating 的 curated tags YAML 数据；提供时优先使用，
            并根据 ``max_rating`` 过滤。
        max_rating: 最大允许分级，默认 ``config.DEFAULT_MAX_RATING``。
            仅当 ``curated_tags`` 提供时生效。

    Returns:
        与输入同结构的抽样结果。
    """
    if seed is not None:
        random.seed(seed)

    if curated_tags is not None:
        source = curated_tags
        max_rating = max_rating or config.DEFAULT_MAX_RATING
    elif pools is not None:
        source = pools
        max_rating = None
    else:
        source = database
        max_rating = None

    normalized_blacklist: set[str] = set()
    if artist_blacklist:
        normalized_blacklist = {
            _normalize_tag(tag.lstrip("@")) for tag in artist_blacklist
        }

    sampled: dict[str, list[dict[str, Any]]] = {}
    for category, tags in source.items():
        n = counts.get(category, 0)
        if n <= 0 or not tags:
            sampled[category] = []
            continue

        # 人数/性别只抽 1 个，限定为 1girl 或 2girls
        if category == "count_gender":
            n = 1

        if max_rating is not None:
            tags = filter_by_rating(tags, max_rating)

        if normalized_blacklist:
            tags = [
                item
                for item in tags
                if _normalize_tag(item["tag"].lstrip("@")) not in normalized_blacklist
            ]

        # 介质/噪音 meta tag 排除（对所有来源生效，包括已入池的 curated_tags）
        tags = [
            item
            for item in tags
            if not config.is_noise_meta_tag(_normalize_tag(item["tag"]))
        ]

        # curated_tags 已按语义人工/审核判定入池，不再套用旧脚本筛选；
        # 旧版数据库/旧池源仍保留语义排除清单 + 脚本防护。
        if source is not curated_tags:
            tags = [item for item in tags if not _is_semantically_excluded(item["tag"], max_rating)]
            tags = [item for item in tags if not is_noisy_tag(item["tag"])]
            tags = [item for item in tags if _is_female_only_tag(item["tag"])]
            tags = [item for item in tags if _is_human_like_tag(item["tag"])]

        # 人数/性别类别限定为 1girl 或 2girls
        if category == "count_gender":
            tags = [
                item
                for item in tags
                if _normalize_tag(item["tag"]) in config.DEFAULT_COUNT_GENDER_TAGS
            ]

        k = min(n, len(tags))
        if k <= 0:
            sampled[category] = []
            continue
        sampled[category] = random.sample(tags, k)
    return sampled


def validate_tag_sources(
    prompt_tags: list[str],
    database: dict[str, list[dict[str, Any]]],
    extra_whitelist: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """校验 prompt 中的 tag 是否均来自数据库或白名单。

    Args:
        prompt_tags: 待校验的 tag 列表。
        database: tag 数据库。
        extra_whitelist: 额外允许的 tag 集合（如质量前缀、安全标签等）。

    Returns:
        ``(valid_tags, unknown_tags)``，均为 prompt_tags 中出现的原始字符串。
    """
    extra_whitelist = extra_whitelist or set()
    normalized_whitelist = {_normalize_tag(t) for t in extra_whitelist}

    normalized_db_tags: dict[str, str] = {}
    for tags in database.values():
        for item in tags:
            normalized = _normalize_tag(item["tag"])
            normalized_db_tags.setdefault(normalized, item["tag"])

    valid_tags: list[str] = []
    unknown_tags: list[str] = []

    for tag in prompt_tags:
        normalized = _normalize_tag(tag)
        if normalized in normalized_db_tags or normalized in normalized_whitelist:
            valid_tags.append(tag)
        else:
            unknown_tags.append(tag)

    return valid_tags, unknown_tags


if __name__ == "__main__":
    db = load_knowledge_v1_database()
    print("Knowledge v1 category counts:")
    for cat, tags in db.items():
        print(f"  {cat}: {len(tags)}")

    curated = load_curated_tags(config.CURATED_TAGS_FILE)
    counts = config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS
    sampled = sample_from_knowledge_v1(db, counts, curated, seed=42, max_rating="r15")

    print("\nSampled counts:")
    for cat, tags in sampled.items():
        print(f"  {cat}: {len(tags)}")

    print("\nSampled tags (first item per category):")
    for cat, tags in sampled.items():
        first = tags[0]["tag"] if tags else None
        print(f"  {cat}: {first}")

    # 校验无 R18 及以上 tag。
    rating_map = {}
    for items in curated.values():
        for item in items:
            rating_map[_normalize_tag(item["tag"])] = item.get("rating", "general")

    bad = []
    for cat, tags in sampled.items():
        for item in tags:
            rating = rating_map.get(_normalize_tag(item["tag"]), "general")
            if config.RATING_ORDER.index(rating) > config.RATING_ORDER.index("r15"):
                bad.append((cat, item["tag"], rating))

    if bad:
        print("\nFound over-R15 tags:", bad)
    else:
        print("\nNo R18+ tags in sample.")
