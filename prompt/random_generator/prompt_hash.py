"""提示词指纹（hash）共享模块。

单一实现点：生成器（cli.py）与未来反查脚本（图片元数据 -> 日志）必须共用本模块，
保证两侧算出的指纹一致。未来若调整归一化规则（质量词表/分隔处理），只改本文件
并递增 ``HASH_VERSION``；旧日志通过 ``prompt.hash_version`` 知道应使用哪版算法，
且 ``prompt.version_1`` 原文始终可重算。
"""
from __future__ import annotations

import hashlib
import re

#: 当前归一化算法版本。修改任何归一化规则或 NON_SEMANTIC 时递增（如 "tags_sha256_v2"）。
HASH_VERSION = "tags_sha256_v1"

#: 非语义前缀词（质量/元数据类）。用户可能手动加到出图 prompt 而不影响画面语义，
#: 计算 tag 集合指纹时忽略它们。
NON_SEMANTIC: frozenset[str] = frozenset(
    {
        "masterpiece", "best quality", "good quality", "ultra detailed", "ultra-detailed",
        "score 7", "score 8", "score 9", "newest", "highres", "absurdres", "wallpaper",
        "official art", "anime screenshot", "high quality", "lowres", "safe", "sensitive",
        "nsfw", "explicit",
    }
)

_WEIGHT_RE = re.compile(r":\d+(\.\d+)?")


def normalize_tag(tag: str) -> str:
    """归一化单个 tag：小写、剥离 :权重、去下划线/括号、压缩空白。"""
    t = _WEIGHT_RE.sub("", tag.lower())
    t = t.replace("_", " ").replace("(", " ").replace(")", " ")
    return " ".join(t.split())


def split_tags(prompt: str) -> list[str]:
    """从 prompt 提取 tag 区（". " 之前的部分）并逗号切分。"""
    tags_part = prompt.split(". ")[0] if ". " in prompt else prompt
    return [t.strip() for t in tags_part.split(",") if t.strip()]


def norm_tags(prompt: str) -> list[str]:
    """归一化后的语义 tag 列表（排序去重），供指纹计算与反查比对。"""
    out = []
    for t in split_tags(prompt):
        n = normalize_tag(t)
        if n and n not in NON_SEMANTIC and n not in out:
            out.append(n)
    return sorted(out)


def tags_sha256(prompt: str) -> str:
    """归一化 tag 集合指纹：加质量前缀/调顺序/改分隔/带权重后仍稳定。"""
    return hashlib.sha256("\n".join(norm_tags(prompt)).encode("utf-8")).hexdigest()


def sha256(prompt: str) -> str:
    """完整 prompt 原文指纹（与 PNG 元数据逐字节一致时可直接匹配）。"""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def prompt_hashes(prompt: str) -> dict[str, str]:
    """同时计算原文指纹与 tag 集合指纹。"""
    return {"sha256": sha256(prompt), "tags_sha256": tags_sha256(prompt)}
