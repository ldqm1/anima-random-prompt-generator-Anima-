"""模块级配置与路径常量。"""

from pathlib import Path
from typing import Any

# 项目根目录：根据本文件位置自动推导（config.py 位于
# <root>/prompt/random_generator/config.py，向上三级即项目根），
# 保证项目整体拷贝/打包到任意位置后无需修改路径。
PROJECT_DIR: Path = Path(__file__).resolve().parent.parent.parent
SOURCE_DIR: Path = PROJECT_DIR / "source"
KNOWLEDGE_BASE_DIR: Path = PROJECT_DIR / "知识库"
OUTPUT_DIR: Path = PROJECT_DIR / "output"

DEFAULT_SAMPLE_COUNTS: dict[str, int] = {
    "count_gender": 2,
    "appearance": 12,
    "clothing_state": 9,
    "pose_action_sex": 10,
    "expression_reaction": 6,
    "camera_shot": 5,
    "scene_environment": 11,
    "detail_mood": 9,
}

KNOWLEDGE_V1_DIR: Path = KNOWLEDGE_BASE_DIR / "v1"

# 知识库 v1 文件名到内部类别的映射。
# 同一个文件可能服务于多个内部类别，由 ``map_knowledge_v1_to_internal`` 按 CAT 细分。
KNOWLEDGE_TAG_FILES: dict[str, list[str]] = {
    "count_gender": ["tags_人物.txt"],
    "appearance": ["tags_人物.txt"],
    "expression_reaction": ["tags_人物.txt", "tags_表情动作.txt"],
    "pose_action_sex": ["tags_人物.txt", "tags_表情动作.txt"],
    "clothing_state": ["tags_服饰.txt"],
    "camera_shot": ["tags_镜头.txt"],
    "scene_environment": ["tags_场景.txt", "tags_环境.txt", "tags_画面.txt", "tags_物品.txt"],
    "detail_mood": ["tags_场景.txt", "tags_环境.txt", "tags_画面.txt", "tags_物品.txt"],
    "character_series": ["tags_二次元角色.txt"],
}

DEFAULT_KNOWLEDGE_SAMPLE_COUNTS: dict[str, int] = {
    "count_gender": 10,
    "appearance": 10,
    "clothing_state": 10,
    "pose_action_sex": 10,
    "expression_reaction": 10,
    "camera_shot": 10,
    "scene_environment": 10,
    "detail_mood": 10,
    "character_series": 1,
    "creative_anchor": 2,
}

DEEPSEEK_API_BASE: str = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL: str = "deepseek-chat"

ARTIST_BLACKLIST_FILES: list[Path] = [
    SOURCE_DIR / "animadex_index.csv",
    SOURCE_DIR / "artists.csv",
]

TAG_SOURCE_FILE: Path = SOURCE_DIR / "danbooru_e261_updated.csv"
CURATED_POOLS_FILE: Path = OUTPUT_DIR / "curated_pools.json"
CURATED_TAGS_FILE: Path = PROJECT_DIR / "prompt" / "random_generator" / "curated_tags.yaml"
SEMANTIC_EXCLUDE_FILE: Path = (
    PROJECT_DIR / "prompt" / "random_generator" / "semantic_exclude.yaml"
)
R18_EUPHEMISMS_FILE: Path = PROJECT_DIR / "prompt" / "random_generator" / "r18_euphemisms.yaml"
R18_TOPICS_FILE: Path = PROJECT_DIR / "prompt" / "random_generator" / "r18_topics.yaml"
GENERATION_CONFIG_FILE: Path = (
    PROJECT_DIR / "prompt" / "random_generator" / "generation_config.yaml"
)
CHARACTER_POOL_FILE: Path = PROJECT_DIR / "prompt" / "random_generator" / "character_pool.json"
CHARACTER_POOL_SERIES_INDEX_FILE: Path = (
    PROJECT_DIR / "prompt" / "random_generator" / "character_pool_series_index.json"
)
# 创意锚点池（高概念设定，用于打破场景/动作/道具趋同）
CREATIVE_ANCHORS_FILE: Path = (
    PROJECT_DIR / "prompt" / "random_generator" / "creative_anchors.yaml"
)

# 年龄分级顺序（由宽松到严格）。
RATING_ORDER: list[str] = ["general", "pg12", "r15", "r18", "r18g"]
DEFAULT_MAX_RATING: str = "r15"

#: r18 模式下每个样本至少抽到的 r18 评级 tag 数量（0 表示不强制；仅 max_rating=r18 时生效）。
DEFAULT_MIN_R18_TAGS_PER_SAMPLE: int = 5

#: r18 模式下注入到 LLM 用户提示词的自定义指令文本（仅提供注入机制，默认留空）。
DEFAULT_R18_INSTRUCTIONS: str = ""

# 直接丢弃的 category。
EXCLUDED_CATEGORIES: set[str] = {
    "二次元角色",  # 角色/作品名
    "艺术家",     # 画师名与元数据
    "无法分类",   # 大多为噪声元数据
}

# 直接丢弃的 (category, subcategory) 对。
EXCLUDED_SUBCATEGORIES: set[tuple[str, str]] = {
    ("物品", "成人玩具"),  # 明确成人用品，整类排除
    ("人物", "身份（职业）"),  # 职业/角色标签会污染 appearance，整类排除
    ("人物", "性器官"),  # 直接涉及性器官，整体排除
    ("表情动作", "颜文字"),  # 颜文字 tag 多为噪声/梗
}

# 精确匹配丢弃的 tag（小写、空格形式）。
EXACT_EXCLUDE_TAGS: set[str] = {
    # 男性性别/外貌
    "1boy",
    "2boys",
    "3boys",
    "4boys",
    "5boys",
    "6+boys",
    "multiple boys",
    "male focus",
    "male only",
    "male",
    "males",
    "man",
    "men",
    "boy",
    "boys",
    "beard",
    "bearded",
    "facial hair",
    "adam's apple",
    "pectorals",
    "pectoral",
    "muscular male",
    "muscular man",
    "muscular men",
    "bara",
    "shota",
    "trap",
    "femboy",
    "cuntboy",
    "dickgirl",
    "futanari",
    "futa",
    "shemale",
    "gynomorph",
    "andromorph",
    "intersex",
    "herm",
    "hermaphrodite",
    "ejaculating while penetrated",
    "old man",
    "old men",
    "elderly man",
    "elderly men",
    "uncle",
    "grandfather",
    "husband",
    "gentleman",
    "father",
    # 全身/躯体兽化 furry
    "furry",
    "furry female",
    "furry male",
    "kemono",
    "anthro",
    "taur",
    "animal head",
    "muzzle",
    "snout",
    "beak",
    "hoof",
    "hooves",
    "hooved",
    "furred",
    "scaly",
    "scaled",
    "feathered",
    "feral",
    "full body fur",
    "fur covered",
    "body fur",
    "detailed fur",
    "realistic fur",
    "wet fur",
    "dry fur",
    "fluffy fur",
    "soft fur",
    "neck fur",
    "chest fur",
    "monotone fur",
    "multicolored fur",
    "multitone fur",
    "multi-colored fur",
    "multi-tone fur",
    "short fur",
    "long fur",
    "gradient fur",
    "argonian",
    "fish tail",
    "mermaid",
    "merman",
    "merfolk",
    "winged arm",
    "winged arms",
    "winged leg",
    "winged legs",
    "winged body",
    # 明确性行为动词（仅保留男性相关/肛交/r18g；其余交由评级表 + max_rating 管理）
    "penetration",
    "fellatio",
    "rape",
    "molestation",
    "molesting",
    "blowjob",
    "rimjob",
    "anal",
    "anal sex",
    "fisting",
    "gangbang",
    "paizuri",
    "titfuck",
    "footjob",
    "handjob",
    "facial",
    "asphyxiation",
    "cannibalism",
    "oral",
    "oral sex",
    "group sex",
    "double penetration",
    "triple penetration",
    "bestiality",
    "zoophilia",
    "incest",
    "lolicon",
    "shotacon",
    # 明确性相关体液/器官/性暗示 framing（仅保留男性/肛交/r18g；其余移出）
    "cum",
    "semen",
    "throat bulge",
    "balls on face",
    "jerking",
    "anal only",
    "human penetrated",
    "testicles touching",
    "muscular child",
    "severed arm",
    "severed leg",
    "detached ears",
    "at knifepoint",
    "manspreading",
    # 明显色情/恋物 framing（interracial 保留，其余移出）
    "interracial",
    # 性器官（仅保留男性器官；女性器官交由评级表管理）
    "penis",
    "dick",
    "cock",
    # 巨乳（用户审美：超过正常人类大小，任何评级模式都排除）
    "huge breasts",
    "gigantic breasts",
    "hyper breasts",
    # 兽人/变身/非穿戴动物肢体
    "therianthrope",
    "centaur",
    "bone tail",
}

# 按子串匹配的噪声关键词（避免过宽，子串匹配会误伤则不加入）。
EXCLUDE_KEYWORDS: set[str] = {
    "artist_name",
    "copyright_name",
    "twitter_username",
    "twitter_id",
}

# 正则排除模式（针对归一化后的小写空格 tag）。
EXCLUDE_PATTERNS: list[str] = [
    # 男性相关（仅命中带数字前缀或独立成词的 boy(s)，避免误伤 tomboy/cowboy 等）
    r"\b\d+boys?\b",
    r"\bboy\b",
    r"\bboys\b",
    r"\b\d*males?\b",
    r"\b\d*men\b",
    r"\b\d*man\b",
    r"\bmuscular\s+(male|man|men|boy|boys)\b",
    r"\b(old|elderly)\s+(man|men)\b",
    r"\badam's\s+apple\b",
    # 全身/躯体兽化 furry（仅排除完整兽化、头部/非穿戴动物肢体）
    r"\bfurry\b",
    r"\bkemono\b",
    r"\banthro\b",
    r"\btaur\b",
    r"\banimal\s+head\b",
    r"\bmuzzle\b",
    r"\bsnout\b",
    r"\bbeak\b",
    r"\bhoof(?:ed|es)?\b",
    r"\bfurred\b",
    r"\bscaly\b",
    r"\bscaled\b",
    r"\bscales?\b",
    r"\bfeathered\b",
    r"\bferal\b",
    r"\bgradient\s+fur\b",
    r"\bargonian\b",
    r"\bfull\s+body\s+fur\b",
    r"\bfur\s+covered\b",
    r"\bbody\s+fur\b",
    r"\b(gradient|detailed|realistic|wet|dry|fluffy|soft|monotone|multicolored|multi[- ]?colored|multitone|multi[- ]?tone|short|long)\s+fur\b",
    r"\b(neck|chest|body)\s+fur\b",
    r"\bfish\s+tail\b",
    r"\bmermaid\b",
    r"\bmerman\b",
    r"\bmerfolk\b",
    r"\bwinged\s+(?:arm|leg|body)s?\b",
    # 明确性行为及相关体液/性暗示 framing（仅保留男性/肛交/r18g；其余移出，交由评级表管理）
    r"\bpenetration\b",
    r"\bfellatio\b",
    r"\brape\b",
    r"\bmolestation\b",
    r"\bmolesting\b",
    r"\bblowjob\b",
    r"\brimjob\b",
    r"\banal\s+sex\b",
    r"\boral\s+sex\b",
    r"\bgroup\s+sex\b",
    r"\bdouble\s+penetration\b",
    r"\btriple\s+penetration\b",
    r"\bfisting\b",
    r"\bpaizuri\b",
    r"\btitfuck\b",
    r"\bfootjob\b",
    r"\bhandjob\b",
    r"\bfacial\b",
    r"\basphyxiation\b",
    r"\bcannibalism\b",
    r"\bgangbang\b",
    r"\bbestiality\b",
    r"\bzoophilia\b",
    r"\bincest\b",
    r"\blolicon\b",
    r"\bshotacon\b",
    r"\bthroat\s+bulge\b",
    r"\bmanspreading\b",
    r"\bballs\s+on\s+face\b",
    r"\binterracial\b",
    r"\bpenis\b",
    r"\bdick\b",
    r"\bcock\b",
    r"\banal\b",
    r"\bcum\b",
    r"\bsemen\b",
    r"\btherianthrope\b",
    r"\bbone\s+tail\b",
    r"\bhuman\s+penetrated\b",
    r"\btesticles?\s+touching\b",
    r"\bmuscular\s+child\b",
    r"\bsevered[- ]?(arm|leg)\b",
    r"\bdetached[- ]?ears?\b",
    r"\bat\s+knifepoint\b",
    # 巨乳（用户审美：超过正常人类大小，任何评级模式下都排除）
    r"\b(huge|gigantic|hyper|enormous)[- ]?breasts?\b",
    r"\b(huge|gigantic|hyper|enormous)[- ]?boobs?\b",
    # 阴毛类 tag 全局排除（任何评级模式下都不出现，用户审美要求）
    r"\bpubic\s+hair\b",
    r"\bpubes\b",
]

# 类别级正则白名单（空表示不启用）。
CATEGORY_TAG_PATTERNS: dict[str, list[str]] = {}

# 按 (category, subcategory) 精确映射到 8 个内部类别。
# 未命中时由 DEFAULT_INTERNAL_CATEGORY 兜底。
CATEGORY_MAPPINGS: dict[tuple[str, str], str] = {
    # ---------- count_gender ----------
    ("人物", "对象"): "count_gender",

    # ---------- appearance ----------
    ("人物", "头发发型"): "appearance",
    ("人物", "眼睛"): "appearance",
    ("人物", "身材"): "appearance",
    ("人物", "皮肤"): "appearance",
    ("人物", "胸部"): "appearance",
    ("人物", "腿部"): "appearance",
    ("人物", "翅膀"): "appearance",
    ("人物", "指甲"): "appearance",
    ("人物", "腹部"): "appearance",
    ("人物", "牙齿"): "appearance",
    ("人物", "脸型"): "appearance",
    ("人物", "鼻子"): "appearance",
    ("人物", "瞳孔"): "appearance",
    ("人物", "眉毛"): "appearance",
    ("人物", "肩部"): "appearance",
    ("人物", "腰部"): "appearance",
    ("人物", "舌头"): "appearance",
    ("人物", "年龄"): "appearance",
    ("人物", "非人特征"): "appearance",

    # ---------- expression_reaction ----------
    ("人物", "面部"): "expression_reaction",
    ("人物", "嘴巴"): "expression_reaction",
    ("表情动作", "笑"): "expression_reaction",
    ("表情动作", "哭"): "expression_reaction",
    ("表情动作", "惊讶"): "expression_reaction",
    ("表情动作", "生气"): "expression_reaction",
    ("表情动作", "不开心"): "expression_reaction",
    ("表情动作", "蔑视"): "expression_reaction",
    ("表情动作", "其他表情"): "expression_reaction",
    ("表情动作", "颜文字"): "expression_reaction",

    # ---------- pose_action_sex ----------
    ("人物", "性器官"): "pose_action_sex",
    ("表情动作", "姿势"): "pose_action_sex",
    ("表情动作", "体位"): "pose_action_sex",
    ("表情动作", "基础动作"): "pose_action_sex",
    ("表情动作", "其他动作"): "pose_action_sex",
    ("表情动作", "手部动作"): "pose_action_sex",
    ("表情动作", "腿部动作"): "pose_action_sex",
    ("表情动作", "手放在某地"): "pose_action_sex",
    ("表情动作", "手抓着某物"): "pose_action_sex",
    ("表情动作", "性爱动作"): "pose_action_sex",
    ("表情动作", "手部拿着某物"): "pose_action_sex",

    # ---------- clothing_state ----------
    ("服饰", "上半身服装"): "clothing_state",
    ("服饰", "下半身服装"): "clothing_state",
    ("服饰", "袜子"): "clothing_state",
    ("服饰", "鞋子"): "clothing_state",
    ("服饰", "头部装饰物"): "clothing_state",
    ("服饰", "脸部装饰物"): "clothing_state",
    ("服饰", "手部装饰物"): "clothing_state",
    ("服饰", "腿部装饰物"): "clothing_state",
    ("服饰", "衣服装饰"): "clothing_state",
    ("服饰", "衣服风格"): "clothing_state",
    ("服饰", "衣服花纹"): "clothing_state",
    ("服饰", "正装"): "clothing_state",
    ("服饰", "衣服套装"): "clothing_state",
    ("服饰", "裤子"): "clothing_state",
    ("服饰", "裙子"): "clothing_state",
    ("服饰", "围巾"): "clothing_state",
    ("服饰", "其他装饰物"): "clothing_state",
    ("服饰", ""): "clothing_state",

    # ---------- camera_shot ----------
    ("镜头", "人物构图"): "camera_shot",
    ("镜头", "人物视觉朝向"): "camera_shot",
    ("镜头", "特写镜头"): "camera_shot",
    ("镜头", "镜头角度"): "camera_shot",
    ("镜头", "效果"): "camera_shot",
    ("镜头", "其他沟通"): "camera_shot",

    # ---------- scene_environment ----------
    ("场景", "室内"): "scene_environment",
    ("场景", "室外"): "scene_environment",
    ("场景", "城市"): "scene_environment",
    ("环境", "大自然"): "scene_environment",
    ("环境", "天气"): "scene_environment",
    ("环境", "氛围"): "scene_environment",
    ("环境", "天空"): "scene_environment",
    ("环境", "水"): "scene_environment",
    ("环境", "季节"): "scene_environment",
    ("环境", "云"): "scene_environment",
    ("环境", ""): "scene_environment",
    ("画面", "背景"): "scene_environment",
    ("物品", "其他物品"): "scene_environment",
    ("物品", "动物"): "scene_environment",
    ("物品", "食物"): "scene_environment",
    ("物品", "武器"): "scene_environment",
    ("物品", "数码设备"): "scene_environment",
    ("物品", "植物"): "scene_environment",
    ("物品", "乐器"): "scene_environment",
    ("物品", "餐具"): "scene_environment",
    ("物品", "学习用品"): "scene_environment",
    ("物品", ""): "scene_environment",

    # ---------- detail_mood ----------
    ("画面", "画面量质"): "detail_mood",
    ("画面", "艺术风格"): "detail_mood",
    ("画面", "艺术类型"): "detail_mood",
    ("画面", "颜色"): "detail_mood",
    ("画面", "光照"): "detail_mood",
    ("画面", "画笔"): "detail_mood",
    ("画面", "艺术派系"): "detail_mood",
    ("画面", "艺术家风格"): "detail_mood",
    ("画面", ""): "detail_mood",
}

DEFAULT_INTERNAL_CATEGORY: str = "detail_mood"

# tag 长度限制（按归一化后的字符数计算）。
MIN_TAG_LEN: int = 2
MAX_TAG_LEN: int = 60

# 是否丢弃没有中文翻译（chinese 为空或仅 "..."）的 tag。
REQUIRE_NON_EMPTY_CHINESE: bool = True

# 括号内为常见消歧义词时保留；否则视为角色/作品名而丢弃。
PAREN_DISAMBIGUATION_OK: set[str] = {
    "symbol", "sky", "structure", "anatomy", "marking", "species", "creature",
    "place", "clothing", "feature", "object", "medium", "artwork", "style",
    "pattern", "fastener", "jewelry", "weapon", "instrument", "ornament",
    "gem", "metal", "substance", "shape", "food", "flower", "plant", "fruit",
    "coloring", "hair", "body_type", "expression", "action", "nonsexual",
    "sexual", "restraint", "cheerleading", "basic", "projectile", "tool",
    "lore", "mtf", "ftm", "gvh", "bhp", "psg", "kari", "season", "temperature",
}

# 特定 tag 覆盖映射：解决 subcategory 粒度不够的问题。
TAG_TO_CATEGORY_OVERRIDES: dict[str, str] = {
    # 人数/关系 tag 被放到 镜头/人物构图 或 表情动作/性爱动作 中，需要纠正
    "solo": "count_gender",
    "duo": "count_gender",
    "trio": "count_gender",
    "group": "count_gender",
    "1other": "count_gender",
    "2others": "count_gender",
    "3others": "count_gender",
    "4others": "count_gender",
    "5others": "count_gender",
    "hetero": "count_gender",
    # 裸露状态应归到服装状态
    "nude": "clothing_state",
    "completely nude": "clothing_state",
    "topless": "clothing_state",
    "bottomless": "clothing_state",
    "no clothes": "clothing_state",
    "bare body": "clothing_state",
    "fully exposed": "clothing_state",
    "partially undressed": "clothing_state",
}

# ---- 介质/噪音 meta tag 黑名单（无画面语义的媒介/封面/版面/文字标注/出处词）----
#: 与内容分级无关：r18 模式跳过禁词替换时仍生效。不包含 8-bit / thick lineart /
#: droste effect / pixelated / highres / lowres 等有画风语义或质量前缀体系的词。
NOISE_META_TAGS: frozenset[str] = frozenset(
{
        # ---- 媒介/封面/页面格式 ----
        "manga cover",
        "cover art",
        "cover image",
        "cover page",
        "page number",
        "textless version",
        "game cover",
        "novel cover",
        "book cover",
        "light novel cover",
        "magazine cover",
        "magazine page",
        "manga page",
        "album cover",
        "dvd cover",
        "blu-ray cover",
        "official cover",
        "doujinshi cover",
        "doujin cover",
        "back cover",
        "box art",
        "fake cover",
        "fake magazine cover",
        "laserdisc cover",
        "album cover redraw",
        "book cover redraw",
        "video game cover redraw",
        "comic book cover",
        "comic cover",
        "comic panel",
        "comic panel redraw",
        "magazine scan",
        "mini comic",
        "2koma",
        "3koma",
        "4koma",
        "instant loss 2koma",
        "3 panel comic",
        "4 panel comic",
        "5 panel comic",
        "6 panel comic",
        "8 panel comic",
        "one page comic",
        "one panel comic",
        "numbered panels",
        "panel border",
        "page tear",
        "cut-here line",
        "right-to-left comic",
        "left-to-right manga",
        "silent comic",
        "segmented comic",
        "borderless panels",
        "key frame",
        "smear frame",
        "negative frames",
        "sketch page",
        "title page",
        "title screen",
        "end card",
        "end roll",
        "eyecatch",
        "key visual",
        "loading screen",
        "to be continued",
        "official art",
        "official art inset",
        "official wallpaper",
        "wallpaper",
        "sprite sheet",
        "blank page",
        "pages",
        "video game cover",
        "video game cover (object)",
        "screenshot background",
        "screencap background",
        "game screenshot background",
        # ---- 图表/资料卡 ----
        "character chart",
        "costume chart",
        "expression chart",
        "height chart",
        "equipment layout",
        "progress bar",
        "profile picture",
        "icon",
        "thumbnail",
        "thumbnail collage",
        "thumbnail surprise",
        "preview",
        "chart",
        "eye chart",
        "radar chart",
        "kiss chart",
        "character profile",
        "column lineup",
        "height mark",
        "length markings",
        # ---- 平台/出处/文件/媒介形式 ----
        "deviantart",
        "nijie",
        "newtype flash",
        "waifu2x",
        "pixiv fantasia",
        "pixiv fantasia 2",
        "pixiv fantasia 3",
        "pixiv fantasia 5",
        "pixiv fantasia age of starlight",
        "pixiv fantasia fallen kings",
        "pixiv fantasia new world",
        "pixiv fantasia t",
        "pixiv fantasia wizard and knight",
        "pixiv fantasia mountain of heaven",
        "pixiv fantasia scepter of zeraldia",
        "pixiv sample",
        "pixiv red",
        "pixiv shadow",
        "twitch.tv",
        "youtube",
        "youtube thumbnail",
        "youtube creator award",
        "twitter",
        "twitter banner",
        "twitter bird",
        "twitter strip game",
        "facebook",
        "fanbox",
        "anilive",
        "banner",
        "logo",
        "ai-assisted",
        "ai-generated",
        "commission",
        "game cg",
        "srw battle screen",
        "media player interface",
        "desktop",
        "file",
        "png file",
        "psd available",
        "huge filesize",
        "downsized",
        "resized",
        "upscaled",
        "scan",
        "screencap",
        "screencap redraw",
        "screenshot",
        "screenshot inset",
        "screenshot redraw",
        "game screenshot",
        "game screenshot inset",
        "anime screenshot",
        "twitter screenshot",
        "cellphone photo",
        "fake phone screenshot",
        "fake screenshot",
        "fake photograph",
        "fake video",
        "animated",
        "animated gif",
        "animated png",
        "looping animation",
        "ugoira",
        "live2d",
        "2d animation",
        "3d animation",
        "gif",
        "video",
        "source larger",
        "source quote parody",
        "bad aspect ratio",
        "long image",
        "tall image",
        "wide image",
        # ---- 文字/语言标注 ----
        "japanese text",
        "english text",
        "french text",
        "german text",
        "korean text",
        "chinese text",
        "russian text",
        "spanish text",
        "traditional chinese text",
        "romaji text",
        "engrish text",
        "fake text",
        "backwards text",
        "mirrored text",
        "upside-down text",
        "rainbow text",
        "black text",
        "white text",
        "pixel text",
        "bilingual",
        "subtitled",
        "multiple subs",
        "text-only page",
        "text focus",
        "caption",
        "dialogue",
        "narration",
        "furigana",
        "onomatopoeia",
        "spoken exclamation mark",
        "spoken sound effect",
        "spoken sparkle",
        "background text",
        "foreground text",
        "text background",
        "text box",
        "wall of text",
        "kaomoji",
        "damage numbers",
        # ---- 版面/边框标注 ----
        "multicolored border",
        "white border",
        "black border",
        "letterboxed",
        "pillarboxed",
        "border",
        "aqua border",
        "blue border",
        "brown border",
        "blurry border",
        "fading border",
        "floral border",
        "gold border",
        "gradient border",
        "green border",
        "grey border",
        "heart border",
        "inset border",
        "orange border",
        "ornate border",
        "outside border",
        "pink border",
        "polka dot border",
        "purple border",
        "red border",
        "round border",
        "striped border",
        "transparent border",
        "yellow border",
        "danmaku comments",
        "dialogue options",
        "directional arrow",
        "red circle",
        "circled 9",
        "watermark",
        "watermark grid",
        "sample watermark",
        "artist watermark",
        "character watermark",
        "miyoushe watermark",
        "too many watermarks",
        "has watermarked revision",
        "has bad revision",
        "has cropped revision",
        "signature",
        "script",
        "storyboard",
        # ---- 版本/创作过程标注 ----
        "derivative work",
        "alternate version",
        "alternate design",
        "official alternate art",
        "official alternate color",
        "official alternate design",
        "alternate cover",
        "alternate",
        "alternative",
        "alternate art style",
        "alternate color",
        "alternate element",
        "alternate size",
        "borrowed design",
        "redesign",
        "redrawn",
        "remake",
        "revision",
        "cleaned",
        "annotated",
        "partially annotated",
        "colored edit",
        "color edit",
        "color trace",
        "recolored",
        "colorized",
        "color switch",
        "color guide",
        "color study",
        "palette swap",
        "recurring image",
        "pixel-perfect duplicate",
        "art jam",
        "art study",
        "art-act",
        "artistic error",
        "art shift",
        "drawing this in your style challenge",
        "draw this in your style challenge",
        "one-hour drawing challenge",
        "multiple drawing challenge",
        "color wheel challenge",
        "heart-shaped boob challenge",
        "jack-o' challenge",
        "tegaki draw and tweet",
        "palette project",
        "irasutoya challenge",
        "gift art",
        "comparison",
        "before and after",
        "compilation",
        "making-of",
        "speedpaint",
        "time lapse",
        "photo-referenced",
        "reference photo",
        "reference inset",
        "scene reference",
        "comic edit",
        "character signature",
        "artist progress",
        "how to draw manga",
        "gundam perfect file",
        "traced",
        "polishing",
        "unfinished",
        "prototype design",
        "production art",
        "promotional art",
        "style request",
        "official style",
        "style parody",
        "multiple style parody",
        "poster parody",
        "fine art parody",
        "logo parody",
        "card parody",
        "satire",
        "parody",
        "meme",
        # ---- 其他无画面语义词 ----
        "meta",
        "mikumikudance",
        "comic cune",
        "comic exe",
        "comic hotmilk",
        "comic sigma",
        "comic unreal",
        "lineage 2",
        "countdown illustration",
        "cropped",
        "dated",
        "detexted",
        "educational",
        "emoticon",
        "face filter",
        "app filter",
        "fake transparency",
        "first stage production",
        "interlude",
        "modeling",
        "movie reference",
        "omake",
        "sequential",
        "social media composition",
        "sound effects",
        "sound effects only",
        "sfx",
        "template",
        "unconventional media",
        "the last supper",
        "the scream",
        "the birth of venus",
        "the creation of adam",
        "napoleon crossing the alps",
        "akira movie poster",
        "girl with a pearl earring",
        "pieta",
        "catherine cover parody",
        "world masterpiece theater",
        "alpha transparency",
        "transparent background",
    }
)

#: 后缀规则：命中即以噪音 meta tag 处理（覆盖未逐个列出的平台 logo
#: 与各语种文字标注，如 ``company logo``、``arabic text``）。
NOISE_META_SUFFIXES: tuple[str, ...] = (" logo", " text")

#: 归一化后的噪音黑名单：将 -/_ 统一为空格并转小写，与检索侧
#: ``retrieval._normalize_tag`` 保持一致。否则 ``cut-here line`` 等带连字符
#: 条目归一化后（``cut here line``）永远无法字面命中，造成泄漏。
_NOISE_META_TAGS_NORMALIZED: frozenset[str] = frozenset(
    t.strip().replace("_", " ").replace("-", " ").lower() for t in NOISE_META_TAGS
)


def is_noise_meta_tag(normalized: str) -> bool:
    """归一化后的 tag 是否为介质/噪音 meta tag（字面命中黑名单或 logo/text 后缀）。

    入参可能是检索侧已归一化（空格）或原始（含 ``-``/``_``）形式，函数内部
    再次统一格式后比对，保证连字符版本与空格版本都能命中黑名单。
    """
    key = normalized.strip().replace("_", " ").replace("-", " ").lower()
    if key in _NOISE_META_TAGS_NORMALIZED:
        return True
    return any(key.endswith(suffix) for suffix in NOISE_META_SUFFIXES)


def resolve_internal_category(category: str, subcategory: str) -> str | None:
    """根据 CSV 的 category/subcategory 返回内部类别名；None 表示丢弃。"""
    if category in EXCLUDED_CATEGORIES:
        return None
    if (category, subcategory) in EXCLUDED_SUBCATEGORIES:
        return None
    return CATEGORY_MAPPINGS.get((category, subcategory), DEFAULT_INTERNAL_CATEGORY)


# 白名单角色池默认配置。
DEFAULT_CHARACTER_WHITELIST: dict[str, Any] = {
    "enabled": False,
    "pool": [],
}

# 通用类别白名单默认配置。
DEFAULT_CATEGORY_WHITELISTS: dict[str, Any] = {
    "enabled": False,
    "pools": {
        "count_gender": [],
        "appearance": [],
        "clothing_state": [],
        "pose_action_sex": [],
        "expression_reaction": [],
        "camera_shot": [],
        "scene_environment": [],
        "detail_mood": [],
        "character_series": [],
    },
}

# Excel 角色池默认配置。
DEFAULT_CHARACTER_POOL: dict[str, Any] = {
    "enabled": False,
    "file": None,  # None 表示使用 CHARACTER_POOL_FILE
    "prefer_same_ip_for_multiple": True,
    "use_core_appearance": True,
    "use_core_clothing_probability": 0.5,
}

#: 多角色场景（如 2girls）触发时的自动调整默认配置。
#: 当抽样结果命中多角色标记（2girls / 3girls / 2boys / 3boys /
#: multiple girls / multiple boys）时：
#: - ``tag_count_bonus``: min_tags 与 max_tags 各增加的数量（n）。
#: - ``focus_character_bonus``: character 占比增加（m，百分比），
#:   并从 background 与 other 中按比例扣减相同额度。
#: ``enabled`` 为 False 时关闭双人/多人角色：人数/性别抽样强制为 ``1girl``，
#: 多角色触发调整与同 IP 角色池多人逻辑均不会生效。
#: ``probability``（0-1，默认 0.5）即多人角色占比：每条样本按该概率掷骰，
#: 命中则 count_gender 为 ``2girls``，否则为 ``1girl``（0.5 与原来的
#: 1girl/2girls 均等随机等价）。
DEFAULT_MULTI_CHARACTER: dict[str, Any] = {
    "enabled": True,
    "probability": 0.5,
    "tag_count_bonus": 20,
    "focus_character_bonus": 10,
}

#: r18 标签主题控制默认配置（仅 max_rating=r18/r18g 时生效）。
#: ``topics`` 为空时退化为完全随机补充；各主题具体默认值见 generation_config.yaml。
#: ``solo`` 为单人场景主题限制：``enabled`` 启用后，``disabled_topics`` 中的
#: 主题在单人场景（1girl/1boy 等非多人标记）下强制不激活，多人场景不受影响。
DEFAULT_R18_TOPIC_CONTROL: dict[str, Any] = {
    "enabled": True,
    "topics": {},
    "solo": {
        "enabled": True,
        "disabled_topics": ["oral", "penetration", "positions"],
    },
}

#: 角色池 IP 默认权重。
DEFAULT_CHARACTER_POOL_WEIGHT: int = 10

#: 人数/性别类别默认允许抽取的 tag，限定为单少女或双少女场景。
DEFAULT_COUNT_GENDER_TAGS: frozenset[str] = frozenset({"1girl", "2girls"})

#: 内部类别展示用中文名到内部类别名的映射。
# 用于支持用户在 generation_config.yaml 等配置文件中按中文类别名填写白名单池。
CATEGORY_DISPLAY_NAME_TO_INTERNAL: dict[str, str] = {
    "人数与性别": "count_gender",
    "外貌": "appearance",
    "服装与穿着状态": "clothing_state",
    "姿势/动作/体位": "pose_action_sex",
    "表情与反应": "expression_reaction",
    "镜头/景别/构图": "camera_shot",
    "场景与环境": "scene_environment",
    "画面质感/氛围": "detail_mood",
    "二次元角色": "character_series",
}
