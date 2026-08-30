"""从 YAML 源文件提取键的帮助文本（tooltip 数据源）。

原理：直接解析 YAML 文件的**注释**（# 开头行）——每个配置项的说明注释
通常写在它上方。这样帮助文本与实际文件同步维护，无需单独维护说明表。

提取规则（面向本项目的 yaml 书写习惯）：
- 扫描每个顶层/嵌套键；收集该键「上方连续注释块」（紧邻该键行的连续 # 行）；
- 也收集键行尾部的行内注释（``key: value  # 说明``）；
- 注释块以「# 开头但非 # 分隔符（# ---- / ====）」为准；
- 输出 dict：``{"key.path": {"help": "..."}, ...}``，key.path 用点分路径。

对 GUI 而言，帮助文本展示「该配置是什么 + 修改会产生什么效果」（即 yaml 里
本来写好的注释），用户悬停控件即可看到。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") and not stripped.startswith("#-") and not stripped.startswith("#=")


def _comment_text(line: str) -> str:
    return line.lstrip()[1:].strip()


def extract_help(
    path: str | Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """提取 YAML 文件的帮助文本。

    Returns:
        ``(inline_help, block_help)``：
        - ``inline_help``：行内注释 ``key: value  # 说明`` → 说明；
        - ``block_help``：键上方的连续注释块 → 合并后的说明文本。
        两者都以点分路径为键（如 ``subcategory_quotas.pose_action_sex``）。
    """
    path = Path(path)
    if not path.exists():
        return {}, {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, {}

    inline_help: dict[str, str] = {}
    block_help: dict[str, str] = {}
    block_lines: list[str] = []
    block_start_line = 0  # 当前注释块起始行号（用于判定是否紧邻键）

    def _flush_block(nearest_key_line: int | None = None) -> None:
        nonlocal block_lines
        if not block_lines:
            return
        text = " ".join(x for x in block_lines if x).strip()
        block_lines = []
        # 交给调用方判断归属（这里仅清空）

    def _is_key_line(line: str) -> bool:
        # 形如 "key:" 或 "key: value" 的行（非列表项、非注释）
        m = re.match(r"^\s*([A-Za-z_][\w]*)\s*:(?:\s|$)", line)
        return bool(m)

    # 记录每个键的行号 → 键名，用于把注释块归属到最近的键
    key_lines: list[tuple[int, str, str]] = []  # (行号, 点分路径, 键名)
    # 用缩进推断嵌套路径
    stack: list[tuple[int, str]] = []  # (缩进, 键名)

    for lineno, raw in enumerate(lines, start=1):
        line = raw
        if _is_comment(line):
            block_lines.append(_comment_text(line))
            continue

        stripped = line.rstrip()
        if not stripped.strip():
            # 空行：注释块到此为止（不归属任何键，除非后面紧跟键）
            block_lines = []
            continue

        if _is_key_line(line):
            indent = len(line) - len(line.lstrip())
            key_match = re.match(r"^\s*([A-Za-z_][\w]*)\s*:", line)
            if not key_match:
                block_lines = []
                continue
            key = key_match.group(1)

            # 维护缩进栈
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, key))
            dotted = ".".join(k for _, k in stack)

            # 行内注释
            inline_m = re.search(r"#\s*(.+?)\s*$", line)
            if inline_m:
                inline_help[dotted] = inline_m.group(1).strip()

            # 紧邻上方的注释块归属该键
            if block_lines:
                text = " ".join(block_lines).strip()
                if text:
                    block_help[dotted] = text
            block_lines = []
            key_lines.append((lineno, dotted, key))
        else:
            # 普通值行（如列表项 "- id: xxx"、数组元素）不归属注释块
            block_lines = []
            continue

    return inline_help, block_help


def build_help_map(path: str | Path) -> dict[str, dict[str, str]]:
    """构建 (点分路径 → {"help": 文本, "inline": 行内文本}) 帮助映射。"""
    inline, block = extract_help(path)
    out: dict[str, dict[str, str]] = {}
    all_keys = set(inline) | set(block)
    for key in all_keys:
        entry: dict[str, str] = {}
        if block.get(key):
            entry["help"] = block[key]
        if inline.get(key) and key not in block:
            entry["inline"] = inline[key]
        if not entry:
            continue
        out[key] = entry
    return out


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "prompt/random_generator/generation_config.yaml"
    m = build_help_map(p)
    for k, v in list(m.items())[:15]:
        print(f"{k}: {v.get('help', '')[:60]} | inline={v.get('inline', '')[:40]}")
    print(f"... 共 {len(m)} 个键有帮助文本")
