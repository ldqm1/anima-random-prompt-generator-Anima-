#!/usr/bin/env python3
"""知识库 v1 反趋同清洗：
1. tags_镜头.txt: 删除成人/透视/元数据/计数词, 补齐结构性构图词(构图质量关键)
2. tags_表情动作.txt: 删除颜文字类等无画面语义词
3. tags_场景.txt: 删除体内视角等无意义词
4. tags_画面.txt: 删除软件介质/媒体垃圾词
格式: [DOMAIN:标签] [CAT:分类] tag | 中文
"""
from __future__ import annotations

import re
from pathlib import Path

KB = Path(r"E:\code\Anima\anima-rag-knowledge-release\知识库\v1")

# ---------------- tags_镜头.txt 删除表（精确 tag） ----------------
CAMERA_DROP = {
    # 成人/透视/露骨（r15 下被 system_prompt 丢弃, 纯浪费名额）
    "penetrating_pov", "fellatio_pov", "cuckold_pov", "taker_pov", "pov_crotch",
    "pov_peephole", "pov_breasts", "pov_legs", "pov_hands", "pov_across_bed",
    "pov_dating", "pov_doorway", "pov_across_table", "lap_pov",
    "pov_cheek_grabbing_(meme)", "pov_cheek_warming_(meme)",
    "penis_out_of_frame", "penis_focus", "presenting_anus", "anus_focus",
    "pussy_focus", "pantyshot", "panty_shot", "under_skirt", "upskirt",
    "extended_upskirt", "upshirt", "extended_downblouse", "implied_pantyshot",
    "pantyshot_through_reflection", "censored", "censored_by_text",
    "blur_censor", "fake_censor", "emoji_censor", "tail_censor", "wing_censor",
    "censored_violence", "x-ray", "x-ray_vision", "viewer_holding_leash",
    "viewer_on_leash", "futanari_pov", "clothed_male_nude_female",
    "offscreen_male", "male_pov", "looking_at_ass", "butt_focus", "butt_shot",
    "ass_focus", "ass_visible_through_thighs", "crotch_focus", "framed_breasts",
    "breast_focus", "pectoral_focus", "pectorals_on_glass", "navel_focus",
    "hip_focus", "armpit_focus", "foot_focus", "feet_only", "in_the_face",
    "view_between_legs", "looking_inside", "full_frontal", "shaft_look",
    "piper_perri_surrounded", "misleading_thumbnail", "kotori_photobomb",
    "inside",
    # 计数/元数据/无意义
    "2others", "3others", "5others", "angle", "above", "view", "lens",
    "zoom_layer", "screen_zoom", "camera_view", "through_medium",
    "through_screen", "multiple_views", "multiple_angles", "multiple_pov",
    "top-down_bottom-up", "group_picture", "group_profile", "lineup",
    "id_photo", "mugshot", "photo_shoot", "cosplay_photo", "front_and_back",
    "head_to_head", "size_comparison", "height_comparison", "floating_head",
    "chibi_on_shoulder", "surrounded", "circle_formation",
    "offscreen_character", "off_screen", "photobomb", "pillarboxed",
    "reflection_focus", "split_depth", "red-eye_effect", "being_watched",
    "group", "trio", "duo", "solo", "solo_focus", "duo_focus", "other_focus",
    "human_focus", "female_focus", "monster_focus", "creature_focus",
    "pokemon_focus", "anthro_focus", "back_peek", "behind_cover",
    "behind_another", "facing_another", "face-to-face", "side-by-side",
    "side_by_side", "eyes_out_of_frame", "eyes_visible_through_hair",
    "eyes_visible_through_eyewear", "mouth_visible_through_hair",
    "one_eye_obstructed", "obscured_face", "obscured", "face_cutout",
    "fisheye_placebo",
}

# ---------------- tags_镜头.txt 补齐（结构性构图词） ----------------
CAMERA_ADD = [
    ("rule_of_thirds", "三分法构图", "镜头/构图法则"),
    ("leading_lines", "引导线构图", "镜头/构图法则"),
    ("negative_space", "负空间留白", "镜头/构图法则"),
    ("frame-in-frame", "框景构图", "镜头/构图法则"),
    ("eye_level", "平视机位", "镜头/镜头角度"),
    ("midground", "中景层次", "镜头/构图法则"),
    ("foreground_focus", "前景对焦", "镜头/构图法则"),
    ("background_focus", "背景对焦", "镜头/构图法则"),
    ("bird's-eye_view", "鸟瞰视角", "镜头/镜头角度"),
    ("deep_focus", "深焦", "镜头/效果"),
    ("symmetrical_composition", "对称构图", "镜头/构图法则"),
    ("diagonal_composition", "对角线构图", "镜头/构图法则"),
    ("shallow_depth_of_field", "浅景深", "镜头/效果"),
    ("extreme_close-up", "大特写", "镜头/特写镜头"),
    ("wide-angle_shot", "广角镜头", "镜头/镜头角度"),
    ("telephoto_shot", "长焦镜头", "镜头/镜头角度"),
    ("long_exposure", "长曝光", "镜头/效果"),
]

# ---------------- 其它库删除（CAT 前缀或精确 tag） ----------------
# tags_表情动作.txt: 删除颜文字类（无画面语义）
EXPR_CAT_PREFIX_DROP = ["表情动作/颜文字"]
# tags_场景.txt: 删除无意义/体内视角
SCENE_DROP = {"internal", "public"}
# tags_画面.txt: 删除软件介质词（精确 tag 后缀匹配 _medium 的软件名保留？只删明确软件）
DETAIL_DROP = {
    "photoshop_(medium)", "clip_studio_paint", "adobe_illustrator_(medium)",
    "ibispaint_(medium)", "medibang_paint_(medium)", "painttool_sai",
    "painttool_sai_(medium)", "microsoft_paint_(medium)", "krita_(medium)",
    "aseprite_(medium)", "procreate_(medium)", "zbrush_(medium)",
    "source_filmmaker_(medium)", "autodesk_3ds_max_(medium)",
    "koikatsu_(medium)", "waifu2x", "mikumikudance", "blender_(medium)",
    "vrchat_(medium)", "png_file", "psd_available", "watermark",
    "watermark_grid", "miyoushe_watermark", "character_watermark",
    "artist_watermark", "sample_watermark", "ai-generated", "ai-assisted",
    "jpeg_artifacts", "huge_filesize", "twitter_screenshot", "deviantart",
    "nijie", "pixiv_sample", "pixiv_red", "pixiv_shadow", "commission",
    "traced", "cleaned", "upscaled", "downscaled", "resized",
}

TAG_RE = re.compile(r"^(\[DOMAIN:标签\] \[CAT:[^\]]+\])\s+([^\s|]+)(?:\s*\|.*)?$")


def clean_file(path: Path, drop_tags: set[str] | None = None,
               drop_cat_prefixes: set[str] | None = None) -> tuple[int, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    removed = 0
    samples: list[str] = []
    for ln in lines:
        m = TAG_RE.match(ln.strip())
        if m:
            cat = m.group(1)
            tag = m.group(2)
            if drop_tags and tag in drop_tags:
                removed += 1
                if len(samples) < 25:
                    samples.append(tag)
                continue
            if drop_cat_prefixes and any(p in cat for p in drop_cat_prefixes):
                removed += 1
                if len(samples) < 25:
                    samples.append(tag)
                continue
        out.append(ln)
    path.write_text("".join(out), encoding="utf-8")
    return removed, samples


def add_to_camera(path: Path, additions: list[tuple[str, str, str]]) -> int:
    """在 tags_镜头.txt 末尾追加结构性构图词（去重）。"""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    existing = set()
    for ln in lines:
        m = TAG_RE.match(ln.strip())
        if m:
            existing.add(m.group(2))
    block = []
    added = 0
    for tag, cn, cat in additions:
        if tag in existing:
            continue
        block.append(f"[DOMAIN:标签] [CAT:{cat}] {tag} | {cn}\n")
        added += 1
    if block:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.extend(block)
        path.write_text("".join(lines), encoding="utf-8")
    return added


cam_file = KB / "tags_镜头.txt"
expr_file = KB / "tags_表情动作.txt"
scene_file = KB / "tags_场景.txt"
detail_file = KB / "tags_画面.txt"

r1, s1 = clean_file(cam_file, drop_tags=CAMERA_DROP)
a1 = add_to_camera(cam_file, CAMERA_ADD)
r2, s2 = clean_file(expr_file, drop_cat_prefixes=EXPR_CAT_PREFIX_DROP)
r3, s3 = clean_file(scene_file, drop_tags=SCENE_DROP)
r4, s4 = clean_file(detail_file, drop_tags=DETAIL_DROP)

print(f"tags_镜头.txt: 删除 {r1} 条, 补齐 {a1} 条")
print("  删除样例:", ", ".join(s1[:15]))
print(f"tags_表情动作.txt: 删除 {r2} 条 (颜文字类)")
print(f"tags_场景.txt: 删除 {r3} 条 -> {s3}")
print(f"tags_画面.txt: 删除 {r4} 条")
print("  删除样例:", ", ".join(s4[:15]))
