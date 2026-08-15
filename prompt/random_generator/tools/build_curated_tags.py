"""从 danbooru CSV 自动构建带年龄分级的 curated_tags.yaml。

用法：
    python -m prompt.random_generator.tools.build_curated_tags

规则基于 tag 的客观字面含义；具体短语的优先级高于泛关键词。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import yaml

from .. import config
from ..retrieval import _is_female_only_tag, _is_human_like_tag
from ..tag_classification_rules import (
    EXTRA_EXACT_OVERRIDES,
    EXTRA_RATING_KEYWORDS,
    R18_MANUAL_WHITELIST,
)

RATING_ORDER = ["general", "pg12", "r15", "r18", "r18g"]

# build_curated_tags 使用比 config.EXCLUDE_KEYWORDS 更宽松的噪声过滤：
# 仅排除画师/版权/元数据/真正无意义标签，让动漫常见 tag（泳装、武器、
# 轻微暴力、兽耳等）进入白名单，并由下面的分级规则处理。
_BUILD_EXCLUDE_KEYWORDS: set[str] = {
    "artist_name",
    "copyright_name",
    "twitter_username",
    "patreon_username",
    "url",
    "md5",
    "md5_mismatch",
    "webm",
    "non-web_source",
    "translation_request",
    "copyright_request",
    "commission",
    "signature",
    "artist_logo",
    "artist_self-insert",
    "collaborative",
    "artist_collaboration",
    "skeb_commission",
    "pixiv_commission",
    "translated",
    "chinese_commentary",
    "korean_commentary",
    "dialogue",
    "watermark",
    "revision",
    "scan",
    "letterboxed",
    "border",
    "onomatopoeia",
    "short_playtime",
    "profile",
    "fan_character",
    "original",
    "text",
    "username",
    "meme",
    "xxx",
    "saberface",
    "zero_pictured",
    "cosplay photo",
}

# 将本地噪声关键词编译为单一 alternation 正则。
_BUILD_EXCLUDE_PATTERN: re.Pattern[str] | None = None
if _BUILD_EXCLUDE_KEYWORDS:
    _BUILD_EXCLUDE_PATTERN = re.compile(
        "|".join(
            re.escape(kw.strip().replace("_", " ").replace("-", " "))
            for kw in _BUILD_EXCLUDE_KEYWORDS
            if kw
        )
    )

# 精确覆盖表：对歧义或常见 tag 做最终裁定。
EXACT_RATING_OVERRIDES: dict[str, str] = {
    # 常见身体特征 -> general
    "blood": "pg12",
    "tears": "general",
    "crying": "general",
    "horns": "general",
    "tail": "general",
    "animal ears": "general",
    "elf": "general",
    "demon girl": "general",
    "fairy": "general",
    "angel": "general",
    "monster girl": "general",
    "wings": "general",
    "pointy ears": "general",
    "fang": "general",
    "fangs": "general",
    "blush": "general",
    "smile": "general",
    "sweat": "general",
    "sweatdrop": "general",
    "wet": "general",
    "bondage": "r15",
    "bound": "r15",
    "tied up": "r15",
    "weapon": "pg12",
    "sword": "pg12",
    "knife": "r15",
    "gun": "r15",
    "rifle": "r15",
    "pistol": "r15",
    "angry": "general",
    "serious": "general",
    "annoyed": "general",
    "scar": "general",
    "scar on face": "pg12",
    "scar on cheek": "pg12",
    "scar across eye": "pg12",
    "bandaged head": "pg12",
    "drunk": "r15",
    # 常见非性 / 非暴力歧义消解
    "teddy bear": "general",
    "covered navel": "general",
    "self bite": "pg12",
    "dominant feral": "general",
    "low-tied long hair": "general",
    "white balls": "general",
    "bouncing balls": "general",
    "black balls": "general",
    "monotone balls": "general",
    "red balls": "general",
    "blue balls": "general",
    "colorful balls": "general",
    "christmas balls": "general",
    "ball": "general",
    "balls": "general",
    "multi-tied hair": "general",
    "wet hair": "general",
    "dominant herm": "general",
    "zenra": "r18",
    # 明确涉及色情内容 -> r18
    "looking at porn": "r18",
    "frottage": "r18",
    "pasties": "r18",
    # 明显性暗示镜头 -> r15
    "crotch shot": "r15",
    # 直接暴力动作 -> r15
    "stab": "r15",
    "stabbing": "r15",
    # 情绪/心理状态在 BDSM 语境下 -> r15
    "humiliation": "r15",
    # 明显性唤起/性暗示表情 -> r15
    "aroused": "r15",
    "aroused face": "r15",
    "arousal": "r15",
    "bimbo": "r15",
    "bimbo lip": "r15",
    # 自我触摸敏感部位 -> r15
    "touching own thigh": "r15",
    "touching own breast": "r15",
    "touching own breasts": "r15",
    "touching own butt": "r15",
    "touching own crotch": "r18",
    # 伤病/残疾状态 -> pg12
    "cracked skin": "pg12",
    "missing leg": "pg12",
    "missing arm": "pg12",
    "scar": "general",
    # 直接暴力武器 -> r15
    "desert eagle": "r15",
    # 身体恐怖/极端 -> r18g
    "headless": "r18g",
    "severed head": "r18g",
    "holding detached head": "r18g",
    "detached head": "r18g",
    "stitched mouth": "r15",
    "sewn mouth": "r15",
    "slutty face": "r15",
    "hat only": "r15",
    "boots only": "r15",
    "shirt only": "r15",
    "jacket only": "r15",
    "gloves only": "r15",
    "socks only": "r15",
    "panties only": "r15",
    "bra only": "r15",
    "jewelry only": "r15",
    # -------------- 服装/穿着状态 --------------
    "swimsuit": "pg12",
    "bikini": "pg12",
    "one-piece swimsuit": "pg12",
    "school swimsuit": "pg12",
    "gym uniform": "pg12",
    "buruma": "pg12",
    "sportswear": "pg12",
    "miniskirt": "pg12",
    "crop top": "pg12",
    "tank top": "general",
    "shorts": "general",
    "skirt lift": "pg12",
    "torn clothes": "pg12",
    "cleavage": "pg12",
    "off shoulder": "pg12",
    "backless": "pg12",
    "strapless": "pg12",
    "side slit": "pg12",
    "midriff": "pg12",
    "navel": "pg12",
    "bare shoulders": "pg12",
    "bare back": "pg12",
    "barefoot": "general",
    "bare legs": "general",
    "bare arms": "general",
    "lingerie": "r15",
    "panties": "r15",
    "bra": "r15",
    "underwear": "r15",
    "thong": "r15",
    "garter belt": "r15",
    "stockings": "pg12",
    "pantyhose": "pg12",
    "tights": "pg12",
    "leotard": "pg12",
    "bodysuit": "pg12",
    "corset": "r15",
    "bustier": "r15",
    "camisole": "pg12",
    "chemise": "r15",
    "babydoll": "r15",
    "negligee": "r15",
    "nightgown": "pg12",
    "slip": "r15",
    "underwear only": "r15",
    "panties only": "r15",
    "bra only": "r15",
    "open clothes": "r15",
    "open shirt": "r15",
    "open jacket": "r15",
    "open fly": "r15",
    "clothes lift": "r15",
    "shirt lift": "r15",
    "dress lift": "r15",
    "skirt lift": "r15",
    "clothing aside": "r15",
    "clothes pull": "r15",
    "clothing pull": "r15",
    "underwear down": "r15",
    "lowleg": "r15",
    "sideboob": "r15",
    "underboob": "r15",
    "under boob": "r15",
    "visible panties": "r15",
    "panty peek": "r15",
    "downblouse": "r15",
    "upskirt": "r15",
    "plunging neckline": "r15",
    "cleavage window": "r15",
    "see-through": "r15",
    "wet clothes": "r15",
    "wet shirt": "r15",
    "wet hair": "general",
    "wet body": "r15",
    "micro bikini": "r15",
    "thong bikini": "r15",
    "slingshot swimsuit": "r15",
    "playboy bunny": "r15",
    "virgin killer sweater": "r15",
    # -------------- 武器/暴力 --------------
    "weapon": "pg12",
    "sword": "pg12",
    "holding sword": "pg12",
    "shield": "pg12",
    "spear": "pg12",
    "bow": "pg12",
    "bow and arrow": "pg12",
    "arrow": "pg12",
    "staff": "general",
    "wand": "general",
    "knife": "r15",
    "gun": "r15",
    "rifle": "r15",
    "pistol": "r15",
    "blade": "r15",
    "holding knife": "r15",
    "holding gun": "r15",
    "holding weapon": "pg12",
    "desert eagle": "r15",
    "fighting": "pg12",
    "battle": "pg12",
    "punching": "pg12",
    "kicking": "pg12",
    "slap": "r15",
    "bite": "pg12",
    "fighting stance": "pg12",
    "battle stance": "pg12",
    "action pose": "pg12",
    "dynamic pose": "pg12",
    "bandage": "pg12",
    "bandaged": "pg12",
    "bandages": "pg12",
    "bruise": "pg12",
    "bruised": "pg12",
    "wound": "pg12",
    "wounded": "pg12",
    "injury": "pg12",
    "injured": "pg12",
    "blood on face": "pg12",
    "blood stain": "pg12",
    "blood from mouth": "r15",
    "bleeding": "r15",
    "cigarette": "pg12",
    "smoking": "pg12",
    "stab": "r15",
    "stabbing": "r15",
    "choking": "r15",
    "strangling": "r15",
    # -------------- 束缚 / 支配 --------------
    "handcuffs": "r15",
    "shackles": "r15",
    "collar": "r15",
    "leash": "r15",
    "blindfold": "r15",
    "submissive": "r15",
    "dominant": "r15",
    "femdom": "r15",
    "rope": "r15",
    "cuffs": "r15",
    "ball gag": "r18",
    "bit gag": "r18",
    "tape gag": "r18",
    "cleave gag": "r18",
    "spreader bar": "r18",
    # -------------- 姿势 / 动作 / 性暗示 --------------
    "spread legs": "r15",
    "legs apart": "r15",
    "leg up": "r15",
    "legs up": "r15",
    "bent over": "r15",
    "all fours": "r15",
    "arched back": "r15",
    "hand between legs": "r15",
    "holding both legs": "r15",
    "grabbing own legs": "r15",
    "grabbing both legs": "r15",
    "thigh grab": "r15",
    "breast grab": "r15",
    "grabbing own breast": "r15",
    "grabbing own breasts": "r15",
    "grabbing breasts": "r15",
    "touching own thigh": "r15",
    "touching own breast": "r15",
    "touching own breasts": "r15",
    "touching own butt": "r15",
    "touching own crotch": "r18",
    "kissing": "pg12",
    "kiss": "pg12",
    "hugging": "general",
    "hug": "general",
    "carrying": "general",
    "princess carry": "pg12",
    "sleeping": "general",
    "asleep": "general",
    "unconscious": "r15",
    "hypnosis": "r15",
    "mind control": "r15",
    "electrocution": "r15",
    # -------------- 表情 / 反应 --------------
    "angry": "general",
    "serious": "general",
    "annoyed": "general",
    "determined": "general",
    "seductive": "r15",
    "bedroom eyes": "r15",
    "naughty face": "r15",
    "slutty face": "r15",
    "aroused": "r15",
    "aroused face": "r15",
    "arousal": "r15",
    "bimbo": "r15",
    "bimbo lip": "r15",
    "licking lips": "r15",
    "licking own lips": "r15",
    "biting lip": "r15",
    "hickey": "r15",
    "drunk": "r15",
    "intoxicated": "r15",
    "humiliation": "r15",
    "embarrassed": "general",
    "shy": "general",
    "blush": "general",
    "tears": "general",
    "crying": "general",
    "sweat": "general",
    "sweatdrop": "general",
    "steaming body": "r15",
    "glistening body": "r15",
    "shiny skin": "general",
    "oiled": "r15",
    # -------------- 裸露 / 性器官 / 性行为 -> r18 --------------
    "nude": "r18",
    "completely nude": "r18",
    "fully nude": "r18",
    "no clothes": "r18",
    "bare body": "r18",
    "fully exposed": "r18",
    "naked": "r18",
    "topless": "r18",
    "bottomless": "r18",
    "no panties": "r18",
    "no bra": "r18",
    "partially undressed": "r18",
    "undressing": "r18",
    "nipples": "r18",
    "nipple": "r18",
    "areola": "r18",
    "pussy": "r18",
    "vagina": "r18",
    "penis": "r18",
    "dick": "r18",
    "cock": "r18",
    "clit": "r18",
    "clitoris": "r18",
    "anus": "r18",
    "asshole": "r18",
    "testicles": "r18",
    "testicle": "r18",
    "glans": "r18",
    "crotchless": "r18",
    "breasts out": "r18",
    "one breast out": "r18",
    "panties around one leg": "r15",
    "sex": "r18",
    "blowjob": "r18",
    "fellatio": "r18",
    "cunnilingus": "r18",
    "handjob": "r18",
    "footjob": "r18",
    "rimjob": "r18",
    "anal": "r18",
    "vaginal": "r18",
    "penetration": "r18",
    "penetrated": "r18",
    "missionary": "r18",
    "doggystyle": "r18",
    "cowgirl position": "r18",
    "prone bone": "r18",
    "gangbang": "r18",
    "orgy": "r18",
    "threesome": "r18",
    "foursome": "r18",
    "orgasm": "r18",
    "masturbation": "r18",
    "fingering": "r18",
    "fisting": "r18",
    "cum": "r18",
    "semen": "r18",
    "ejaculation": "r18",
    "creampie": "r18",
    "internal cumshot": "r18",
    "bukkake": "r18",
    "gokkun": "r18",
    "paizuri": "r18",
    "naizuri": "r18",
    "oral": "r18",
    "dildo": "r18",
    "vibrator": "r18",
    "buttplug": "r18",
    "sex toy": "r18",
    "anal beads": "r18",
    "bdsm": "r18",
    "shibari": "r18",
    "hogtie": "r18",
    "hogtied": "r18",
    # -------------- 极端 / r18g --------------
    "headless": "r18g",
    "severed head": "r18g",
    "detached head": "r18g",
    "holding detached head": "r18g",
    "amputee": "r18g",
    "amputated": "r18g",
    "amputation": "r18g",
    "dismembered": "r18g",
    "beheaded": "r18g",
    "decapitated": "r18g",
    "decapitation": "r18g",
    "disembowel": "r18g",
    "disembowelment": "r18g",
    "internal organs": "r18g",
    "intestine": "r18g",
    "intestines": "r18g",
    "viscera": "r18g",
    "prolapse": "r18g",
    "rectal prolapse": "r18g",
    "mutilated": "r18g",
    "mutilation": "r18g",
    "flayed": "r18g",
    "skinned alive": "r18g",
    "corpse": "r18g",
    "dead body": "r18g",
    "death": "r18g",
    "dying": "r18g",
    "murder": "r18g",
    "snuff": "r18g",
    "necrophilia": "r18g",
    "ryona": "r18g",
    "torture": "r18g",
    "asphyxia": "r18g",
    "asphyxiation": "r18g",
    "strangled": "r18g",
    "garrote": "r18g",
    "lynching": "r18g",
    "crucifixion": "r18g",
    "gore": "r18g",
    "blood splatter": "r18g",
    "cannibalism": "r18g",
    "feces": "r18g",
    "scat": "r18g",
    "poop": "r18g",
    "shit": "r18g",
    "urine": "r18g",
    "pee": "r18g",
    "piss": "r18g",
    "vomit": "r18g",
    "snot": "r18g",
    "menstruation": "r18g",
    "period blood": "r18g",
    "enema": "r18g",
    "diarrhea": "r18g",
    "fart": "r18g",
    "flatulence": "r18g",
    "bestiality": "r18g",
    "zoophilia": "r18g",
    "incest": "r18g",
    "rape": "r18g",
    "pedophile": "r18g",
}

# 分类关键词。越具体的短语优先级越高（按长度排序后长优先）。
RATING_KEYWORDS: dict[str, list[str]] = {
    "r18g": [
        # 极端暴力 / 血腥
        "guro",
        "amputee",
        "amputated",
        "amputation",
        "dismembered",
        "beheaded",
        "decapitated",
        "decapitation",
        "disembowel",
        "disembowelment",
        "internal organs",
        "intestine",
        "intestines",
        "viscera",
        "prolapse",
        "mutilated",
        "mutilation",
        "flayed",
        "skinned alive",
        "corpse",
        "dead body",
        "death",
        "dying",
        "murder",
        "snuff",
        "necrophilia",
        "ryona",
        "torture",
        "asphyxia",
        "asphyxiation",
        "strangled",
        "garrote",
        "lynching",
        "crucifixion",
        "gore",
        "blood splatter",
        "cannibalism",
        # 排泄 / 体液
        "feces",
        "scat",
        "fecal",
        "poop",
        "shit",
        "urine",
        "pee",
        "piss",
        "vomit",
        "snot",
        "menstruation",
        "period blood",
        "enema",
        "diarrhea",
        "fart",
        "flatulence",
        # 非法 / 极端
        "bestiality",
        "zoophilia",
        "incest",
        "rape",
        "pedophile",


    ],
    "r18": [
        # 裸露状态
        "nude",
        "completely nude",
        "fully nude",
        "no clothes",
        "bare body",
        "fully exposed",
        "naked",
        "topless",
        "bottomless",
        "no panties",
        "no bra",
        "exposed slit",
        "visible slit",
        "wet slit",
        "pink inside",
        "visible bulge",
        "tented shorts",
        "undressing",
        "partially undressed",
        "indoor nudity",
        # 性器官
        "nipples",
        "pussy",
        "vagina",
        "penis",
        "dick",
        "cock",
        "clit",
        "clitoris",
        "anus",
        "asshole",
        "testicles",
        "testicle",
        "glans",
        "areola",
        "breasts out",
        "genitals",
        "genital",
        "crotchless",
        # 性行为 / 体液
        "sex",
        "blowjob",
        "fellatio",
        "cunnilingus",
        "handjob",
        "footjob",
        "rimjob",
        "anal",
        "vaginal",
        "penetration",
        "penetrated",
        "missionary",
        "doggystyle",
        "cowgirl position",
        "prone bone",
        "gangbang",
        "orgy",
        "threesome",
        "foursome",
        "orgasm",
        "cum",
        "semen",
        "ejaculation",
        "creampie",
        "bukkake",
        "gokkun",
        "paizuri",
        "naizuri",
        "oral",
        "masturbation",
        "fingering",
        "fisting",
        "cum on",
        "cum in",
        "cum inside",
        "internal cumshot",
        # 性用品 / explicit bdsm
        "dildo",
        "vibrator",
        "buttplug",
        "sex toy",
        "bdsm",
        "shibari",
        "hogtie",
        "ball gag",
        "anal beads",
        # 暴露姿势
        "spread pussy",
        "spread anus",
        "ass up",
        "presenting hindquarters",
        "presenting",
        "ball grab",
    ],
    "r15": [
        # 内衣 / 睡衣
        "lingerie",
        "panties",
        "bra",
        "underwear",
        "thong",
        "garter belt",
        "garter straps",
        "stockings",
        "pantyhose",
        "tights",
        "leotard",
        "camisole",
        "chemise",
        "babydoll",
        "negligee",
        "nightgown",
        "slip",
        "corset",
        "bustier",
        "bodysuit",
        "underwear only",
        # 更暴露的泳装变体
        "micro bikini",
        "slingshot swimsuit",
        "thong bikini",
        "see-through",
        "wet clothes",
        "wet shirt",
        "wet hair",
        # 身体局部暴露
        "bare shoulders",
        "bare back",
        "midriff",
        "navel",
        "sideboob",
        "underboob",
        "under boob",
        "visible panties",
        "panty peek",
        "downblouse",
        "upskirt",
        "open clothes",
        "open shirt",
        "open jacket",
        "open fly",
        "off shoulder",
        "backless",
        "strapless",
        "lowleg",
        "side slit",
        "plunging neckline",
        "cleavage window",
        "breast hold",
        "breast grab",
        "grabbing own breasts",
        "grabbing breasts",
        "nipple",
        "areola",
        "underwear down",
        "clothing aside",
        "clothes pull",
        "clothes in mouth",
        # 直接暴力 / 武器
        "knife",
        "gun",
        "rifle",
        "pistol",
        "blade",
        "holding knife",
        "holding gun",
        "fighting",
        "battle",
        "punching",
        "kicking",
        "slap",
        "bite",
        # 受伤 / 血腥（较明显）
        "bandage",
        "bandaged",
        "bandages",
        "bruise",
        "bruised",
        "wound",
        "wounded",
        "injury",
        "injured",
        "blood on",
        "blood from",
        "bleeding",
        "blood stain",
        "blood splatter",
        # 束缚 / 支配
        "bondage",
        "bound",
        "tied",
        "restrained",
        "handcuffs",
        "shackles",
        "collar",
        "leash",
        "blindfold",
        "submissive",
        "dominant",
        "femdom",
        # 性暗示姿势 / 动作
        "spread legs",
        "legs apart",
        "leg up",
        "bent over",
        "all fours",
        "arched back",
        "clothes lift",
        "shirt lift",
        "dress lift",
        "unzipped",
        "hand between legs",
        "holding both legs",
        "grabbing own legs",
        "grabbing both legs",
        "pov legs",
        "goo drip",
        "thigh grab",
        "mask pull",
        "strangling",
        "choking",
        "one-piece swimsuit pull",
        "panty pull",
        "panties pull",
        # 性暗示表情/性化标签
        "seductive",
        "bedroom eyes",
        "naughty face",
        "slutty",
        "bawdy",
        "aroused",
        "arousal",
        "bimbo",
        "eyes rolling back",
        "eyes rolled up",
        "touching own thigh",
        "touching own breast",
        "touching own breasts",
        "licking lips",
        "licking own lips",
        "biting lip",
        "hickey",
        "intoxicated",
        "drunk",
        # 身体恐怖
        "stitched mouth",
        "stitched eyes",
        "stitched face",
        # 未成年暗示
        "loli",
        "shota",
        "toddler",
        "kindergarten",
        "elementary school",
        "middle school",
    ],
    "pg12": [
        # 泳装 / 运动服
        "bikini",
        "swimsuit",
        "school swimsuit",
        "gym uniform",
        "buruma",
        # 轻微暴露
        "cleavage",
        "miniskirt",
        "crop top",
        "skirt lift",
        # 幻想武器 / 装备
        "sword",
        "weapon",
        "holding sword",
        "holding weapon",
        "shield",
        "spear",
        "bow and arrow",
        "staff",
        "wand",
        # 轻微暴力 / 状态
        "blood on face",
        "minor injury",
        "scrape",
        "scratch",
        "torn clothes",
        "torn sleeve",
        "band aid",
        "cigarette",
        "smoking",
    ],
}

_FLAT_KEYWORDS: list[tuple[str, str]] = []
for _rating in reversed(RATING_ORDER):
    for _kw in RATING_KEYWORDS.get(_rating, []):
        _FLAT_KEYWORDS.append((_kw, _rating))
_FLAT_KEYWORDS.sort(key=lambda pair: len(pair[0]), reverse=True)

# 元数据 / 质量 / 版权标签：这些 tag 描述图片元信息而非画面内容，直接丢弃。
METADATA_TAGS: set[str] = {
    "highres",
    "absurdres",
    "hi res",
    "lowres",
    "low res",
    "newest",
    "score_7",
    "score_8",
    "score_9",
    "score_6",
    "score_5",
    "score_4",
    "censored",
    "uncensored",
    "blur censor",
    "mosaic censoring",
    "translation request",
    "copyright request",
    "commission",
    "signature",
    "watermark",
    "revision",
    "scan",
    "text",
    "dialogue",
    "username",
    "url",
    "md5",
    "webm",
    "non-web source",
    "commentary",
    "translated",
    "bilingual",
    "letterboxed",
    "border",
    "black bars",
    "profile",
    "fan character",
    "meme",
    "parody",
    "screenshot",
    "official art",
    "game cg",
    "visual novel",
    "traditional media",
    "sketch",
    "lineart",
    "rough",
    "animation",
    "animated",
    "gif",
    "loop",
    "frame by frame",
    "comic",
    "manga",
    "doujin",
    "cover",
    "cover page",
    "omake",
    "promotional art",
    "expression chart",
    "height chart",
    "photo inset",
    "projected inset",
    "multiple views",
    "wide image",
    "tall image",
    "widescreen",
    "pillarboxed",
    "4k",
    "animated gif",
    "thumbnail",
    "vector trace",
    "ai-assisted",
    "official style",
    "style parody",
    "inspired by",
    "cut-in",
    # 画面媒介 / 元数据 / 无意义物品
    "ascii art",
    "gift art",
    "bad food",
    "good food",
    "food on face",
    "food on body",
    "rice on face",
    "incoming food",
    "f-ism",
    "clip studio paint (medium)",
    "card (medium)",
    "pen (artwork)",
    "colored pencil (artwork)",
    "flipnote studio (artwork)",
    "inspired by formal art",
    "making-of",
    "cosplay photo",
    # dry-run 残留的性暗示 / 解剖 / 错位噪声
    "top-down bottom-up",
    "wet body",
    "spines",
    "cropped head",
    "pov legs",
    "goo drip",
    "looking at porn",
    "zenra",
    # 跨类别错位的生物/物种噪声
    "digimon (species)",
    "male/ambiguous",
    "trunk (anatomy)",
    "body part in mouth",
    "voyeur",
    "floating head",
    "shanghai doll",
    "cucujoid",
    "snoot game",
    "raphe (anatomy)",
    "pantsu shot",
    "taurified",
    "ventrexian",
    # 明确不应进入白名单的 r18/r18g 错位 tag
    "topless male",
    "corpse",
    "half naked",
    "living sex doll",
    "naked penny",
    "bottomless male",
    "naked towel",
    "sex shot",
    "outside sex",
}

NOISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^score_\d+$"),
    re.compile(r"^[:;^=<>]?[\doOpP][-'Õ]?[\)\(\[\]dDpP/\\|]+$"),
    re.compile(r"^[oO0][\-_.~]?[3mMwWuUvV][\-_.~]?[oO0uU]$"),
    re.compile(r"^[^a-zA-Z0-9]+$"),
    re.compile(r"\s+\d{3,}$"),
    re.compile(r"\s+[a-z0-9]{6,}$"),
    re.compile(r"^[a-z]+[A-Z][a-zA-Z]*$"),
    re.compile(r"^[a-z]+\d+$"),
    re.compile(r"\d+mm$"),
    re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$"),  # 时间码 05:06:00
]

# 预编译类别级正则白名单，避免 build 过程中重复编译。
_COMPILED_CATEGORY_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    category: [re.compile(pattern) for pattern in patterns]
    for category, patterns in config.CATEGORY_TAG_PATTERNS.items()
}


# 保留的括号消歧义词（其余带括号 tag 视为角色/作品名而丢弃）。
_ALLOWED_PAREN: set[str] = {
    "symbol",
    "sky",
    "structure",
    "anatomy",
    "marking",
    "species",
    "creature",
    "place",
    "clothing",
    "feature",
    "object",
    "medium",
    "artwork",
    "style",
    "pattern",
    "fastener",
    "jewelry",
    "weapon",
    "instrument",
    "ornament",
    "gem",
    "metal",
    "substance",
    "shape",
    "food",
    "flower",
    "plant",
    "fruit",
    "coloring",
    "hair",
    "body_type",
    "expression",
    "action",
    "nonsexual",
    "sexual",
    "restraint",
    "basic",
    "projectile",
    "tool",
    "season",
    "temperature",
}


def _normalize_tag(tag: str) -> str:
    """统一 tag 格式：下划线/连字符转空格、小写、去首尾空白。"""
    return tag.strip().replace("_", " ").replace("-", " ").lower()


# 确保外部精确覆盖表的 key 与内部归一化格式一致。
EXACT_RATING_OVERRIDES.update(
    {_normalize_tag(k): v for k, v in EXTRA_EXACT_OVERRIDES.items()}
)

# 同样对外部关键词做归一化，避免下划线/连字符导致匹配失败。
for _rating, _kws in EXTRA_RATING_KEYWORDS.items():
    RATING_KEYWORDS.setdefault(_rating, []).extend(_normalize_tag(kw) for kw in _kws)

# 用户手工精选的 r18 白名单：并入精确覆盖表，确保重建时评级恒为 r18。
for _tags in R18_MANUAL_WHITELIST.values():
    for _t in _tags:
        EXACT_RATING_OVERRIDES[_normalize_tag(_t)] = "r18"


def _matches_category_patterns(tag: str, category: str) -> bool:
    """检查 tag 是否满足 config.CATEGORY_TAG_PATTERNS 中该类别的白名单正则。"""
    patterns = _COMPILED_CATEGORY_PATTERNS.get(category)
    if not patterns:
        return True
    normalized = _normalize_tag(tag)
    return any(pattern.search(normalized) for pattern in patterns)


def is_metadata_or_noise(tag: str) -> bool:
    """判断 tag 是否为元数据 / 噪声 / 角色名，应被排除在白名单外。"""
    normalized = _normalize_tag(tag)
    if not normalized:
        return True

    # 长度过滤
    if len(normalized) < config.MIN_TAG_LEN or len(normalized) > config.MAX_TAG_LEN:
        return True

    # 元数据 / 质量标签（同时按归一化形式匹配，处理带连字符条目）
    if normalized in METADATA_TAGS or tag.strip().lower() in METADATA_TAGS:
        return True

    # 括号内不是常见消歧义词 -> 角色 / 作品 / 版权
    paren_match = re.search(r"\(([^)]+)\)$", normalized)
    if paren_match:
        inner = paren_match.group(1).lower().strip()
        if "/" in inner or inner not in _ALLOWED_PAREN:
            return True

    # 噪声正则
    for pattern in NOISE_PATTERNS:
        if pattern.search(normalized):
            return True

    # 复用 config 中的精确黑名单与正则黑名单；关键词黑名单改用本地宽松版本。
    # 同时检查归一化形式（下划线/连字符转空格）与原始小写形式，避免 "1uped-art" 漏判。
    if (
        normalized in config.EXACT_EXCLUDE_TAGS
        or tag.strip().lower() in config.EXACT_EXCLUDE_TAGS
    ):
        return True
    if _BUILD_EXCLUDE_PATTERN is not None and _BUILD_EXCLUDE_PATTERN.search(
        normalized
    ):
        return True
    for pattern in config.EXCLUDE_PATTERNS:
        if re.search(pattern, normalized):
            return True

    return False


def _keyword_matches(tag_lower: str, keyword: str) -> bool:
    """检查 keyword 是否命中 tag。

    多词短语使用子串匹配；单关键词使用单词边界，避免 "membrane" 误命中 "bra"。
    keyword 与 tag 使用相同的归一化规则（连字符转空格），保证 "see-through" 能命中
    "see through dress"。
    """
    keyword = keyword.replace("-", " ")
    if " " in keyword:
        return keyword in tag_lower
    return re.search(r"\b" + re.escape(keyword) + r"\b", tag_lower) is not None


def classify_tag(tag: str) -> str:
    """基于客观字面含义为 tag 分配年龄分级。"""
    normalized = _normalize_tag(tag)

    # 精确覆盖
    if normalized in EXACT_RATING_OVERRIDES:
        return EXACT_RATING_OVERRIDES[normalized]

    # 长短语优先匹配
    for keyword, rating in _FLAT_KEYWORDS:
        if _keyword_matches(normalized, keyword):
            return rating

    return "general"


def _fetch_chinese_for_tags(csv_path: Path, want: set[str]) -> dict[str, str]:
    """流式扫描 CSV，为目标 tag 收集 chinese 翻译（全部找到后提前结束）。"""
    result: dict[str, str] = {}
    remaining = set(want)
    if not remaining:
        return result
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            english = (row.get("english") or "").strip()
            if not english:
                continue
            norm = _normalize_tag(english)
            if norm in remaining:
                result[norm] = (row.get("chinese") or "").strip()
                remaining.discard(norm)
                if not remaining:
                    break
    return result


def build_curated_tags(
    csv_path: str | Path | None = None,
    top_n: int = 300,
) -> dict[str, list[dict[str, Any]]]:
    """读取 CSV，过滤噪声，评级，并按内部类别返回前 top_n 条 tag。

    Args:
        csv_path: 源 CSV 路径，默认使用 config.TAG_SOURCE_FILE。
        top_n: 每个内部类别保留的最大 tag 数。

    Returns:
        ``{category: [{tag, chinese, rating, category, subcategory, index}, ...]}``
    """
    csv_path = Path(csv_path or config.TAG_SOURCE_FILE)
    curated: dict[str, list[dict[str, Any]]] = {
        key: [] for key in config.DEFAULT_SAMPLE_COUNTS
    }
    missing_categories = set(curated.keys())

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row_index, row in enumerate(reader):
            english = (row.get("english") or "").strip()
            if not english:
                continue

            if english.startswith("score_"):
                tag = english
            else:
                tag = english.replace("_", " ")

            if is_metadata_or_noise(tag):
                continue

            category = (row.get("category") or "").strip()
            subcategory = (row.get("subcategory") or "").strip()
            internal_category = config.resolve_internal_category(category, subcategory)

            # tag 级覆盖
            tag_override = config.TAG_TO_CATEGORY_OVERRIDES.get(_normalize_tag(tag))
            if tag_override:
                internal_category = tag_override

            if internal_category not in curated:
                continue

            # 应用类别级白名单正则，剔除 subcategory 映射错误导致的错位噪声。
            if not _matches_category_patterns(tag, internal_category):
                continue

            # 少女向过滤：排除男性/成熟女性相关 tag。
            if not _is_female_only_tag(tag):
                continue

            # 人类/少女向过滤：排除纯兽人、深肤/非人肤色、非人形态 tag。
            # 允许兽耳、兽尾、角（头饰）等部分兽类特征。
            if not _is_human_like_tag(tag):
                continue

            # 每个类别集满 top_n 后提前结束，避免扫描整个大 CSV。
            if internal_category not in missing_categories:
                continue

            rating = classify_tag(tag)
            curated[internal_category].append(
                {
                    "tag": tag,
                    "chinese": (row.get("chinese") or "").strip(),
                    "rating": rating,
                    "category": category,
                    "subcategory": subcategory,
                    "index": row_index,
                }
            )

            if len(curated[internal_category]) >= top_n:
                missing_categories.discard(internal_category)
                if not missing_categories:
                    break

    # 合并用户手工精选的 r18 白名单：
    # 无条件保留并评 r18（不受 top_n 截断影响），缺失的 chinese 从 CSV 补取。
    wl_tags = {
        _normalize_tag(t) for tags in R18_MANUAL_WHITELIST.values() for t in tags
    }
    wl_chinese = _fetch_chinese_for_tags(csv_path, wl_tags) if wl_tags else {}
    existing_norms: dict[str, dict[str, Any]] = {
        _normalize_tag(item["tag"]): item
        for cat_items in curated.values()
        for item in cat_items
    }
    for category, tags in R18_MANUAL_WHITELIST.items():
        for tag in tags:
            norm = _normalize_tag(tag)
            item = existing_norms.get(norm)
            if item is not None:
                item["rating"] = "r18"
                continue
            new_item: dict[str, Any] = {
                "tag": tag,
                "chinese": wl_chinese.get(norm, ""),
                "rating": "r18",
                "category": "",
                "subcategory": "",
                "index": -1,
            }
            curated.setdefault(category, []).append(new_item)
            existing_norms[norm] = new_item

    return curated


def save_curated_tags(
    curated: dict[str, list[dict[str, Any]]],
    output_path: str | Path | None = None,
) -> Path:
    """将 curated tags 保存为 YAML 文件。"""
    output_path = Path(output_path or config.CURATED_TAGS_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 仅保留白名单需要的字段，按类别分组。
    yaml_data: dict[str, list[dict[str, str]]] = {}
    for category, items in curated.items():
        yaml_data[category] = [
            {
                "tag": item["tag"],
                "rating": item["rating"],
                "chinese": item.get("chinese", ""),
            }
            for item in items
        ]

    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(
            yaml_data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    return output_path


def print_rating_distribution(curated: dict[str, list[dict[str, Any]]]) -> None:
    """打印每个类别的分级分布。"""
    print("\n分级分布（按类别 / 按 rating）：")
    total_by_rating: dict[str, int] = {r: 0 for r in RATING_ORDER}
    for category, items in curated.items():
        counts: dict[str, int] = {r: 0 for r in RATING_ORDER}
        for item in items:
            counts[item["rating"]] += 1
            total_by_rating[item["rating"]] += 1
        summary = ", ".join(f"{r}={counts[r]}" for r in RATING_ORDER)
        print(f"  {category}: {len(items)} ({summary})")
    total = sum(total_by_rating.values())
    total_summary = ", ".join(
        f"{r}={total_by_rating[r]} ({total_by_rating[r] / total * 100:.1f}%)"
        for r in RATING_ORDER
        if total
    )
    print(f"  total: {total} ({total_summary})")


def main() -> int:
    """CLI 入口：重建 curated_tags.yaml 并打印统计。"""
    curated = build_curated_tags(top_n=500)
    output_path = save_curated_tags(curated)
    print(f"已保存 curated tags 到 {output_path}")
    print_rating_distribution(curated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
