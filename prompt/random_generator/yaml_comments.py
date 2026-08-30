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


# ---------------------------------------------------------------------------
# 兜底帮助：按路径/键名语义生成通用说明（当 yaml 无注释时）
# ---------------------------------------------------------------------------
def semantic_help(dotted: str, value: Any = None) -> str:
    """为无注释字段生成语义化帮助文本。

    规则按"路径特征"匹配（自底向上检查），返回最具体的说明；找不到返回 ""。
    """
    parts = dotted.split(".")
    key = parts[-1]
    joined = ".".join(parts)

    # ---- 子类配额 min/max（最常见的一类）----
    if "subcategory_quotas" in parts:
        if key == "min":
            return "该子类每批【至少】抽到的 tag 数量（保证冷门内容出现）。设为 0 表示不强制出现。"
        if key == "max":
            return "该子类每批【最多】抽到的 tag 数量（0 = 完全不抽，防高频趋同）。留空/不设 = 不限。"
        return ""

    # ---- default_word_quota（词配额）----
    if "default_word_quota" in parts:
        return (
            "反趋同词配额：该词在每条最终提示词中至多出现 1 次（此处 1 = 限 1 次，"
            "0 = 完全禁用该词）。用于压制 soft lighting / cherry blossom 等高频套路词。"
        )

    # ---- r18 主题控制 ----
    if "r18_topic_control" in parts:
        if key == "enabled":
            return "总开关：false 时 r18 主题控制完全关闭（保持完全随机补充）。"
        if key == "mode":
            return "主题出现模式：fixed=固定出现；probabilistic=按概率出现；weighted=按权重调节抽样（不强制出现）。"
        if key == "count":
            return "该主题激活时抽到的目标 tag 数量（fixed 固定抽 count 个；probabilistic/weighted 被选中后抽 count 个）。"
        if key == "probability":
            return "probabilistic 模式的出现概率（0-1）。越大越常出现；0 = 永不出现。"
        if key == "weight":
            return "加权模式下的抽样权重（默认 1）。越大越容易被抽中。"
        if key == "linked_topics":
            return "联动主题列表：本主题被激活时，以 link_probability 概率同时激活列表中的主题。"
        if key == "link_probability":
            return "联动触发概率（默认 0.8）：激活本主题时带出联动主题的概率。"
        if key == "disabled_topics":
            return "单人场景下强制不激活的主题列表（需要两人配合的主题，如 oral/penetration/positions）。"
        if key == "solo":
            return "单人场景（1girl 等）主题限制：非多人画面强制禁用某些需双人配合的主题。"
        if joined.endswith(".topics"):
            return "r18 主题出现配置：每个主题独立控制出现模式/概率/权重/联动。"
        return ""

    # ---- 抽样数量 ----
    if "sample_counts" in parts or "r18_sample_counts" in parts:
        if key == "creative_anchor":
            return "每条样本抽到的创意锚点数量（高概念设定，打破画面趋同）。"
        return "每个内部类别的抽样 tag 数量。调大 = 该类内容更丰富、LLM 输入更多；调小 = 该类更精简。r18_sample_counts 仅 r18/r18g 模式生效。"

    # ---- focus_weights ----
    if "focus_weights" in parts or "r18_focus_weights" in parts:
        return "生成侧重点权重（百分比）：提示 LLM 在最终 prompt 中各类描述的占比。character=角色相关，background=背景相关，r18=r18 内容（仅 r18 模式），other=其他/缓冲。"

    # ---- 通用键名 ----
    if key == "enabled":
        return "总开关：false 时关闭该项功能。"
    if key == "probability":
        return "概率（0-1）：该事件每条样本按此概率触发。"
    if key == "weight":
        return "权重：越大越容易被抽中（相对其他项）。"
    if key == "count":
        return "数量：该项在每条样本中的目标数量。"
    if key == "file":
        return "文件路径。留空（null）= 使用默认路径。"
    if key == "skip_probability":
        return "整组跳过的概率（0-1）：命中则本组抽 0 项。"
    if key == "text":
        return "额外要求的文本内容，原样注入到 LLM 用户提示词。"
    if key == "excludes":
        return "互斥声明：与列表中的其他条目文本互斥，抽中任一侧都会排除另一侧。"
    if key == "tags":
        return "配套 tag 组（3-5 个，相互关联，一起注入才构成完整设定）。"
    if key == "narrative":
        return "叙事句要点（机位/空间/设定逻辑，供叙事句参考）。"
    if key == "cn":
        return "中文说明（仅显示用途，不进入 prompt）。"
    if key == "id":
        return "锚点唯一标识（不进入 prompt）。"
    if key == "name":
        return "英文核心 tag（必须出现在最终 prompt）。"
    if key == "pool":
        return "白名单角色池：从该池随机抽取角色 tag（替代知识库 v1 二次元角色抽样）。"

    # ---- max/min_tags ----
    if key in ("min_tags", "max_tags"):
        return "最终提示词长度约束（tag 数量）：min_tags 为最少 tag 数，max_tags 为最多 tag 数。LLM 会在此区间内输出。"

    # ---- category_whitelists.pools ----
    if "category_whitelists" in parts and key != "category_whitelists":
        return "通用类别白名单池：启用后该类优先从该池抽样（填入英文 tag，逗号分隔）。留空 = 保持知识库 v1 随机抽样。"

    # ---- deepseek ----
    if "deepseek" in parts:
        if key == "temperature":
            return "采样温度（0-2）：越高越随机/有创意，越低越稳定/保守。默认 0.7。"
        if key == "max_tokens":
            return "单次生成的最大 token 数（含输出）。提示词较长时可调大。"
        if key == "timeout":
            return "单次 API 调用超时秒数；第三方代理较慢时可适当调大。"
        if key == "max_parse_retries":
            return "解析失败（空内容/JSON 异常）时的最大重试次数。"
        if key == "reasoning_effort":
            return "模型思考模式：none=关闭推理（更快更省）；low/medium/high=开启推理（更慢但可能更精细）。"

    # ---- multi_character ----
    if "multi_character" in parts:
        if key == "tag_count_bonus":
            return "多角色触发时 min_tags 与 max_tags 各增加的数量（容纳多个角色的 tag）。"
        if key == "focus_character_bonus":
            return "多角色触发时 character 占比额外增加的百分比（从 background/other 按比例扣减）。"

    # ---- character_pool ----
    if "character_pool" in parts:
        if key == "prefer_same_ip_for_multiple":
            return "多角色场景下优先从同一作品（IP）抽样角色。"
        if key == "use_core_appearance":
            return "是否向 LLM 注入角色核心外貌词。"
        if key == "use_core_clothing_probability":
            return "使用核心服饰词作为基础服饰的概率（0-1）。"

    # ---- extra_requirements_pool ----
    if "extra_requirements_pool" in parts:
        if key == "mutex_groups":
            return "互斥组列表：每组按 weight 加权抽 1 项；skip_probability 表示整组跳过概率。"
        if key == "optional_items":
            return "可选特效项：每项按自身 probability 独立决定是否加入。"

    return ""


if __name__ == "__main__":
    import sys

    p = sys.argv[1] if len(sys.argv) > 1 else "prompt/random_generator/generation_config.yaml"
    m = build_help_map(p)
    for k, v in list(m.items())[:15]:
        print(f"{k}: {v.get('help', '')[:60]} | inline={v.get('inline', '')[:40]}")
    print(f"... 共 {len(m)} 个键有帮助文本")
