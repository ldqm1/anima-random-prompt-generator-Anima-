"""GUI 专用生成引擎。

复用 CLI 的整条生成链路（抽样 → 组装 → 渲染 → 调用 DeepSeek → 后处理 →
落盘），为桌面界面提供：

- 批量生成（多线程）与实时进度回调；
- 可取消（取消后已生成的结果已落盘，不会丢失）；
- 断点续存（同一输出文件自动追加，已存在的条数不重复生成）；
- 单条预览（只抽样 + 渲染，不调用 API）与格式重渲染；
- API 参数（key/base/model/temperature 等）显式注入，绝不读写仓库内配置。
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import assembler, client, config, postprocess, retrieval
from .cli import (
    _build_fallback_character_pool_info,
    _collect_r18_tags,
    _determine_safety,
    _is_multi_character,
    _resolve_sample_constraints,
    sample_extra_requirements,
)


# ---------------------------------------------------------------------------
# 配置合并（与 cli._build_config 等价，但 API 参数显式注入）
# ---------------------------------------------------------------------------
@dataclass
class GenConfig:
    """一次生成任务的完整配置（合并 generation_config.yaml 与界面参数）。"""

    max_rating: str = "r15"
    count: int = 1
    min_tags: int = 50
    max_tags: int = 75
    theme_hint: str = ""
    subject_control: str = ""
    extra_requirements: str = ""
    forced_tags: str = ""
    forbidden_tags: str = ""
    seed: int | None = None
    workers: int = 4
    temperature: float = 0.7
    max_tokens: int = 1000
    timeout: float = 120.0
    max_parse_retries: int = 2
    reasoning_effort: str = "none"
    output_dir: str = "output"
    output_name: str = "random_prompts"
    dry_run: bool = False
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None
    proxies: dict[str, str] | None = None
    creative_anchors_enabled: bool = True
    extra_body: dict | None = None


@dataclass
class ProgressEvent:
    """进度回调事件。"""

    done: int = 0          # 已成功完成条数
    failed: int = 0        # 失败条数
    total: int = 0         # 总条数
    current: str = ""      # 当前样本简述（如 seed / 摘要）
    finished: bool = False  # 全部结束


@dataclass
class BatchResult:
    """一次批量生成的结果汇总。"""

    ok: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    output_jsonl: str = ""
    output_txt: str = ""
    audit_log: str = ""
    failures_log: str = ""
    canceled: bool = False


# ---------------------------------------------------------------------------
# 资源加载（模块级缓存，避免 GUI 重复加载）
# ---------------------------------------------------------------------------
_cache: dict[str, Any] = {}


def _load_generation_config() -> dict[str, Any]:
    """读取生成配置：默认 generation_config.yaml + 用户目录 user_config.yaml 覆盖。"""
    if "gen_cfg" not in _cache:
        try:
            import yaml

            with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
                default = yaml.safe_load(f) or {}
        except (OSError, ImportError):
            default = {}
        from .config_merge import load_user_config

        user = load_user_config()
        if user:
            from .config_merge import merge_with_defaults

            default = merge_with_defaults(default, user)
        _cache["gen_cfg"] = default
    return _cache["gen_cfg"]


def load_resources(
    progress: Callable[[str], None] | None = None,
    max_rating: str | None = None,
) -> dict[str, Any]:
    """加载一次生成所需的全部静态资源（数据库/黑名单/curated tags/角色池等）。

    知识库预过滤依赖 max_rating（r15 会滤掉 r18 tag）；传入显式
    ``max_rating`` 时按该分级构建，否则使用生成配置默认值。结果按
    ``(max_rating)`` 缓存，切换分级时自动重建。返回资源字典，供多次批量复用。
    """
    def _log(msg: str) -> None:
        if progress is not None:
            progress(msg)

    gen_cfg = _load_generation_config()
    rating = max_rating or gen_cfg.get("max_rating", "r15")

    key = f"r_{rating}"
    if key in _cache:
        return _cache[key]

    _log(f"加载知识库 v1（{rating}）…")
    knowledge_database = retrieval.load_knowledge_v1_database()
    _log("加载 curated tags…")
    curated_tags = retrieval.load_curated_tags(config.CURATED_TAGS_FILE)
    rating_map = _build_rating_map(curated_tags)

    _log("加载画师黑名单…")
    artist_blacklist = retrieval.build_artist_blacklist(
        config.ARTIST_BLACKLIST_FILES[0],
        config.ARTIST_BLACKLIST_FILES[1],
    )

    _log("加载 tag 数据库…")
    database = retrieval.load_tag_database(config.TAG_SOURCE_FILE)

    _log(f"预过滤知识库（{rating}）…")
    filtered_kb = retrieval.build_filtered_knowledge_database(
        knowledge_database,
        curated_tags,
        max_rating=rating,
    )

    creative_anchors: dict[str, list[dict]] = {}
    anchors_cfg = gen_cfg.get("creative_anchors", {})
    if anchors_cfg.get("enabled", True):
        _log("加载创意锚点池…")
        creative_anchors = retrieval.load_creative_anchors(
            anchors_cfg.get("file") or config.CREATIVE_ANCHORS_FILE
        )
        # 用户配置中的锚点覆盖（GUI 高级页可编辑 creative_anchors.yaml）
        from .config_merge import load_user_config

        user_cfg = load_user_config()
        user_anchors = user_cfg.get("creative_anchors_override")
        if isinstance(user_anchors, dict) and user_anchors:
            from .config_merge import merge_with_defaults

            merged_anchors_cfg = merge_with_defaults(
                {k: v for k, v in anchors_cfg.items()}, user_anchors
            )
            # merged 是按类别的 dict[list]，直接转成锚点结构
            creative_anchors = {}
            for cat, items in merged_anchors_cfg.items():
                if isinstance(items, list):
                    creative_anchors[str(cat)] = [
                        dict(i) for i in items
                        if isinstance(i, dict) and i.get("enabled", True) is not False
                    ]
            _log("已应用用户自定义创意锚点。")

    res = {
        "knowledge_database": filtered_kb,
        "curated_tags": curated_tags,
        "rating_map": rating_map,
        "artist_blacklist": artist_blacklist,
        "database": database,
        "creative_anchors": creative_anchors,
        "gen_cfg": gen_cfg,
        "max_rating": rating,
    }
    _cache[key] = res
    return res


def _build_rating_map(curated_tags: dict) -> dict[str, str]:
    rating_map: dict[str, str] = {}
    for cat_tags in curated_tags.values():
        for t in cat_tags:
            rating_map[t["tag"].replace("_", " ").lower()] = t.get("rating", "general")
    return rating_map


# ---------------------------------------------------------------------------
# 配置快照（供审计记录复用）
# ---------------------------------------------------------------------------
def _merged_dict(gen_cfg: dict[str, Any], section: str) -> dict[str, Any]:
    return dict(gen_cfg.get(section, {}))


def _build_snapshot(
    res: dict[str, Any], cfg: GenConfig, output_path: str
) -> dict[str, Any]:
    gen_cfg = res["gen_cfg"]
    return {
        "output_file": output_path,
        "sample_counts": gen_cfg.get("sample_counts", {}),
        "subcategory_quotas": gen_cfg.get("subcategory_quotas", {}),
        "default_word_quota": gen_cfg.get("default_word_quota", {}),
        "multi_character": gen_cfg.get("multi_character", {}),
        "focus_weights": gen_cfg.get("focus_weights", {}),
        "creative_anchors_enabled": bool(gen_cfg.get("creative_anchors", {}).get("enabled", True)),
    }


# ---------------------------------------------------------------------------
# 单条任务构建（与 cli._build_task 等价）
# ---------------------------------------------------------------------------
def _build_task(
    res: dict[str, Any],
    cfg: GenConfig,
    idx: int,
    seed: int,
    output_path: str,
) -> dict[str, Any]:
    gen_cfg = res["gen_cfg"]
    knowledge_sample_counts = dict(config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS)
    knowledge_sample_counts.update(gen_cfg.get("sample_counts", {}))
    if cfg.max_rating in ("r18", "r18g"):
        r18_counts = dict(gen_cfg.get("r18_sample_counts", {}))
        if r18_counts:
            knowledge_sample_counts.update(r18_counts)

    focus_weights = dict(gen_cfg.get("focus_weights", {}))
    if cfg.max_rating in ("r18", "r18g"):
        r18_focus = dict(gen_cfg.get("r18_focus_weights", {}))
        if r18_focus:
            focus_weights = r18_focus

    min_r18_tags = int(
        gen_cfg.get("min_r18_tags_per_sample")
        or config.DEFAULT_MIN_R18_TAGS_PER_SAMPLE
    )
    r18_instructions = (
        gen_cfg.get("r18_instructions") or config.DEFAULT_R18_INSTRUCTIONS or ""
    )

    # r18 主题控制
    r18_topic_control: dict[str, Any] = {
        "enabled": bool(config.DEFAULT_R18_TOPIC_CONTROL.get("enabled", True)),
        "topics": dict(config.DEFAULT_R18_TOPIC_CONTROL.get("topics", {})),
    }
    gen_topics = gen_cfg.get("r18_topic_control", {})
    if isinstance(gen_topics, dict):
        r18_topic_control["enabled"] = bool(
            gen_topics.get("enabled", r18_topic_control["enabled"])
        )
        r18_topic_control["topics"].update(gen_topics.get("topics", {}))
    solo = gen_topics.get("solo") if isinstance(gen_topics, dict) else None
    if isinstance(solo, dict) and solo:
        r18_topic_control["solo"] = solo

    # 多角色配置
    multi_character_cfg = dict(config.DEFAULT_MULTI_CHARACTER)
    multi_character_cfg.update(gen_cfg.get("multi_character", {}))

    # 角色池
    character_pool = dict(config.DEFAULT_CHARACTER_POOL)
    character_pool.update(gen_cfg.get("character_pool", {}))
    character_whitelist = dict(config.DEFAULT_CHARACTER_WHITELIST)
    character_whitelist.update(gen_cfg.get("character_whitelist", {}))
    category_whitelists: dict[str, Any] = {
        "enabled": bool(gen_cfg.get("category_whitelists", {}).get("enabled", False)),
        "pools": dict(gen_cfg.get("category_whitelists", {}).get("pools", {})),
    }

    # 子类配额与词配额
    subcategory_quotas = dict(gen_cfg.get("subcategory_quotas", {}))
    default_word_quota = dict(gen_cfg.get("default_word_quota", {}))

    rng = random.Random(seed)

    sampled = retrieval.sample_from_knowledge_v1(
        res["knowledge_database"],
        knowledge_sample_counts,
        res["curated_tags"],
        seed=None,
        rng=rng,
        max_rating=cfg.max_rating,
        character_whitelist=character_whitelist,
        category_whitelists=category_whitelists,
        character_pool=character_pool,
        pre_filtered=True,
        min_r18_tags=min_r18_tags,
        r18_topic_control=r18_topic_control,
        multi_character_cfg=multi_character_cfg,
        default_word_quota=default_word_quota,
        creative_anchors=res["creative_anchors"],
        subcategory_quotas=subcategory_quotas,
    )
    payload = assembler.build_prompt_payload(sampled, max_rating=cfg.max_rating)
    sampled_text = assembler.format_tags_for_llm(payload)

    # r18 占位符
    r18_placeholder_map: dict[int, str] = {}
    if cfg.max_rating in ("r18", "r18g") and min_r18_tags > 0:
        sampled_text, r18_placeholder_map = client.assign_r18_placeholders(
            sampled_text, _collect_r18_tags(sampled, res["rating_map"])
        )

    is_multi = _is_multi_character(sampled_text)
    eff_min_tags, eff_max_tags, eff_focus_text = _resolve_sample_constraints(
        is_multi, cfg.min_tags, cfg.max_tags, focus_weights, multi_character_cfg
    )

    character_tag = (
        sampled["character_series"][0]["tag"]
        if sampled.get("character_series")
        else ""
    )

    character_pool_info = None
    if (
        sampled.get("character_series")
        and sampled["character_series"][0].get("source") == "character_pool"
        and character_pool.get("use_core_appearance", True)
    ):
        probability = float(
            character_pool.get("use_core_clothing_probability", 0.5)
        )
        clothing_strategy = "core_mixed" if rng.random() < probability else "sampled_only"
        character_pool_info = {
            "characters": [
                {
                    "tag": item["tag"],
                    "series_tag": item.get("series_tag", ""),
                    "core_appearance_tags": list(item.get("core_appearance_tags", [])),
                    "core_clothing_tags": list(item.get("core_clothing_tags", [])),
                }
                for item in sampled["character_series"]
                if item.get("source") == "character_pool"
            ],
            "clothing_strategy": clothing_strategy,
        }

    if not character_pool_info:
        character_pool_info = _build_fallback_character_pool_info(
            sampled_text, character_tag, sampled
        )

    safety = _determine_safety(sampled)

    # 额外要求池
    extra_requirements_pool = dict(gen_cfg.get("extra_requirements_pool", {}))
    if extra_requirements_pool.get("enabled", False) and not cfg.extra_requirements:
        current_extra = sample_extra_requirements(extra_requirements_pool, rng=rng)
    else:
        current_extra = cfg.extra_requirements or ""

    creative_spark = rng.random() < 0.40

    forced = [
        t.strip() for t in cfg.forced_tags.split(",") if t.strip()
    ]
    forbidden = [
        t.strip() for t in cfg.forbidden_tags.split(",") if t.strip()
    ]

    return {
        "idx": idx,
        "seed": seed,
        "creative_spark": creative_spark,
        "sampled": sampled,
        "sampled_text": sampled_text,
        "character_tag": character_tag,
        "character_pool_info": character_pool_info,
        "safety": safety,
        "extra_requirements": current_extra,
        "min_tags": eff_min_tags,
        "max_tags": eff_max_tags,
        "theme_hint": cfg.theme_hint,
        "focus_text": eff_focus_text,
        "subject_control": cfg.subject_control,
        "forced_tags": forced,
        "forbidden_tags": forbidden,
        "max_rating": cfg.max_rating,
        "r18_instructions": r18_instructions,
        "r18_placeholder_map": r18_placeholder_map,
        "placeholder_meanings": (
            client.build_placeholder_meanings(r18_placeholder_map)
            if r18_placeholder_map
            else None
        ),
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout": cfg.timeout,
        "max_parse_retries": cfg.max_parse_retries,
        "reasoning_effort": cfg.reasoning_effort,
        "extra_body": cfg.extra_body,
        "proxies": cfg.proxies,
        "creative_anchor_info": payload.get("creative_anchor_info"),
        "config_snapshot": _build_snapshot(res, cfg, output_path),
    }


# ---------------------------------------------------------------------------
# 预览：只抽样 + 渲染，不调用 API
# ---------------------------------------------------------------------------
def preview(
    res: dict[str, Any],
    cfg: GenConfig,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """生成一条预览样本（不调用 API），返回渲染后的 user_prompt 与抽样明细。"""
    seed = cfg.seed if cfg.seed is not None else random.randint(0, 2**32 - 1)
    task = _build_task(res, cfg, 0, seed, output_path="")
    user_prompt = client.render_user_prompt(
        sampled_tags_text=task["sampled_text"],
        safety=task["safety"],
        min_tags=task["min_tags"],
        max_tags=task["max_tags"],
        theme_hint=task["theme_hint"],
        focus_text=task["focus_text"],
        subject_control=task["subject_control"],
        forced_tags=task["forced_tags"],
        forbidden_tags=task["forbidden_tags"],
        character_tag=task["character_tag"],
        max_rating=task["max_rating"],
        extra_requirements=task["extra_requirements"],
        character_pool_info=task["character_pool_info"],
        placeholder_meanings=task["placeholder_meanings"],
        creative_anchor_info=task["creative_anchor_info"],
    )
    return {
        "seed": seed,
        "sampled_text": task["sampled_text"],
        "safety": task["safety"],
        "is_multi": _is_multi_character(task["sampled_text"]),
        "character_tag": task["character_tag"],
        "user_prompt": user_prompt,
        "task": task,
    }


def generate_plain(
    res: dict[str, Any],
    cfg: GenConfig,
) -> dict[str, Any]:
    """无 API 模式：抽样 + 渲染完整提示词模板（不调用 API）。

    返回可直接复制发给网页端 LLM 的完整文本：
    系统提示词（纯文本输出版）+ 用户提示词。LLM 收到后按指令输出
    最终单行提示词。

    Returns:
        ``{"seed", "system_prompt", "user_prompt", "full_text",
        "sampled_text", "safety", "is_multi", "character_tag"}``。
    """
    seed = cfg.seed if cfg.seed is not None else random.randint(0, 2**32 - 1)
    task = _build_task(res, cfg, 0, seed, output_path="")
    # 纯文本输出版系统提示词（无 JSON 要求）
    system_prompt = client.render_system_prompt(
        client.MODULE_DIR / "system_prompt_plain.md",
        max_rating=task["max_rating"],
        min_tags=task["min_tags"],
        max_tags=task["max_tags"],
        r18_instructions=task["r18_instructions"],
    )
    user_prompt = client.render_user_prompt(
        sampled_tags_text=task["sampled_text"],
        safety=task["safety"],
        min_tags=task["min_tags"],
        max_tags=task["max_tags"],
        theme_hint=task["theme_hint"],
        focus_text=task["focus_text"],
        subject_control=task["subject_control"],
        forced_tags=task["forced_tags"],
        forbidden_tags=task["forbidden_tags"],
        character_tag=task["character_tag"],
        max_rating=task["max_rating"],
        extra_requirements=task["extra_requirements"],
        character_pool_info=task["character_pool_info"],
        placeholder_meanings=task["placeholder_meanings"],
        creative_anchor_info=task["creative_anchor_info"],
        plain_output=True,
    )
    full_text = (
        "【系统提示词】\n" + system_prompt + "\n\n"
        "【用户提示词】\n" + user_prompt
    )
    return {
        "seed": seed,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "full_text": full_text,
        "sampled_text": task["sampled_text"],
        "safety": task["safety"],
        "is_multi": _is_multi_character(task["sampled_text"]),
        "character_tag": task["character_tag"],
    }


# ---------------------------------------------------------------------------
# 批量生成
# ---------------------------------------------------------------------------
def generate_batch(
    res: dict[str, Any],
    cfg: GenConfig,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> BatchResult:
    """批量生成并落盘。

    输出路径 = <output_dir>/<output_name>.jsonl（同名 .txt / audit_log /
    failures_log 一并写入）。采用"追加"模式：已存在的条目跳过，天然断点续存。
    """
    result = BatchResult()
    out_dir = Path(cfg.output_dir) if cfg.output_dir else Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"{cfg.output_name}.jsonl"
    txt_path = out_dir / f"{cfg.output_name}.txt"
    audit_path = out_dir / "audit_log.jsonl"
    fail_path = out_dir / "failures_log.jsonl"

    result.output_jsonl = str(jsonl_path)
    result.output_txt = str(txt_path)
    result.audit_log = str(audit_path)
    result.failures_log = str(fail_path)

    # 断点续存：已有 jsonl 条数即已生成数量
    existing = 0
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as f:
            existing = sum(1 for _ in f)
    total = max(cfg.count - existing, 0)
    if total <= 0:
        result.ok = cfg.count
        if on_progress:
            on_progress(ProgressEvent(done=cfg.count, failed=0, total=cfg.count,
                                      current="已完成（断点续存）", finished=True))
        return result

    # 种子生成
    rng = random.Random()
    seeds = [cfg.seed + i for i in range(cfg.count)] if cfg.seed is not None else [
        rng.randint(0, 2**32 - 1) for _ in range(cfg.count)
    ]
    seeds = seeds[existing:]  # 跳过已生成的

    # 构建任务（并行抽样）
    tasks: list[dict[str, Any]] = []
    sampler = ThreadPoolExecutor(max_workers=cfg.workers)
    try:
        futures = [
            sampler.submit(_build_task, res, cfg, idx, seed, str(jsonl_path))
            for idx, seed in enumerate(seeds, start=existing)
        ]
        for fut in futures:
            tasks.append(fut.result())
    finally:
        sampler.shutdown(wait=True)

    write_lock = threading.Lock()
    done = 0
    failed = 0
    errors: list[str] = []

    jsonl_handle = jsonl_path.open("a", encoding="utf-8")
    txt_handle = txt_path.open("a", encoding="utf-8")
    audit_handle = audit_path.open("a", encoding="utf-8")
    fail_handle = fail_path.open("a", encoding="utf-8")

    def _emit() -> None:
        if on_progress:
            on_progress(ProgressEvent(
                done=existing + done,
                failed=failed,
                total=cfg.count,
                current=f"seed={tasks[done + failed]['seed']}" if done + failed < len(tasks) else "",
                finished=False,
            ))

    try:
        executor = ThreadPoolExecutor(max_workers=cfg.workers)
        futures = [
            executor.submit(
                _generate_one,
                task,
                res,
                cfg,
                fail_handle,
                write_lock,
            )
            for task in tasks
        ]
        try:
            for future in futures:
                if cancel_event is not None and cancel_event.is_set():
                    result.canceled = True
                    break
                try:
                    res2 = future.result()
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(str(exc))
                    _emit()
                    continue
                if not res2["ok"]:
                    failed += 1
                    errors.append(res2["error"])
                    _emit()
                    continue
                record = res2["record"]
                with write_lock:
                    audit = record.pop("__audit__", None)
                    if audit is not None:
                        try:
                            audit_handle.write(json.dumps(audit, ensure_ascii=False) + "\n")
                            audit_handle.flush()
                        except (TypeError, ValueError, OSError):
                            pass
                    jsonl_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    jsonl_handle.flush()
                    version_1 = record.get("version_1", "")
                    if version_1:
                        txt_handle.write(version_1 + "\n")
                        txt_handle.flush()
                done += 1
                _emit()
        except KeyboardInterrupt:
            result.canceled = True
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        finally:
            executor.shutdown(wait=False)
    finally:
        jsonl_handle.close()
        txt_handle.close()
        audit_handle.close()
        fail_handle.close()

    result.ok = done
    result.failed = failed
    result.errors = errors
    if on_progress:
        on_progress(ProgressEvent(
            done=existing + done,
            failed=failed,
            total=cfg.count,
            current="完成" if not result.canceled else "已取消",
            finished=True,
        ))
    return result


def _generate_one(
    task: dict[str, Any],
    res: dict[str, Any],
    cfg: GenConfig,
    fail_handle: Any,
    lock: Any,
) -> dict[str, Any]:
    """线程内执行单条 API 调用与后处理（与 cli._generate_one_task 等价）。"""
    try:
        anchor_tags = [
            a.get("tag", "") for a in (task.get("creative_anchor_info") or [])
            if a.get("tag")
        ]
        anchor_retry = False
        max_anchor_attempts = 2 if anchor_tags else 1
        for attempt in range(max_anchor_attempts):
            result = client.generate_single(
                sampled_tags_text=task["sampled_text"],
                safety=task["safety"],
                min_tags=task["min_tags"],
                max_tags=task["max_tags"],
                theme_hint=task["theme_hint"],
                focus_text=task["focus_text"],
                temperature=task["temperature"],
                max_tokens=task["max_tokens"],
                timeout=task["timeout"],
                max_parse_retries=task["max_parse_retries"],
                subject_control=task["subject_control"],
                forced_tags=task["forced_tags"],
                forbidden_tags=task["forbidden_tags"],
                character_tag=task["character_tag"],
                max_rating=task["max_rating"],
                extra_requirements=task["extra_requirements"],
                character_pool_info=task["character_pool_info"],
                placeholder_meanings=task.get("placeholder_meanings"),
                r18_instructions=task["r18_instructions"],
                reasoning_effort=task["reasoning_effort"],
                extra_body=task.get("extra_body"),
                creative_spark=bool(task.get("creative_spark")),
                proxies=task.get("proxies"),
                creative_anchor_info=task.get("creative_anchor_info"),
                api_key=cfg.api_key,
                api_base=cfg.api_base,
                model=cfg.model,
            )
            task["render_snapshot"] = result.get("render_snapshot")
            try:
                _raw = result.get("raw") or {}
                _first = (_raw.get("choices") or [{}])[0]
                task["model_raw_output"] = (
                    _first.get("message") or {}
                ).get("content") or ""
            except Exception:  # noqa: BLE001
                task["model_raw_output"] = ""
            result = postprocess.postprocess(
                result,
                res["artist_blacklist"],
                res["database"],
                target_safety=task["safety"],
                max_rating=task["max_rating"],
                max_tags=task.get("max_tags"),
                anchor_tags=anchor_tags if attempt > 0 else None,
            )
            missing_anchors = (
                result.get("postprocess_log", {})
                .get("version_1", {})
                .get("anti_convergence", {})
                .get("missing_anchors", [])
            )
            if not missing_anchors:
                break
            if attempt + 1 < max_anchor_attempts:
                anchor_retry = True
                task["forced_tags"] = (
                    (task.get("forced_tags") or "") + ", " + ", ".join(missing_anchors)
                ).strip(", ")
        ph_map = task.get("r18_placeholder_map") or {}
        if ph_map:
            result["version_1"] = client.restore_r18_placeholders(
                result["version_1"], ph_map
            )
        record = _record_to_jsonl(result, task["sampled"], False, task["focus_text"])
        record["seed"] = task["seed"]
        if anchor_retry:
            record["anchor_retry"] = True
        try:
            task["model"] = cfg.model
            record["__audit__"] = _build_audit_record(task, result, record)
        except Exception as exc:  # noqa: BLE001
            record["__audit__"] = {"schema_version": 1, "error": str(exc)}
        return {"ok": True, "record": record, "idx": task["idx"]}
    except Exception as exc:  # noqa: BLE001
        _log_generation_failure(fail_handle, lock, task, exc)
        return {"ok": False, "error": str(exc), "idx": task["idx"]}


def _record_to_jsonl(
    result: dict[str, Any],
    sampled_tags: dict[str, list[dict[str, Any]]],
    v2_only: bool,
    focus_text: str = "",
) -> dict[str, Any]:
    record = dict(result)
    record["sampled_tags"] = {
        category: [item["tag"] for item in items]
        for category, items in sampled_tags.items()
    }
    if focus_text:
        record["focus_text"] = focus_text
    if v2_only and "version_2" in record:
        record.pop("version_1", None)
    return record


def _build_audit_record(
    task: dict[str, Any],
    result: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    import hashlib
    import uuid

    from .cli import _prompt_hashes, _template_version

    version_1 = result.get("version_1", "")
    hashes = _prompt_hashes(version_1) if version_1 else {
        "sha256": "", "tags_sha256": "", "hash_version": "", "norm_tags": [],
    }
    sampled = task.get("sampled") or {}

    def _item(cat: str) -> list[dict[str, Any]]:
        out = []
        for it in sampled.get(cat) or []:
            if isinstance(it, dict):
                out.append({
                    "tag": it.get("tag", ""),
                    "subcategory": it.get("subcategory", ""),
                    "source": it.get("source", ""),
                })
            else:
                out.append({"tag": str(it), "subcategory": "", "source": ""})
        return out

    anchors = [
        {
            "tag": a.get("tag", ""),
            "anchor_cn": a.get("anchor_cn", ""),
            "anchor_tags": list(a.get("anchor_tags", [])),
        }
        for a in (task.get("creative_anchor_info") or [])
    ]
    snapshot = task.get("config_snapshot") or {}
    render_snap = task.get("render_snapshot") or {}
    tv = _template_version()
    return {
        "schema_version": 2,
        "id": "%s-%s" % (task.get("seed", ""), hashes["tags_sha256"][:8]),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": {
            "name": "anima-random-prompt-generator",
            "output_file": (snapshot.get("output_file") or ""),
        },
        "params": {
            "seed": task.get("seed"),
            "max_rating": task.get("max_rating"),
            "min_tags": task.get("min_tags"),
            "max_tags": task.get("max_tags"),
            "temperature": task.get("temperature"),
            "model": task.get("model", ""),
            "theme_hint": task.get("theme_hint", ""),
            "subject_control": task.get("subject_control", ""),
            "extra_requirements": task.get("extra_requirements", ""),
            "forced_tags": task.get("forced_tags", "") or "",
            "forbidden_tags": task.get("forbidden_tags", "") or "",
            "is_multi_character": bool(
                task.get("sampled_text", "").lower().find("2girls") >= 0
            ),
        },
        "eval_input": {
            "template_version": tv,
            "prompt_version": "v1",
            "system_prompt": render_snap.get("system_prompt") or "",
            "user_prompt": render_snap.get("user_prompt") or "",
        },
        "model_raw_output": task.get("model_raw_output", ""),
        "sampled": {
            "count_gender": _item("count_gender"),
            "character_series": _item("character_series"),
            "appearance": _item("appearance"),
            "clothing_state": _item("clothing_state"),
            "pose_action_sex": _item("pose_action_sex"),
            "expression_reaction": _item("expression_reaction"),
            "camera_shot": _item("camera_shot"),
            "scene_environment": _item("scene_environment"),
            "detail_mood": _item("detail_mood"),
            "creative_anchor": _item("creative_anchor"),
        },
        "anchors": anchors,
        "quota_snapshot": {
            "sample_counts": snapshot.get("sample_counts", {}),
            "subcategory_quotas": snapshot.get("subcategory_quotas", {}),
            "default_word_quota": snapshot.get("default_word_quota", {}),
            "multi_character": snapshot.get("multi_character", {}),
            "focus_weights": snapshot.get("focus_weights", {}),
            "creative_anchors_enabled": snapshot.get("creative_anchors_enabled", True),
        },
        "prompt": {
            "version_1": version_1,
            "sha256": hashes["sha256"],
            "tags_sha256": hashes["tags_sha256"],
            "hash_version": hashes.get("hash_version", "unknown"),
            "norm_tags": hashes.get("norm_tags", []),
            "tag_count": len([t for t in version_1.split(", ") if t.strip()])
            if version_1
            else 0,
        },
        "postprocess": record.get("postprocess_log", {}).get("version_1", {}),
        "unknown_tags": record.get("unknown_tags", []),
        "anchor_retry": bool(record.get("anchor_retry")),
    }


def _log_generation_failure(
    fail_handle: Any,
    lock: Any,
    task: dict[str, Any],
    exc: Exception,
) -> None:
    from .client import ResponseParseError

    if fail_handle is None:
        return
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, ResponseParseError):
        raw = cause.raw if isinstance(cause.raw, dict) else {}
        msg = (
            raw.get("choices", [{}])[0].get("message", {})
            if isinstance(raw, dict) and raw.get("choices")
            else {}
        )
        record = {
            "type": "generate_failure",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "idx": task.get("idx"),
            "seed": task.get("seed"),
            "max_rating": task.get("max_rating"),
            "error": str(exc),
            "input_sampled_text": task.get("sampled_text", ""),
            "model_output": {
                "content": cause.content,
                "reasoning_content": msg.get("reasoning_content"),
                "finish_reason": cause.finish_reason,
                "usage": cause.usage,
            },
        }
    else:
        record = {
            "type": "generate_failure",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "idx": task.get("idx"),
            "seed": task.get("seed"),
            "max_rating": task.get("max_rating"),
            "error": str(exc),
            "input_sampled_text": task.get("sampled_text", ""),
        }
    line = json.dumps(record, ensure_ascii=False, default=str)
    if lock is not None:
        with lock:
            try:
                fail_handle.write(line + "\n")
                fail_handle.flush()
            except (OSError, ValueError, TypeError):
                pass
    else:
        try:
            fail_handle.write(line + "\n")
            fail_handle.flush()
        except (OSError, ValueError, TypeError):
            pass
