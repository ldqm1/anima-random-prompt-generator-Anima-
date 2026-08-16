"""DeepSeek API 客户端与响应解析。"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, TemplateNotFound
import yaml

from . import config

#: r18 注入文本中与 §10.2 禁用清单冲突的内容匹配模式（忽略大小写）。
#: 命中任意模式的行会在注入前被整行移除，避免 LLM 收到互相矛盾的指令
#: 而降低对整段注入文本的遵循度。覆盖两类冲突：
#: 1) §10.2 明确禁止的类别（未成年/乱伦/强奸/非自愿/性暴力等）；
#: 2) 要求放弃原则/拆除自审机制的指令。
_R18_INSTRUCTION_FILTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpedophil\w*", re.IGNORECASE),
    re.compile(r"\bloli\b", re.IGNORECASE),
    re.compile(r"\bshota\b", re.IGNORECASE),
    re.compile(r"\bunderage\b", re.IGNORECASE),
    re.compile(r"\bincest\w*", re.IGNORECASE),
    re.compile(r"\bcoerc\w*", re.IGNORECASE),
    re.compile(r"\bnon[\s-]?consensual\b", re.IGNORECASE),
    re.compile(r"\bsexual\s+abuse\b", re.IGNORECASE),
    re.compile(r"\bsexual\s+violence\b", re.IGNORECASE),
    re.compile(r"\brape\w*\b", re.IGNORECASE),
    re.compile(r"\babandon\s+all\b", re.IGNORECASE),
    re.compile(r"\bself[\s-]?censorship\b", re.IGNORECASE),
    re.compile(r"\bfiltering\s+modules\b", re.IGNORECASE),
    re.compile(r"\bcontent\s+violation\b", re.IGNORECASE),
    re.compile(r"\bunconditionally\b", re.IGNORECASE),
)


def filter_r18_instructions(text: str) -> str:
    """移除 r18 注入文本中与 §10.2 禁用清单冲突的行。

    按行匹配，命中任一冲突模式即整行丢弃；无冲突内容原样保留。
    """
    if not text:
        return text
    kept = [
        line
        for line in text.splitlines()
        if not any(pattern.search(line) for pattern in _R18_INSTRUCTION_FILTER_PATTERNS)
    ]
    return "\n".join(kept)


#: r18 占位符格式：``[[r18_appearance_1]]``、``[[r18_pose_2]]`` …
#: 三段式：``[[r18_<槽位类别>_<编号>]]``，类别编码帮助模型放入正确槽位。
#: 容错匹配方括号内的空格/下划线/连字符变体。
#: 类别段使用非贪婪匹配，确保末尾 ``_<编号>`` 整体作为编号（类别名均不以
#: 数字结尾）；否则 ``[[r18_pose_action_sex_10]]`` 会被贪婪匹配成类别
#: ``pose_action_sex_1`` + 编号 ``0``，导致超过 9 个占位符的类别还原失败。
R18_PLACEHOLDER_RE = re.compile(
    r"\[\[\s*r18[ _-]?([a-z0-9]+(?:_[a-z0-9]+)*?)[ _-]?(\d+)\s*\]\]"
)


def assign_r18_placeholders(
    text: str, r18_tags: list[tuple[str, str]]
) -> tuple[str, dict[str, str]]:
    """将文本中的 r18 tag 替换为带类别的占位符，返回 (新文本, 占位符->真实tag 映射)。

    - ``r18_tags`` 为 ``(类别, tag)`` 列表；占位符形如 ``[[r18_<类别>_<n>]]``，
      类别按槽位命名（appearance/clothing/pose/expression 等），帮助模型放对位置。
    - 编号按类别独立递增；同一真实 tag 在文本中多处出现时共用同一占位符。
    - 文本中不存在的 tag 跳过（如已被冲突消解移除）。
    - 先替换为唯一临时标记再转占位符，避免单字符 tag 污染已生成的占位符。
    - 按 tag 长度降序替换，避免短 tag 误伤长 tag 的子串。
    """
    mapping: dict[str, str] = {}
    new_text = text
    pending: list[tuple[str, str]] = []
    for category, tag in sorted(r18_tags, key=lambda item: len(item[1]), reverse=True):
        if tag not in new_text:
            continue
        safe_cat = re.sub(r"[^a-z0-9_]+", "_", category.lower()).strip("_") or "tag"
        num = sum(1 for k in mapping if k.startswith(f"[[r18_{safe_cat}_")) + 1
        placeholder = f"[[r18_{safe_cat}_{num}]]"
        marker = f"\x00RPH{len(mapping)}\x00"
        mapping[placeholder] = tag
        new_text = new_text.replace(tag, marker)
        pending.append((marker, placeholder))
    for marker, placeholder in pending:
        new_text = new_text.replace(marker, placeholder)
    return new_text, mapping


def restore_r18_placeholders(text: str, mapping: dict[str, str]) -> str:
    """将输出文本中的 r18 占位符替换回真实 tag；未知占位符删除。

    LLM 可能编造映射之外的占位符编号（例如把某类别占位符扩充到
    ``[[r18_<类别>_10]]``），这类占位符无真实 tag 可还原，直接移除，
    避免泄漏到最终提示词中。
    """
    if not text or not mapping:
        return text

    def _sub(match: re.Match[str]) -> str:
        placeholder = f"[[r18_{match.group(1)}_{match.group(2)}]]"
        return mapping.get(placeholder, "")

    return R18_PLACEHOLDER_RE.sub(_sub, text)


#: 每个允许出现的 r18 tag 的含蓄短句描述（tag -> 一句委婉/模糊描述）。
#: 模型看不到占位符的真实内容，仅凭类别与短句理解其大致语义。
_r18_euphemisms_cache: dict[str, str] | None = None


def load_r18_euphemisms() -> dict[str, str]:
    """加载 r18 tag 含蓄短句表（r18_euphemisms.yaml）。"""
    global _r18_euphemisms_cache
    if _r18_euphemisms_cache is not None:
        return _r18_euphemisms_cache
    data: dict[str, str] = {}
    if config.R18_EUPHEMISMS_FILE.exists():
        with config.R18_EUPHEMISMS_FILE.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        data = {
            tag.strip(): str(desc).strip()
            for tag, desc in loaded.items()
            if isinstance(desc, str) and desc.strip()
        }
    _r18_euphemisms_cache = data
    return data


def build_placeholder_meanings(
    placeholder_map: dict[str, str],
) -> dict[str, str]:
    """为占位符生成「含蓄短句」描述：占位符 -> 其真实 tag 的委婉说明。

    - 命中了 euphemisms 表（r18_euphemisms.yaml）的 tag 用其短句；
    - 未命中的 tag 用类别级默认描述（该类别的 adult-themed 概括）；
    - 无任何描述时不生成该条目。
    """
    if not placeholder_map:
        return {}
    table = load_r18_euphemisms()
    meanings: dict[str, str] = {}
    for placeholder, tag in placeholder_map.items():
        desc = table.get(tag) or table.get(tag.replace("_", " "))
        if desc:
            meanings[placeholder] = desc
        else:
            category = placeholder[len("[[r18_") : -len("_N]")].rsplit("_", 1)[0]
            meanings[placeholder] = (
                f"an adult-themed tag of the {category or 'pose'} category "
                "(exposure state, intimate or suggestive pose, or body reaction)"
            )
    return meanings

#: 默认槽位顺序，与 ``system_prompt.md`` 及 ``user_prompt.jinja`` 保持一致。
SLOT_ORDER = (
    "[count/gender] -> [character/series] -> [appearance] -> [clothing/state] -> "
    "[pose/action/sex] -> [expression/reaction] -> [camera/shot] -> "
    "[scene/environment] -> [detail/mood] -> "
    "[natural language: 关系/动作/剧情补充]"
)

#: 模块目录，用于定位默认提示词文件。
MODULE_DIR = Path(__file__).resolve().parent


def load_system_prompt(path: str | Path | None = None) -> str:
    """加载系统提示词。

    Args:
        path: 系统提示词文件路径。默认加载模块目录下的 ``system_prompt.md``。

    Returns:
        系统提示词文本。

    Raises:
        FileNotFoundError: 找不到指定的系统提示词文件。
    """
    if path is None:
        path = MODULE_DIR / "system_prompt.md"
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"System prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def render_system_prompt(
    path: str | Path | None = None,
    **kwargs: Any,
) -> str:
    """加载系统提示词并按需渲染 ``{{变量}}`` 占位符。

    Args:
        path: 系统提示词文件路径。默认加载模块目录下的 ``system_prompt.md``。
        **kwargs: 模板变量，例如 ``max_rating``、``safety``。

    Returns:
        渲染后的系统提示词文本。
    """
    text = load_system_prompt(path)
    if kwargs:
        # r18 注入文本先过滤掉与 §10.2 禁用清单冲突的内容，再交给模板渲染。
        if kwargs.get("r18_instructions"):
            kwargs = dict(kwargs)
            kwargs["r18_instructions"] = filter_r18_instructions(
                kwargs["r18_instructions"]
            )
        text = Template(text).render(**kwargs)
    return text


def render_user_prompt(
    sampled_tags_text: str,
    safety: str,
    min_tags: int,
    max_tags: int,
    theme_hint: str = "",
    focus_text: str = "",
    template_path: str | Path | None = None,
    subject_control: str = "",
    max_rating: str = "r15",
    forced_tags: list[str] | str = "",
    forbidden_tags: list[str] | str = "",
    character_tag: str = "",
    extra_requirements: str = "",
    character_pool_info: dict | None = None,
    placeholder_meanings: dict[str, str] | None = None,
    creative_anchor_info: list[dict] | None = None,
) -> str:
    """渲染用户提示词模板。

    Args:
        sampled_tags_text: 已抽样的 tag 文本，可直接放入模板。
        safety: 安全标签，如 ``safe``、``sensitive``、``nsfw``、``explicit``。
        min_tags: 允许的最少 tag 数量。
        max_tags: 允许的最多 tag 数量。
        theme_hint: 可选的场景主题提示。
        focus_text: 可选的生成侧重点说明文本。
        template_path: 用户提示词模板路径。默认使用模块目录下的 ``user_prompt.jinja``。
        subject_control: 人数/关系控制文本。
        max_rating: 当前允许的最大内容分级，默认 ``r15``。
        forced_tags: 强制保留的 tag 列表或逗号分隔字符串。
        forbidden_tags: 强制丢弃的 tag 列表或逗号分隔字符串。
        character_tag: 角色/系列 seed tag。
        extra_requirements: 用户自定义额外要求文本。
        character_pool_info: Excel 角色池信息，包含 ``characters`` 与
            ``clothing_strategy``，用于注入角色原外貌词与服饰策略。
        placeholder_meanings: 占位符 -> 含蓄短句描述，用于解释各 r18 占位符
            的大致语义（仅 r18 模式渲染）。

    Returns:
        渲染后的用户提示词文本。

    Raises:
        FileNotFoundError: 找不到指定的模板文件。
    """
    if template_path is None:
        template_path = MODULE_DIR / "user_prompt.jinja"
    else:
        template_path = Path(template_path)

    template_path = Path(template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"User prompt template not found: {template_path}")

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    try:
        template = env.get_template(template_path.name)
    except TemplateNotFound as exc:
        raise FileNotFoundError(f"User prompt template not found: {template_path}") from exc

    is_multi_character = _is_multi_character(sampled_tags_text)
    return template.render(
        sampled_tags_text=sampled_tags_text,
        safety=safety,
        min_tags=min_tags,
        max_tags=max_tags,
        theme_hint=theme_hint,
        focus_text=focus_text,
        slot_order=SLOT_ORDER,
        character_tag=character_tag,
        subject_control=subject_control,
        max_rating=max_rating,
        forced_tags=forced_tags,
        forbidden_tags=forbidden_tags,
        extra_requirements=extra_requirements,
        character_pool_info=character_pool_info,
        is_multi_character=is_multi_character,
        placeholder_meanings=placeholder_meanings,
        creative_anchor_info=creative_anchor_info,
    )


def _is_multi_character(sampled_tags_text: str) -> bool:
    """根据抽样 tag 文本判断是否包含多人场景标记。"""
    multi_markers = {
        "2girls",
        "3girls",
        "2boys",
        "3boys",
        "multiple girls",
        "multiple boys",
    }
    # 统一 '_'、'-' 与 ',' 为空白，再按空白分词，以兼容换行、逗号等多种分隔。
    normalized = (
        sampled_tags_text.replace("_", " ")
        .replace("-", " ")
        .replace(",", " ")
        .lower()
    )
    words = normalized.split()
    for word in words:
        if word in multi_markers:
            return True
    for i in range(len(words) - 1):
        if f"{words[i]} {words[i + 1]}" in multi_markers:
            return True
    return False


def _env_or_config(value: Any | None, env_name: str, config_value: Any) -> Any:
    """优先使用显式参数，其次环境变量，最后配置默认值。"""
    if value is not None:
        return value
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    return config_value


def _try_openai_chat_completion(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float = 60.0,
    reasoning_effort: str | None = None,
) -> dict:
    """尝试使用 ``openai`` 库调用聊天补全接口。"""
    # 延迟导入，避免未安装 openai 时直接报错。
    import openai  # type: ignore[import-untyped]

    client = openai.OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    response = client.chat.completions.create(**kwargs)
    return response.model_dump()


def _requests_chat_completion(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float = 60.0,
    reasoning_effort: str | None = None,
) -> dict:
    """使用 ``requests`` 库直接调用 DeepSeek 聊天补全接口。"""
    import requests

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    url = f"{api_base.rstrip('/')}/chat/completions"
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def call_deepseek(
    system_prompt: str,
    user_prompt: str,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: float = 60.0,
    reasoning_effort: str | None = None,
) -> dict:
    """调用 DeepSeek API 并返回原始响应字典。

    参数优先级：显式传入 > 环境变量 > ``config.py`` 默认值。

    当 ``openai`` 库可用时优先使用它；否则退化为 ``requests`` 直接请求。
    失败时不再重试，直接抛出错误。

    Args:
        system_prompt: 系统提示词。
        user_prompt: 用户提示词。
        api_key: DeepSeek API Key。
        api_base: DeepSeek API 基础地址。
        model: 使用的模型名称。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数.
        timeout: 单次 API 调用超时秒数。
        reasoning_effort: 模型思考模式（``"none"`` / ``"low"`` / ``"medium"`` /
            ``"high"``）；为 ``None`` 时不发送该参数。``"none"`` 关闭推理，
            输出更快且不占用 ``max_tokens``。

    Returns:
        API 返回的原始响应字典。

    Raises:
        ValueError: 未提供有效的 API Key。
        RuntimeError: 调用失败且重试后仍失败。
    """
    api_key = _env_or_config(api_key, "DEEPSEEK_API_KEY", None)
    api_base = _env_or_config(api_base, "DEEPSEEK_API_BASE", config.DEEPSEEK_API_BASE)
    model = _env_or_config(model, "DEEPSEEK_MODEL", config.DEEPSEEK_MODEL)

    if not api_key:
        raise ValueError(
            "DeepSeek API key is required. Set DEEPSEEK_API_KEY env var or pass api_key."
        )

    try:
        use_openai = True
        import openai  # type: ignore[import-untyped]
    except ImportError:
        use_openai = False

    last_exception: Exception | None = None
    # 重试次数设为 0：仅尝试 1 次，失败直接报错，不重试。
    max_attempts = 1

    for attempt in range(max_attempts):
        try:
            if use_openai:
                return _try_openai_chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    api_base=api_base,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    reasoning_effort=reasoning_effort,
                )
            return _requests_chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                api_base=api_base,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                reasoning_effort=reasoning_effort,
            )
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            should_retry = False
            if use_openai and isinstance(exc, openai.APIStatusError):
                if exc.status_code in (429, 500, 502, 503, 504):
                    should_retry = True
            elif not use_openai:
                import requests

                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    status_code = exc.response.status_code
                    if status_code in (429, 500, 502, 503, 504):
                        should_retry = True

            if not should_retry or attempt >= max_attempts - 1:
                break
            time.sleep(1.0 * (attempt + 1))

    raise RuntimeError(
        f"DeepSeek API call failed after {max_attempts} attempt(s): {last_exception}"
    ) from last_exception


def _strip_markdown_fences(text: str) -> str:
    """移除 JSON 周围的 markdown 代码块标记。"""
    text = text.strip()
    fence_pattern = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
    match = fence_pattern.match(text)
    if match:
        return match.group(1).strip()
    return text


def _extract_json_object(text: str) -> str:
    """从文本中提取第一个 JSON 对象字符串。"""
    # 尝试匹配最外层花括号，处理简单嵌套。
    depth = 0
    start: int | None = None
    for idx, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : idx + 1]
    raise ValueError("No JSON object found in response text")


def _describe_response_state(response: dict) -> str:
    """返回用于排错的响应状态摘要（不含敏感内容）。"""
    if not isinstance(response, dict):
        return f"response type={type(response)}"
    usage = response.get("usage")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return "choices empty/missing"
    first = choices[0] if isinstance(choices[0], dict) else {}
    finish = first.get("finish_reason")
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    has_content = bool(content and isinstance(content, str) and content.strip())
    refusal = message.get("refusal")
    return (
        f"finish_reason={finish}, has_content={has_content}, "
        f"refusal={refusal is not None}, usage={usage is not None}"
    )


def parse_response(response: dict | str) -> dict:
    """解析 DeepSeek 返回的响应。

    Args:
        response: API 原始响应字典，或直接的响应字符串。

    Returns:
        包含 ``version_1``、``version_2``、``reasoning`` 的字典。

    Raises:
        ValueError: 无法从响应中提取有效内容。
        KeyError: 解析后的字典缺少必要字段。
    """
    if isinstance(response, dict):
        content: str | None = None
        choices = response.get("choices")
        finish_reason: str | None = None
        refusal: str | None = None
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                finish_reason = first_choice.get("finish_reason")
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    refusal = message.get("refusal")
                    # DeepSeek v4 may put thinking/reasoning in reasoning_content while content is empty.
                    if not content:
                        content = message.get("reasoning_content")
        if content is None:
            content = response.get("content")
        if not isinstance(content, str):
            raise ValueError(
                f"Could not extract content from response. "
                f"{_describe_response_state(response)}"
            )
        if not content.strip():
            state = _describe_response_state(response)
            detail = f"DeepSeek returned empty content. {state}"
            if finish_reason == "content_filter":
                detail = (
                    f"DeepSeek content filter triggered (finish_reason=content_filter). "
                    f"{state}"
                )
            if refusal:
                detail += f"; refusal={refusal}"
            raise ValueError(detail)
    elif isinstance(response, str):
        content = response
        if not content.strip():
            raise ValueError("DeepSeek returned empty content string.")
    else:
        raise TypeError(f"Response must be dict or str, got {type(response)}")

    content = _strip_markdown_fences(content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as decode_error:
        try:
            parsed = json.loads(_extract_json_object(content))
        except (ValueError, json.JSONDecodeError) as extraction_error:
            raise ValueError(
                f"Failed to parse response as JSON: {decode_error}"
            ) from extraction_error

    if not isinstance(parsed, dict):
        raise ValueError(f"Parsed response is not a dict: {type(parsed)}")

    # 新格式：模型只返回一个 prompt 字段（当前 system_prompt 只要求输出单个
    # 版本）。不再复制一份 version_2——v1/v2 完全相同没有生成价值，v2 已关闭。
    if "prompt" in parsed:
        reasoning = parsed.get("reasoning", [])
        if isinstance(reasoning, str):
            reasoning = [reasoning]
        return {
            "version_1": parsed["prompt"],
            "reasoning": reasoning,
        }

    required_keys = ("version_1", "version_2", "reasoning")
    missing = [key for key in required_keys if key not in parsed]
    if missing:
        raise KeyError(f"Parsed response missing required keys: {missing}")

    return parsed


def generate_single(
    sampled_tags_text: str,
    safety: str,
    min_tags: int = 22,
    max_tags: int = 38,
    theme_hint: str = "",
    focus_text: str = "",
    system_prompt_path: str | Path | None = None,
    user_template_path: str | Path | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: float = 60.0,
    subject_control: str = "",
    max_rating: str = "r15",
    forced_tags: list[str] | str = "",
    forbidden_tags: list[str] | str = "",
    character_tag: str = "",
    extra_requirements: str = "",
    r18_instructions: str = "",
    character_pool_info: dict | None = None,
    placeholder_meanings: dict[str, str] | None = None,
    creative_anchor_info: list[dict] | None = None,
    max_parse_retries: int = 2,
    reasoning_effort: str | None = None,
) -> dict:
    """生成单条随机提示词。

    该函数会依次加载系统提示词、渲染用户提示词、调用 DeepSeek API、解析响应，
    并返回包含 ``version_1``、``version_2``、``reasoning`` 与 ``raw`` 的字典。

    当 API 返回空内容或无法解析的 JSON 时，会自动重试（最多 ``max_parse_retries`` 次）。

    Args:
        sampled_tags_text: 已抽样的 tag 文本。
        safety: 安全标签。
        min_tags: 最少 tag 数量。
        max_tags: 最多 tag 数量。
        theme_hint: 可选主题提示。
        focus_text: 可选的生成侧重点说明文本。
        system_prompt_path: 系统提示词文件路径。
        user_template_path: 用户提示词模板路径。
        api_key: DeepSeek API Key。
        api_base: DeepSeek API 基础地址。
        model: 使用的模型名称。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数.
        timeout: 单次 API 调用超时秒数。
        subject_control: 人数/关系控制文本。
        max_rating: 当前允许的最大内容分级，默认 ``r15``。
        forced_tags: 强制保留的 tag 列表或逗号分隔字符串。
        forbidden_tags: 强制丢弃的 tag 列表或逗号分隔字符串。
        character_tag: 角色/系列 seed tag。
        extra_requirements: 用户自定义额外要求文本。
        r18_instructions: r18 模式下注入的自定义指令文本（为空时不注入）。
        character_pool_info: Excel 角色池信息，透传给 ``render_user_prompt``。
        placeholder_meanings: 占位符 -> 含蓄短句描述，透传给 ``render_user_prompt``
            （仅 r18 模式且抽样包含 r18 tag 时传入）。
        max_parse_retries: 解析失败时的最大重试次数（默认 2 次）。
        reasoning_effort: 模型思考模式（``"none"`` / ``"low"`` / ``"medium"`` /
            ``"high"``）；为 ``None`` 时不发送该参数。``"none"`` 关闭推理，
            输出更快且不占用 ``max_tokens``。

    Returns:
        包含生成结果的字典，结构为
        ``{"version_1": ..., "version_2": ..., "reasoning": ..., "raw": ...}``。
    """
    system_prompt = render_system_prompt(
        system_prompt_path,
        max_rating=max_rating,
        min_tags=min_tags,
        max_tags=max_tags,
        r18_instructions=r18_instructions,
    )
    user_prompt = render_user_prompt(
        sampled_tags_text=sampled_tags_text,
        safety=safety,
        min_tags=min_tags,
        max_tags=max_tags,
        theme_hint=theme_hint,
        focus_text=focus_text,
        template_path=user_template_path,
        subject_control=subject_control,
        max_rating=max_rating,
        forced_tags=forced_tags,
        forbidden_tags=forbidden_tags,
        character_tag=character_tag,
        extra_requirements=extra_requirements,
        character_pool_info=character_pool_info,
        placeholder_meanings=placeholder_meanings,
        creative_anchor_info=creative_anchor_info,
    )

    last_parse_error: Exception | None = None
    for attempt in range(max_parse_retries + 1):
        raw_response = call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            api_base=api_base,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        )
        try:
            parsed = parse_response(raw_response)
            # v2 已关闭：仅保留 version_1 单版本输出。
            return {
                "version_1": parsed["version_1"],
                "reasoning": parsed["reasoning"],
                "raw": raw_response,
            }
        except (ValueError, KeyError, TypeError) as exc:
            last_parse_error = exc
            if attempt < max_parse_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            break

    raise RuntimeError(
        f"Failed to parse DeepSeek response after {max_parse_retries + 1} attempt(s): "
        f"{last_parse_error}"
    ) from last_parse_error


def generate_v2_enhance(
    v1_prompt: str,
    safety: str,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: float = 60.0,
    max_rating: str = "r15",
    system_prompt_path: str | Path | None = None,
    max_parse_retries: int = 1,
    reasoning_effort: str | None = None,
) -> dict:
    """对 v1 提示词执行 V2 震撼美化精修（单独一次 API 调用）。

    使用 ``system_prompt_v2.md`` 的 V2 规则，将 ``v1_prompt`` 重写为更富视觉张力的
    版本：强制最高质量前缀、自然语言光影/画风长句、镜头语言与关键特征加权，同时
    保持原设核心内容与安全约束不变。

    Args:
        v1_prompt: 已生成的 v1 提示词（作为精修底稿）。
        safety: 安全标签（``safe`` / ``sensitive`` / ``nsfw`` 等），注入质量前缀。
        api_key: API Key。
        api_base: API 基础地址。
        model: 模型名称。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数。
        timeout: 单次 API 调用超时秒数。
        max_rating: 内容分级上限，默认 ``r15``。
        system_prompt_path: V2 系统提示词文件路径，默认 ``system_prompt_v2.md``。
        max_parse_retries: 解析失败时的最大重试次数（默认 1 次）。
        reasoning_effort: 模型思考模式（``"none"`` / ``"low"`` / ``"medium"`` /
            ``"high"``）；为 ``None`` 时不发送该参数。

    Returns:
        ``{"version_2": ..., "reasoning": [...], "raw": ...}``
    """
    system_prompt = render_system_prompt(
        system_prompt_path or MODULE_DIR / "system_prompt_v2.md",
        max_rating=max_rating,
        safety=safety,
    )
    user_prompt = f"SAFETY: {safety}\nV1_PROMPT:\n{v1_prompt}"

    last_parse_error: Exception | None = None
    for attempt in range(max_parse_retries + 1):
        raw_response = call_deepseek(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            api_base=api_base,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning_effort=reasoning_effort,
        )
        try:
            parsed = parse_response(raw_response)
            # system_prompt_v2.md 同样只要求输出单个 prompt 字段，
            # parse_response 将其放入 version_1；这里作为精修版 version_2 返回。
            return {
                "version_2": parsed["version_1"],
                "reasoning": parsed["reasoning"],
                "raw": raw_response,
            }
        except (ValueError, KeyError, TypeError) as exc:
            last_parse_error = exc
            if attempt < max_parse_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            break

    raise RuntimeError(
        f"Failed to parse V2 enhance response after {max_parse_retries + 1} attempt(s): "
        f"{last_parse_error}"
    ) from last_parse_error


def generate_batch(
    count: int,
    sampled_tags_text: str,
    safety: str,
    min_tags: int = 22,
    max_tags: int = 38,
    theme_hint: str = "",
    focus_text: str = "",
    system_prompt_path: str | Path | None = None,
    user_template_path: str | Path | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    timeout: float = 60.0,
    subject_control: str = "",
    max_rating: str = "r15",
    forced_tags: list[str] | str = "",
    forbidden_tags: list[str] | str = "",
    character_tag: str = "",
    extra_requirements: str = "",
    character_pool_info: dict | None = None,
    placeholder_meanings: dict[str, str] | None = None,
    max_parse_retries: int = 2,
) -> list[dict]:
    """顺序生成多条随机提示词。

    Args:
        count: 需要生成的提示词数量。
        sampled_tags_text: 已抽样的 tag 文本。
        safety: 安全标签。
        min_tags: 最少 tag 数量。
        max_tags: 最多 tag 数量。
        theme_hint: 可选主题提示。
        focus_text: 可选的生成侧重点说明文本。
        system_prompt_path: 系统提示词文件路径。
        user_template_path: 用户提示词模板路径。
        api_key: DeepSeek API Key。
        api_base: DeepSeek API 基础地址。
        model: 模型名称。
        temperature: 采样温度。
        max_tokens: 最大生成 token 数。
        timeout: 单次 API 调用超时秒数。
        subject_control: 人数/关系控制文本。
        max_rating: 当前允许的最大内容分级，默认 ``r15``。
        forced_tags: 强制保留的 tag 列表或逗号分隔字符串。
        forbidden_tags: 强制丢弃的 tag 列表或逗号分隔字符串。
        character_tag: 角色/系列 seed tag。
        extra_requirements: 用户自定义额外要求文本。
        character_pool_info: Excel 角色池信息，透传给 ``generate_single``。
        placeholder_meanings: 占位符 -> 含蓄短句描述，透传给 ``generate_single``。
        max_parse_retries: 解析失败时的最大重试次数。

    Returns:
        生成结果字典列表。
    """
    results: list[dict] = []
    for _ in range(count):
        result = generate_single(
            sampled_tags_text=sampled_tags_text,
            safety=safety,
            min_tags=min_tags,
            max_tags=max_tags,
            theme_hint=theme_hint,
            focus_text=focus_text,
            system_prompt_path=system_prompt_path,
            user_template_path=user_template_path,
            api_key=api_key,
            api_base=api_base,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            subject_control=subject_control,
            max_rating=max_rating,
            forced_tags=forced_tags,
            forbidden_tags=forbidden_tags,
            character_tag=character_tag,
            extra_requirements=extra_requirements,
            character_pool_info=character_pool_info,
            placeholder_meanings=placeholder_meanings,
            max_parse_retries=max_parse_retries,
        )
        results.append(result)
    return results


if __name__ == "__main__":
    # 本地演示：渲染用户提示词并用假响应测试解析逻辑，不发起真实 API 请求。
    sample_tags = (
        "【人数与性别】\n1girl, solo\n\n"
        "【外貌】\nlong black hair, purple eyes, medium breasts\n\n"
        "【服装与穿着状态】\ncompletely nude\n\n"
        "【姿势/动作/体位】\nsitting, spread legs\n\n"
        "【表情与反应】\nblush, parted lips, looking at viewer\n\n"
        "【镜头/景别/构图】\ndutch angle, close-up\n\n"
        "【场景与环境】\nbedroom, bed sheets\n\n"
        "【画面质感/氛围】\ncinematic composition, depth of field"
    )

    print("=== 系统提示词长度 ===")
    print(len(load_system_prompt()), "chars")

    print("\n=== 渲染后的用户提示词（前 800 字符） ===")
    rendered = render_user_prompt(
        sampled_tags_text=sample_tags,
        safety="nsfw",
        min_tags=22,
        max_tags=38,
        theme_hint="柔和光影下的私密氛围",
    )
    print(rendered[:800])
    print("...")

    print("\n=== 解析模拟响应 ===")
    dummy_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '```json\n{\n'
                        '  "version_1": "best quality, good quality, score_7, score_8, newest, nsfw,\\n'
                        '1girl, solo, long black hair, purple eyes, medium breasts,\\n'
                        'no clothes, sitting, spread legs,\\n'
                        'blush, parted lips, looking at viewer,\\n'
                        'dutch angle, close-up,\\n'
                        'bedroom, bed sheets,\\n'
                        'cinematic composition, depth of field,\\n'
                        'A young woman sits on rumpled sheets, knees parted, soft shadows on her skin.",\n'
                        '  "version_2": "masterpiece, best quality, score_9, newest, highres, absurdres, nsfw,\\n'
                        '1girl, solo, long black hair, purple eyes, medium breasts,\\n'
                        'no clothes, sitting, spread legs,\\n'
                        'blush, parted lips, looking at viewer, heavy breathing,\\n'
                        '(dutch angle:1.5), close-up,\\n'
                        'bedroom, bed sheets,\\n'
                        'cinematic composition, depth of field, dramatic tension, film grain,\\n'
                        'A young woman sits on rumpled sheets, knees parted, soft shadows on her skin.",\n'
                        '  "reasoning": [\n'
                        '    "Replaced completely nude with no clothes for better flow.",\n'
                        '    "Added dramatic tension and film grain in V2.",\n'
                        '    "Used indirect natural language for sensitive body description."\n'
                        '  ]\n'
                        '}\n```'
                    )
                }
            }
        ]
    }
    parsed = parse_response(dummy_response)
    print("version_1 prefix:", parsed["version_1"].split("\\n")[0])
    print("version_2 prefix:", parsed["version_2"].split("\\n")[0])
    print("reasoning count:", len(parsed["reasoning"]))
