#!/usr/bin/env python3
"""curated_tags.yaml 反趋同清洗（保守版）：
1. camera_shot: 删除元数据/计数/成人/无意义词，补齐结构性构图词
2. detail_mood: 删除媒体格式/水印/ai 垃圾词
3. expression_reaction: 删除明显非表情词（外貌/肢体/r18）
4. scene_environment: 删除品牌/媒体/恐怖/游戏角色名
保持 YAML 文本格式不变（逐行处理），输出统计。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(r"E:\code\Anima\anima-rag-knowledge-release\prompt\random_generator\curated_tags.yaml")

CAMERA_DROP = {
    "2others", "3others", "5others", "angle", "angle view", "above", "down view",
    "lens", "view", "side", "through medium", "zoom", "zoom in", "zoom out",
    "zooming in", "zoom layer", "zoom lines", "id photo", "mugshot", "camera view",
    "screen zoom", "red-eye effect", "rotating view", "pillarboxed", "photobomb",
    "being watched", "offscreen character", "height comparison", "size comparison",
    "lineup", "group picture", "group shot", "group profile", "front and back",
    "back side", "top-down bottom-up", "waterline view", "view between legs",
    "view from back", "viewed from above", "split depth", "unusual visible",
    "anus focus", "cervix view", "pussy close-up", "pussy focus", "pussy shot",
    "pantyshot", "panty shot", "pantyshot through reflection", "under skirt",
    "upskirt", "upskirt view", "extended downblouse", "extended upskirt",
    "blur censor", "censored", "censored by text", "emoji censor", "fake censor",
    "tail censor", "wing censor", "x-ray", "x-ray vision", "penetrating pov",
    "fellatio pov", "cuckold pov", "taker pov", "pov crotch", "pov peephole",
    "presenting anus", "butt focus", "butt shot", "butt view", "butt close-up",
    "butt from the front", "ass focus", "ass visible through thighs",
    "viewer holding leash", "viewer on leash", "genital close-up", "genital shot",
    "crotch focus", "implied pantyshot", "pov breasts", "pov legs", "pov hands",
    "eye behind hair", "eyes out of frame", "mouth out of frame", "mouth shot",
    "group", "trio", "duo",
}

DETAIL_DROP = {
    "png file", "psd available", "watermark", "watermark grid", "miyoushe watermark",
    "character watermark", "artist watermark", "sample watermark", "ai-generated",
    "ai-assisted", "jpeg artifacts", "huge filesize", "twitter screenshot",
    "deviantart", "nijie", "pixiv sample", "pixiv red", "pixiv shadow", "commission",
    "dated", "traced", "cleaned", "upscaled", "downscaled", "resized", "noise",
    "scan", "scan artifacts", "screencap", "screenshot", "screenshot inset",
    "screencap redraw", "subtitled", "text-only page", "title page", "end card",
    "eyecatch", "loading screen", "progress bar", "thumbnail", "thumbnail collage",
    "thumbnail surprise", "has bad revision", "has cropped revision",
    "has watermarked revision", "revision", "remake", "redrawn", "redesign",
    "alternate", "alternate art style", "alternate color", "alternate design",
    "alternate element", "alternate size", "alternative", "official alternate color",
    "official alternate design", "quality", "negative", "noise reduction",
    "recolored", "reversed", "rotated", "source larger",
    "character chart", "character profile", "costume chart", "expression chart",
    "height chart", "height mark", "length markings", "sprite sheet", "tachi-e",
    "2koma", "3koma", "4koma", "5 panel comic", "6 panel comic", "8 panel comic",
    "numbered panels", "one panel comic", "one page comic", "comic panel",
    "comic panel redraw", "storyboard", "montage", "collage", "split screen",
    "split image", "diptych", "triptych", "before and after", "comparison",
    "compilation", "column lineup", "multiple drawing challenge",
    "draw this in your style challenge", "one-hour drawing challenge",
    "art study", "art jam", "art shift", "speedpaint", "time lapse", "making-of",
    "sketch page", "sketch inset", "chibi inset", "photo inset",
    "reference inset", "projected inset", "inset", "inset border",
    "borderless panels", "cross-section", "cut-here line", "doodle inset",
    "game screenshot inset", "official art inset",
    "adobe photoshop", "adobe illustrator (medium)", "clip studio paint",
    "clip studio paint (medium)", "ibispaint (medium)", "medibang paint (medium)",
    "painttool sai", "painttool sai (medium)", "microsoft paint (medium)",
    "krita (medium)", "aseprite (medium)", "procreate (medium)", "zbrush (medium)",
    "source filmmaker (medium)", "autodesk 3ds max (medium)", "koikatsu (medium)",
    "waifu2x", "live2d", "mikumikudance", "minecraft (style)", "game model",
    "game cg", "game screenshot", "video game cover redraw", "game cover",
    "cover page", "cover image", "album cover redraw", "book cover redraw",
    "novel illustration", "doujin cover", "manga cover", "comic cover",
    "comic book cover", "magazine scan", "laserdisc cover", "end roll",
    "title screen", "key frame", "key visual", "promotional art",
    "production art", "poster parody", "logo parody", "fake cover",
    "fake screenshot", "fake text", "fake video", "fake photograph",
    "fake phone screenshot", "fake transparency", "card parody", "style parody",
    "parody", "interlude", "omake", "gift art",
}

EXPR_DROP = {
    "leopard ears", "scar on head", "x scar", "torn ear", "long earlobes",
    "ear mouth", "chest mouth", "cheek gills", "mismatched animal ear colors",
    "eye black", "eye gouge", "drawn ears", "visible ears", "forehead",
    "l hand", "pink lipstick", "purple lipstick", "red lips", "green mouth",
    "small mouth", "gaping mouth", "squiggle mouth", "packed mouth",
    "milk mustache", "lipstick mark", "scar on cheek", "scar on forehead",
    "glitter makeup", "mascara smear",
    "looking at pussy", "cum from nose", "tears of pleasure", "ahegao",
    "feces from mouth", "too many in mouth", "begging to stop",
    "cum covered", "bodily fluids", "blood drip", "blood on face",
    "expressions", "expression print", "screen face", "flustered face emoji",
    "smile emoji", "smiley face", "spoken smile", "spoken blush",
    "spoken zzz", "spoken ellipsis", "spoken interrobang",
    "spoken flying sweatdrops", "shout lines", "hidoi", "usotsuki",
    "ei ei mun!", "can't be this cute", "my eyes are up here",
}

SCENE_DROP = {
    "twitch.tv", "windows 95", "miiverse", "shounen jump", "silent hill 1",
    "nissan", "copyright logo", "walk-in", "weather report", "timeline",
    "seasons", "april fools", "log pose", "suiyou dou de shou", "zero one driver",
    "star guardian pet", "lego brick", "roomba", "cradily", "sawsbuck",
    "swellow", "susuwatari", "ehomaki", "hina ningyou",
    "noose", "urine", "urine meter", "gore", "blood splatter", "inverted cross",
    "symbiote", "stationary restraints",
    "midd night", "censored food", "too many chicks",
}

CAMERA_ADD = [
    ("rule of thirds", "三分法构图"),
    ("leading lines", "引导线构图"),
    ("negative space", "负空间留白"),
    ("frame-in-frame", "框景构图"),
    ("eye level", "平视机位"),
    ("midground", "中景层次"),
    ("foreground focus", "前景对焦"),
    ("background focus", "背景对焦"),
    ("bird's-eye view", "鸟瞰视角"),
    ("over-the-shoulder", "过肩镜头"),
    ("deep focus", "深焦"),
    ("symmetrical composition", "对称构图"),
    ("diagonal composition", "对角线构图"),
    ("shallow depth of field", "浅景深"),
    ("extreme close-up", "大特写"),
    ("wide-angle shot", "广角镜头"),
    ("telephoto shot", "长焦镜头"),
    ("long exposure", "长曝光"),
]

CAT_RE = re.compile(r"^([a-z_]+):\s*$")
TAG_RE = re.compile(r"^\s*-\s+tag:\s*(.+?)\s*$")

lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)

DROP = {
    "camera_shot": CAMERA_DROP,
    "detail_mood": DETAIL_DROP,
    "expression_reaction": EXPR_DROP,
    "scene_environment": SCENE_DROP,
}

cur_cat = ""
removed: dict[str, int] = {}
removed_samples: dict[str, list[str]] = {}

# 第一遍：删除
out: list[str] = []
i = 0
while i < len(lines):
    ln = lines[i]
    m = CAT_RE.match(ln.strip())
    if m:
        cur_cat = m.group(1)
        out.append(ln)
        i += 1
        continue
    tm = TAG_RE.match(ln)
    if tm and cur_cat in DROP:
        tag = tm.group(1)
        if tag in DROP[cur_cat]:
            removed[cur_cat] = removed.get(cur_cat, 0) + 1
            removed_samples.setdefault(cur_cat, []).append(tag)
            j = i + 1
            while j < len(lines) and lines[j].startswith(("  ", "\t")):
                j += 1
            i = j
            continue
    out.append(ln)
    i += 1

# 第二遍：camera_shot 末尾补结构性构图词（去重）
existing = set()
cur = ""
for ln in out:
    m = CAT_RE.match(ln.strip())
    if m:
        cur = m.group(1)
        continue
    tm = TAG_RE.match(ln)
    if tm and cur == "camera_shot":
        existing.add(tm.group(1))

final: list[str] = []
cur = ""
inserted = 0
for idx, ln in enumerate(out):
    m = CAT_RE.match(ln.strip())
    if m:
        cur = m.group(1)
        final.append(ln)
        continue
    final.append(ln)
    if cur == "camera_shot":
        nxt = out[idx + 1].strip() if idx + 1 < len(out) else ""
        if nxt == "" or CAT_RE.match(nxt):
            for tag, cn in CAMERA_ADD:
                if tag in existing:
                    continue
                final.append(f"- tag: {tag}\n")
                final.append(f"  rating: general\n")
                final.append(f"  chinese: {cn}\n")
                inserted += 1

SRC.write_text("".join(final), encoding="utf-8")

print("== 删除统计 ==")
total = 0
for cat, n in removed.items():
    total += n
    print(f"{cat}: 删除 {n} 条")
    for s in removed_samples[cat][:12]:
        print(f"    - {s}")
print(f"共删除 {total} 条; camera_shot 补齐 {inserted} 条")

import yaml
data = yaml.safe_load(SRC.read_text(encoding="utf-8"))
print("YAML 校验 OK:")
for cat in ["count_gender", "appearance", "clothing_state", "pose_action_sex",
            "expression_reaction", "camera_shot", "scene_environment", "detail_mood"]:
    print(f"  {cat}: {len(data.get(cat, []))}")
