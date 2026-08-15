#!/usr/bin/env python3
"""OpenCode Go 预算守护调度脚本（独立于 run_generator.py）。

功能：
- 强制 ``reasoning_effort=none``：关闭模型推理 token，单条耗时/成本降低约 10 倍。
- 预算账本：逐次记录真实 usage，按 5 小时 / 7 天 / 30 天三个窗口核算消耗，
  任一窗口达到阈值（默认 90%）即暂停新任务，避免超额浪费。
- 失败重试：网络抖动/解析失败的样本自动重试（重试成功才计费），最多 N 次。
- 结果追加写入 JSONL 与纯文本，中途中断后重新运行可续跑。

用法示例：
    python opencode_runner.py --count 5000 --output output/opencode_prompts.jsonl \
        --api-config prompt/random_generator/api_profiles/deepseek4.yaml --workers 16
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from prompt.random_generator import assembler, client, config, postprocess, retrieval
from prompt.random_generator.cli import (
    _build_fallback_character_pool_info,
    _build_config,
    _collect_r18_tags,
    _determine_safety,
    _is_multi_character,
    _load_generation_config,
    _load_yaml_config,
    _record_to_jsonl,
    _resolve_api_profile,
    _resolve_sample_constraints,
    sample_extra_requirements,
)

# ---------------------------------------------------------------------------
# OpenCode Go 计费规则（DeepSeek V4 Flash）
# ---------------------------------------------------------------------------
WINDOWS: list[tuple[str, float, float]] = [
    ("5h", 5 * 3600, 12.0),
    ("7d", 7 * 24 * 3600, 30.0),
    ("30d", 30 * 24 * 3600, 60.0),
]
PRICE_INPUT_PER_M = 0.14      # 未命中缓存的输入 token
PRICE_CACHED_PER_M = 0.0028   # 命中缓存的输入 token（prompt cache read）
PRICE_OUTPUT_PER_M = 0.28     # 输出 token

DEFAULT_LEDGER_FILE = "output/opencode_budget.jsonl"


def _calibration_path(ledger_file: str | Path) -> Path:
    """真实用量折算系数文件（与账本同目录，账本路径 + .calibration.json）。

    平台控制台（opencode.ai/auth）显示的真实用量可能远低于本地按官方单价
    估算的 token 成本（对直接 API 调用计费低于公布单价，官方 issue #26213），
    ``--real-usage`` 校准后系数保存于此，后续运行自动沿用。
    """
    return Path(str(ledger_file) + ".calibration.json")


def _txt_multi_ratio(txt_path: str | Path) -> float:
    """统计纯文本输出文件中多人提示词占比（命中 '2girls'/'2 girls'，忽略大小写）。

    文件不存在或为空时返回 0.0。
    """
    try:
        total = 0
        multi = 0
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                total += 1
                ll = line.lower()
                if "2girls" in ll or "2 girls" in ll:
                    multi += 1
        return multi / total if total else 0.0
    except OSError:
        return 0.0


def _acquire_file_lock(ledger_file: Path, timeout: float = 30.0) -> None:
    """跨进程独占锁（O_CREAT|O_EXCL 锁文件），带超时与陈旧锁清理。

    多个生成器实例（如 r15 与 r18 同时运行）共享同一账本时，用文件锁保证
    「重载最新记录 → 追加 → 原子替换保存」整段操作不被打断，避免丢失更新。
    Windows 上 ``os.open(..., O_EXCL)`` 同样可靠；进程崩溃残留的锁文件
    超过 60 秒按 mtime 强制清除，防止永久卡死。
    """
    lock_path = Path(str(ledger_file) + ".lock")
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 60:
                    lock_path.unlink()
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"等待账本文件锁超时: {lock_path}")
            time.sleep(0.05)


def _release_file_lock(ledger_file: Path) -> None:
    """释放跨进程锁。"""
    try:
        Path(str(ledger_file) + ".lock").unlink()
    except OSError:
        pass


class QuotaExceededError(RuntimeError):
    """平台额度耗尽 / 限流类错误（HTTP 429/402/403 或 quota/limit 关键字）。

    与普通网络/解析失败区分：触发后进入冷却等待，而不是按普通失败重试止损。
    """


def _is_quota_error(exc: Exception) -> bool:
    """判断异常是否为平台额度/限流类错误。

    - 429/402 直接判定（标准限流/额度耗尽码）；
    - 403 需带 quota/limit/balance 关键字（纯 Forbidden 不算）；
    - 其余状态或连接类异常按响应/异常文本中的 quota/rate limit 关键字判定。
    """
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    if status in (429, 402):
        return True
    body = ""
    if resp is not None:
        try:
            body = resp.text or ""
        except Exception:  # noqa: BLE001
            body = ""
    text = (str(exc) + " " + body).lower()
    if status == 403:
        return any(k in text for k in ("quota", "limit", "balance"))
    return any(k in text for k in ("quota", "rate limit"))


class BudgetLedger:
    """OpenCode Go 预算账本：记录每次成功请求的 token 用量与成本。

    存储为 JSONL（每行一条记录），初始化时一次性读取到内存，此后纯内存
    记账、追加落盘；``--ledger`` 兼容旧 JSON 格式，启动时自动迁移。
    """

    def __init__(self, ledger_file: str | Path):
        self.ledger_file = Path(ledger_file)
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        # 各窗口真实用量折算系数 {窗口名: factor}；1.0 表示不折算。
        # 本地按官方单价估算的 token 成本可能高于平台实际计费，用
        # --real-usage 把控制台真实百分比折算为系数，status/cooldown/avg 全部套用。
        self.factor: dict[str, float] = {}
        self._load_calibration()
        self._load()

    MAX_RECORDS = 200000  # 内存与磁盘均只保留最近 20 万条

    def _load(self) -> None:
        """初始化时读取一次账本，兼容旧 JSON 格式并自动迁移为 JSONL。

        - 优先整体解析：若整个文件是单个 JSON 文档（旧格式
          ``{"records": [...]}``，indent 美化多行），解析后重写为 JSONL；
        - 否则按 JSONL 逐行解析，坏行（如崩溃遗留的半行）自动跳过；
        - 超过 MAX_RECORDS 时截断，仅保留最近条目（一次性成本）。
        """
        if not self.ledger_file.exists():
            return
        try:
            text = self.ledger_file.read_text(encoding="utf-8")
        except OSError:
            self.records = []
            return
        # 旧格式：整个文件是一个 JSON 文档
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "records" in data:
            records = data["records"]
            if len(records) > self.MAX_RECORDS:
                records = records[-self.MAX_RECORDS :]
            self._rewrite(records)
            self.records = records
            return
        # 新格式 JSONL：逐行解析，坏行跳过（崩溃最多损失一行）
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "ts" in obj:
                records.append(obj)
        if len(records) > self.MAX_RECORDS:
            records = records[-self.MAX_RECORDS :]
            self._rewrite(records)
        self.records = records

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        """全量重写账本（仅初始化阶段用于格式迁移/超限截断，一次性成本）。"""
        _acquire_file_lock(self.ledger_file)
        try:
            self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_file.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                encoding="utf-8",
            )
        finally:
            _release_file_lock(self.ledger_file)

    # ---- 真实用量校准 ----

    def _load_calibration(self) -> None:
        """启动时读取折算系数文件（不存在则系数为空，等价于 1.0）。"""
        path = _calibration_path(self.ledger_file)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            names = {name for name, _, _ in WINDOWS}
            self.factor = {
                str(k): float(v) for k, v in data.items() if k in names
            }

    def _save_calibration(self) -> None:
        """持久化折算系数，供后续运行自动沿用。"""
        path = _calibration_path(self.ledger_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.factor, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _factor(self, name: str) -> float:
        return self.factor.get(name, 1.0)

    def apply_real_usage(self, spec: str) -> None:
        """按平台控制台真实用量百分比校准本地账本折算系数。

        ``spec`` 形如 ``"5h:2,7d:22,30d:22"``（百分比，官网控制台查询）。
        对每个窗口：factor = (百分比/100 × 窗口限额) / 本地记账成本；
        窗口无本地记录时跳过（沿用原系数）。折算系数持久化到 sidecar 文件，
        账本原始记录不动，status/cooldown/avg 按系数折算。
        """
        parsed: dict[str, float] = {}
        for token in spec.split(","):
            token = token.strip()
            if not token:
                continue
            name, _, pct = token.partition(":")
            try:
                parsed[name.strip()] = float(pct.strip().rstrip("%")) / 100.0
            except ValueError as exc:
                raise ValueError(
                    f"无法解析 --real-usage 片段: {token!r}（期望如 5h:2,7d:22,30d:22）"
                ) from exc
        now = time.time()
        updated: list[str] = []
        for name, seconds, limit in WINDOWS:
            if name not in parsed:
                continue
            raw = self.window_cost(seconds, now, calibrated=False)
            if raw <= 0:
                continue
            factor = (parsed[name] * limit) / raw
            self.factor[name] = factor
            updated.append(f"{name} {parsed[name] * 100:.0f}% -> 系数 {factor:.3f}")
        self._save_calibration()
        if updated:
            print("真实用量校准（--real-usage，系数已保存，后续运行自动沿用）:")
            for line in updated:
                print(f"  {line}")

    def _append(self, rec: dict[str, Any]) -> None:
        """追加写入单条记录（JSONL 一行）。"""
        self.ledger_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    @staticmethod
    def cost_from_usage(usage: dict[str, Any]) -> float:
        """根据 API usage 计算本请求成本（美元）。"""
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens", 0) or 0)
        if not cached:
            cached = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        uncached = max(prompt - cached, 0)
        return (
            uncached * PRICE_INPUT_PER_M
            + cached * PRICE_CACHED_PER_M
            + completion * PRICE_OUTPUT_PER_M
        ) / 1e6

    def record(self, usage: dict[str, Any], ok: bool = True) -> float:
        """记录一次请求，返回本次成本（美元）。失败请求成本记 0。

        内存记账 + JSONL 追加落盘：一次请求仅追加一行，锁持有时间从
        「全量重载 + 全量写盘」降至微秒级，可支撑高并发；跨进程安全仍由
        文件锁保证（r15 与 r18 两个生成器同时运行时共享同一账本）。
        """
        cost = self.cost_from_usage(usage) if ok else 0.0
        rec = {
            "ts": time.time(),
            "cost": cost,
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "cached_tokens": int(
                (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
            ),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        }
        with self._lock:
            _acquire_file_lock(self.ledger_file)
            try:
                self.records.append(rec)
                if len(self.records) > self.MAX_RECORDS:
                    self.records = self.records[-self.MAX_RECORDS :]
                self._append(rec)
            finally:
                _release_file_lock(self.ledger_file)
        return cost

    def window_cost(
        self, seconds: float, now: float | None = None, calibrated: bool = True
    ) -> float:
        """返回最近 seconds 秒内的累计成本（美元）。

        ``calibrated=True`` 时按窗口折算系数换算为平台真实用量
        （用于预算判断/展示）；``calibrated=False`` 返回本地原始估算。
        """
        now = now if now is not None else time.time()
        cutoff = now - seconds
        cost = sum(r["cost"] for r in self.records if r["ts"] >= cutoff)
        if calibrated:
            name = next((n for n, s, _ in WINDOWS if s == seconds), None)
            if name:
                cost *= self._factor(name)
        return cost

    def status(self, now: float | None = None) -> list[dict[str, Any]]:
        """返回各窗口使用情况。"""
        now = now if now is not None else time.time()
        status: list[dict[str, Any]] = []
        for name, seconds, limit in WINDOWS:
            used = self.window_cost(seconds, now)
            status.append(
                {
                    "name": name,
                    "used": used,
                    "limit": limit,
                    "ratio": used / limit if limit else 0.0,
                    "remaining": max(limit - used, 0.0),
                }
            )
        return status

    def can_proceed(self, limit_ratio: float, now: float | None = None) -> bool:
        """任一窗口达到阈值即返回 False（暂停新请求）。"""
        for item in self.status(now):
            if item["ratio"] >= limit_ratio:
                return False
        return True

    def cooldown_seconds(self, limit_ratio: float, now: float | None = None) -> float:
        """返回需要等待多少秒，所有窗口才能恢复到阈值以下。

        对每个超阈值的窗口，按时间从旧到新累计需要滑出的记录成本，
        取最旧记录的滑出时刻作为该窗口的等待时间；返回所有窗口的最大值。
        未超阈值的窗口不参与计算。
        """
        now = now if now is not None else time.time()
        waits: list[float] = []
        for name, seconds, limit in WINDOWS:
            factor = self._factor(name)
            used = self.window_cost(seconds, now, calibrated=True)
            if used < limit * limit_ratio:
                continue
            need = used - limit * limit_ratio
            cutoff = now - seconds
            in_window = sorted(
                (r for r in self.records if r["ts"] >= cutoff),
                key=lambda r: r["ts"],
            )
            removed = 0.0
            wait = 0.0
            for r in in_window:
                removed += r["cost"] * factor
                wait = max(wait, r["ts"] + seconds - now)
                if removed >= need:
                    break
            waits.append(wait)
        return max(waits) if waits else 0.0

    def avg_cost(self, last_n: int = 100) -> float:
        """最近 last_n 条记录的平均成本（美元/条，按 7d 窗口系数折算为真实单价）。"""
        recent = [r["cost"] for r in self.records[-last_n:] if r["cost"] > 0]
        if not recent:
            return 0.0
        return sum(recent) / len(recent) * self._factor("7d")

    def print_status(self) -> None:
        lines = ["--- OpenCode Go 预算状态 ---"]
        for item in self.status():
            lines.append(
                f"  {item['name']:<4} 已用 ${item['used']:.4f} / "
                f"${item['limit']:.2f} ({item['ratio'] * 100:.1f}%)"
            )
        factors = {n: k for n, k in self.factor.items() if k != 1.0}
        if factors:
            lines.append(
                "  真实用量折算系数: "
                + " ".join(f"{n}x{k:.3f}" for n, k in factors.items())
            )
        avg = self.avg_cost()
        if avg > 0:
            total_remaining = min(s["remaining"] for s in self.status())
            lines.append(f"  平均成本 ${avg:.6f}/条，按当前速率预计还可跑约 {int(total_remaining / avg)} 条")
        print("\n".join(lines))


def _chat_completion(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    api_base: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    reasoning_effort: str | None = "none",
) -> dict[str, Any]:
    """调用 OpenAI 兼容接口；reasoning_effort 默认 ``none`` 关闭推理。"""
    import requests

    payload: dict[str, Any] = {
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
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _generate_one(
    task: dict[str, Any],
    api_key: str,
    api_base: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_parse_retries: int,
    artist_blacklist: Any,
    database: Any,
    ledger: BudgetLedger,
    v2_enhance: bool = False,
    reasoning_effort: str | None = "none",
) -> dict[str, Any]:
    """执行单条：渲染 → 调用 API（关推理）→ 记账 → 解析 → 后处理。"""
    # 系统提示词按任务渲染 max_rating/min_tags/max_tags/r18_instructions 变量，
    # 与 CLI 的 client.generate_single 行为保持一致（含 r18 注入指令）。
    system_prompt = client.render_system_prompt(
        max_rating=task["max_rating"],
        min_tags=task["min_tags"],
        max_tags=task["max_tags"],
        r18_instructions=task.get("r18_instructions", ""),
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
        placeholder_meanings=task.get("placeholder_meanings"),
    )

    last_error: Exception | None = None
    last_quota = False
    raw_response: dict[str, Any] | None = None
    for attempt in range(max_parse_retries + 1):
        try:
            raw_response = _chat_completion(
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
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            last_quota = _is_quota_error(exc)
            if attempt < max_parse_retries:
                time.sleep(1.5 * (attempt + 1))

    if raw_response is None:
        if last_quota:
            raise QuotaExceededError(f"平台额度/限流: {last_error}")
        raise RuntimeError(f"API 调用失败: {last_error}")

    usage = raw_response.get("usage") or {}
    cost = ledger.record(usage, ok=True)
    task["cost"] = cost

    last_parse_error: Exception | None = None
    for attempt in range(max_parse_retries + 1):
        try:
            parsed = client.parse_response(raw_response)
            # v2 已关闭：仅保留 version_1 单版本输出。
            result: dict[str, Any] = {
                "version_1": parsed["version_1"],
                "reasoning": parsed["reasoning"],
                "raw": raw_response,
                "cost": cost,
                "usage": usage,
            }
            result = postprocess.postprocess(
                result,
                artist_blacklist,
                database,
                target_safety=task["safety"],
                max_rating=task["max_rating"],
            )
            if v2_enhance:
                v2_res = client.generate_v2_enhance(
                    v1_prompt=result["version_1"],
                    safety=task["safety"],
                    api_key=api_key,
                    api_base=api_base,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    max_parse_retries=max_parse_retries,
                    max_rating=task["max_rating"],
                    reasoning_effort=reasoning_effort,
                )
                v2_usage = (v2_res.get("raw") or {}).get("usage") or {}
                cost += ledger.record(v2_usage, ok=True)
                result["version_2"] = v2_res["version_2"]
                result["reasoning"] = v2_res["reasoning"]
                result["raw_v2"] = v2_res["raw"]
                result["cost"] = cost
            # r18 占位符统一还原为真实 tag（V2 精修输入保持占位符版本，
            # 最后统一还原，避免 V2 模型按禁词规则改写露骨词）。
            ph_map = task.get("r18_placeholder_map") or {}
            if ph_map:
                result["version_1"] = client.restore_r18_placeholders(
                    result["version_1"], ph_map
                )
                if result.get("version_2"):
                    result["version_2"] = client.restore_r18_placeholders(
                        result["version_2"], ph_map
                    )
            return result
        except (ValueError, KeyError, TypeError) as exc:
            last_parse_error = exc
            if attempt < max_parse_retries:
                time.sleep(1.0 * (attempt + 1))

    raise RuntimeError(
        f"解析失败（已计费 ${cost:.6f}）: {last_parse_error}"
    )


def _dispatch_batch(
    executor: ThreadPoolExecutor,
    tasks: list[dict[str, Any]],
    worker,
    max_workers: int,
    max_retries: int,
    quota_fail_n: int,
    on_success,
    on_quota,
    on_retry,
    on_fail,
    on_report,
    wait_quota_cooldown,
    budget_check=None,
    wait_budget_cooldown=None,
    quota_held=None,
) -> dict[str, int]:
    """滑动窗口调度一批任务：任一任务完成立即补提交，保持 worker 满负荷。

    与旧「波次屏障」调度的核心区别：不再等待整波全部完成才提交下一批，
    而是维护 ``in_flight`` 滑动窗口（大小 = max_workers），任务一完成就
    从 ``pending`` 补提交新任务，慢任务不再拖住整个流水线。

    结果统计返回 ``{"ok", "fail", "retry", "quota_total", "batch_fail"}``；
    tasks 为空时直接返回全 0 统计，不调用任何回调。
    """
    stats: dict[str, int] = {
        "ok": 0,
        "fail": 0,
        "retry": 0,
        "quota_total": 0,
        "batch_fail": 0,
    }
    if not tasks:
        return stats

    pending = list(tasks)
    in_flight: dict[Any, dict[str, Any]] = {}
    retry_counts: dict[int, int] = {}
    wave_quota = 0
    if quota_held is None:
        quota_held = []
    budget_checked = 0  # 距上次预算检查已完成的条数（每 max_workers 条检查一次）

    def _submit() -> None:
        """从 pending 头部取任务补提交，填满 in_flight 窗口。"""
        while len(in_flight) < max_workers and pending:
            task = pending.pop(0)
            in_flight[executor.submit(worker, task)] = task

    _submit()
    try:
        while in_flight or pending:
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                res = future.result()
                task = res["task"]
                del in_flight[future]
                if res["ok"]:
                    on_success(res)
                    stats["ok"] += 1
                elif res.get("quota"):
                    # 额度/限流失败：暂缓重试（不占普通重试次数），累计到阈值后冷却再排回
                    wave_quota += 1
                    stats["quota_total"] += 1
                    quota_held.append(task)
                    on_quota()
                else:
                    # 普通失败：入队尾随队列自然延后重试，超过 max_retries 判定失败
                    retry_counts[task["idx"]] = retry_counts.get(task["idx"], 0) + 1
                    if retry_counts[task["idx"]] <= max_retries:
                        pending.append(task)
                        stats["retry"] += 1
                        on_retry()
                    else:
                        stats["fail"] += 1
                        stats["batch_fail"] += 1
                        on_fail()
                on_report()
                # 每完成 max_workers 条且启用账本守门时做一次预算检查
                budget_checked += 1
                if budget_check is not None and budget_checked >= max_workers:
                    budget_checked = 0
                    if not budget_check():
                        wait_budget_cooldown()
            # 本轮额度失败达到阈值 → 冷却后把暂缓任务排回队列重试
            if wave_quota >= quota_fail_n:
                wait_quota_cooldown()
                pending.extend(quota_held)
                quota_held.clear()
                wave_quota = 0
            _submit()
            # 滑动窗口下若尾部剩余 quota 失败数不足阈值，任务会滞留在 quota_held；
            # 队列与在途均空时把它们排回继续重试，避免任务随批次结束丢失。
            if not in_flight and not pending and quota_held:
                pending.extend(quota_held)
                quota_held.clear()
    except KeyboardInterrupt:
        # 中断时把已完成的成功结果补写落盘，再重新抛出
        for future in list(in_flight):
            if future.done():
                try:
                    res = future.result()
                except Exception:  # noqa: BLE001
                    continue
                if res["ok"]:
                    on_success(res)
        raise
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opencode-runner",
        description="OpenCode Go 预算守护生成器（强制关闭推理）",
    )
    parser.add_argument("--count", type=int, default=1, help="生成数量")
    parser.add_argument("--output", type=str, default=None, help="JSONL 输出路径")
    parser.add_argument("--workers", type=int, default=4, help="并发数")
    parser.add_argument("--api-config", type=str, default=None, help="API 配置文件（YAML）")
    parser.add_argument("--api-key", type=str, default=None, help="API Key（临时覆盖）")
    parser.add_argument("--api-base", type=str, default=None, help="API Base URL（临时覆盖）")
    parser.add_argument("--model", type=str, default=None, help="模型名（临时覆盖）")
    parser.add_argument(
        "--max-rating",
        type=str,
        default=None,
        choices=config.RATING_ORDER,
        help="允许抽样的最大年龄分级（默认读取 generation_config.yaml 中的 max_rating；"
        "r18 运行与 r15 运行同时启动时，用本参数显式区分，避免修改共享配置文件）",
    )
    parser.add_argument("--ledger", type=str, default=DEFAULT_LEDGER_FILE, help="预算账本文件")
    parser.add_argument(
        "--real-usage",
        type=str,
        default=None,
        help='平台控制台真实用量百分比（官网 opencode.ai/auth 查询），格式 "5h:2,7d:22,30d:22"。'
        "启动时按此比例把本地账本折算系数化并持久化，后续运行自动沿用；"
        "本地按官方单价估算的 token 成本可能与平台实际计费差异较大（直接 API 调用计费低于公布单价），"
        "用控制台数字对齐可避免误触发预算冷却。",
    )
    parser.add_argument("--limit-ratio", type=float, default=0.9, help="窗口使用率阈值，达到后暂停（默认 0.9）")
    parser.add_argument(
        "--ledger-guard",
        action="store_true",
        help="启用账本预算守门：本地估算达到阈值时冷却。默认关闭——"
        "平台无用量查询 API，本地估算与实际计费差异大，账本仅作参考展示，"
        "实际止损交给 --quota-cooldown（平台额度/限流错误冷却）。",
    )
    parser.add_argument(
        "--quota-cooldown",
        type=int,
        default=30,
        help="检测到平台额度/限流错误后的冷却分钟数（默认 30）",
    )
    parser.add_argument(
        "--quota-fail-n",
        type=int,
        default=10,
        help="连续多少次额度/限流失败触发冷却（默认 10；并发高时 1 批即触发）",
    )
    parser.add_argument("--max-retries", type=int, default=3, help="失败样本自动重试次数（默认 3）")
    parser.add_argument("--max-parse-retries", type=int, default=1, help="解析失败重试次数（默认 1）")
    parser.add_argument(
        "--balance",
        type=float,
        default=None,
        help='自动均衡多人占比（0-1，如 0.25）：txt 整体多人比例高于目标时，先以纯单人'
        "（probability=0）补充，直到整体比例降到目标后自动切换为该占比稳态运行。"
        "用于把含历史旧数据（约 50%% 多人）的输出文件逐步稀释到目标占比，无需手动改配置重启。",
    )
    parser.add_argument(
        "--balance-interval",
        type=float,
        default=60,
        help="--balance 模式下检查整体多人比例的间隔秒数（默认 60）",
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子（单条时生效）")
    parser.add_argument(
        "--v2-enhance",
        action="store_true",
        help="对 v1 额外调用一次 API，按 anima V2 规则精修为震撼美化版（version_2）",
    )
    args = parser.parse_args(argv)

    if args.count < 0:
        parser.error("--count 必须大于等于 0（0 表示无限循环）")
    if not args.api_config and not (args.api_key and args.api_base):
        parser.error("必须提供 --api-config 或 --api-key/--api-base")

    # ---- 合并配置（复用 cli 的配置合并逻辑）----
    build_args = argparse.Namespace(
        config=None,
        extra_requirements=None,
        max_rating=args.max_rating,
        min_tags=None,
        max_tags=None,
        character_json=None,
        theme_hint="",
        subject_control="",
        forced_tags="",
        forbidden_tags="",
        api_key=args.api_key,
        api_config=args.api_config,
        api_base=args.api_base,
        model=args.model,
    )
    (
        knowledge_sample_counts,
        deepseek_cfg,
        output_dir,
        focus_weights,
        max_rating,
        min_tags,
        max_tags,
        extra_requirements,
        extra_requirements_pool,
        character_whitelist,
        category_whitelists,
        character_pool,
        multi_character_cfg,
        min_r18_tags_per_sample,
        r18_instructions,
        r18_topic_control,
    ) = _build_config(build_args)
    api_key, api_base, model, profile_temperature = _resolve_api_profile(build_args)
    if "temperature" in _load_yaml_config(args.api_config):
        deepseek_cfg["temperature"] = _load_yaml_config(args.api_config).get("temperature")
    if "reasoning_effort" in _load_yaml_config(args.api_config):
        deepseek_cfg["reasoning_effort"] = _load_yaml_config(args.api_config).get(
            "reasoning_effort"
        )

    if args.seed is not None:
        random.seed(args.seed)

    output_path = args.output or os.path.join(output_dir, "opencode_prompts.jsonl")

    # ---- 加载数据源（与 cli.main 一致）----
    database = retrieval.load_tag_database(config.TAG_SOURCE_FILE)
    artist_blacklist = retrieval.build_artist_blacklist(
        config.ARTIST_BLACKLIST_FILES[0],
        config.ARTIST_BLACKLIST_FILES[1],
    )
    curated_tags = retrieval.load_curated_tags(config.CURATED_TAGS_FILE)
    knowledge_database = retrieval.load_knowledge_v1_database()
    print("正在预过滤知识库...")
    knowledge_database = retrieval.build_filtered_knowledge_database(
        knowledge_database,
        curated_tags,
        max_rating=max_rating,
    )
    print(f"知识库预过滤完成，共 {sum(len(v) for v in knowledge_database.values())} 条可用 tag。")

    forced_tags = [t.strip() for t in build_args.forced_tags.split(",") if t.strip()]
    forbidden_tags = [t.strip() for t in build_args.forbidden_tags.split(",") if t.strip()]

    # ---- 预算账本与输出句柄 ----
    ledger = BudgetLedger(args.ledger)
    if args.real_usage:
        ledger.apply_real_usage(args.real_usage)
    ledger.print_status()
    print(f"强制关闭推理（reasoning_effort=none），模型: {model}")

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    jsonl_handle = Path(output_path).open("a", encoding="utf-8")
    txt_handle = Path(str(Path(output_path).with_suffix(".txt"))).open("a", encoding="utf-8")

    # ---- 自动均衡（--balance）：整体多人占比高于目标时先纯单人补充，达标后切稳态 ----
    # 监控线程直接改写 multi_character_cfg["probability"]（每条任务抽样时读取），
    # 无需重启进程即可切换。
    balance_stop = threading.Event()
    if args.balance is not None:
        balance_target = min(1.0, max(0.0, args.balance))
        balance_txt = Path(str(Path(output_path).with_suffix(".txt")))

        def _balance_monitor() -> None:
            while not balance_stop.is_set():
                try:
                    ratio = _txt_multi_ratio(balance_txt)
                except Exception:  # noqa: BLE001
                    ratio = None
                if ratio is not None and ratio <= balance_target:
                    multi_character_cfg["probability"] = balance_target
                    print(
                        f"\n[自动均衡] 整体多人占比 {ratio:.1%} <= 目标 {balance_target:.0%}，"
                        f"已切换为 {balance_target:.0%} 多人稳态，继续生成。"
                    )
                    return
                balance_stop.wait(args.balance_interval)

        initial_ratio = _txt_multi_ratio(balance_txt)
        if initial_ratio > balance_target:
            multi_character_cfg["probability"] = 0.0
            print(
                f"[自动均衡] 当前整体多人占比 {initial_ratio:.1%} > 目标 {balance_target:.0%}，"
                "进入纯单人补充阶段（probability=0），达到目标后自动切换，无需手动干预。"
            )
            threading.Thread(target=_balance_monitor, daemon=True).start()
        else:
            multi_character_cfg["probability"] = balance_target
            print(
                f"[自动均衡] 当前整体多人占比 {initial_ratio:.1%} <= 目标 {balance_target:.0%}，"
                f"直接以 {balance_target:.0%} 多人稳态运行。"
            )

    v2_enhance = args.v2_enhance or _load_generation_config().get("v2_enhance", False)
    # 评级映射：r18 模式下用于识别抽样结果中的 r18 tag 以生成占位符。
    rating_map = retrieval._build_rating_map(curated_tags)
    write_lock = threading.Lock()

    def _sample_tasks(n: int, start_idx: int) -> list[dict[str, Any]]:
        """按批抽样组装 n 个任务，编号从 start_idx 开始（用于无限循环模式）。

        每条样本使用独立随机种子（``task_seed``），保证抽样结果可复现：
        调试时用 ``--seed <task_seed> --count 1`` 即可复现同一条提示词。
        """
        tasks: list[dict[str, Any]] = []
        for i in range(n):
            idx = start_idx + i
            # 单条且显式 --seed 时使用指定值，否则为每条生成独立种子。
            if args.count == 1 and args.seed is not None:
                task_seed = args.seed
            else:
                task_seed = random.randint(0, 2**32 - 1)
            # 重置随机状态，使本条抽样完全由 task_seed 决定。
            random.seed(task_seed)
            sampled = retrieval.sample_from_knowledge_v1(
                knowledge_database,
                knowledge_sample_counts,
                curated_tags,
                seed=None,  # 已由上方 random.seed(task_seed) 控制本条随机性
                max_rating=max_rating,
                character_whitelist=character_whitelist,
                category_whitelists=category_whitelists,
                character_pool=character_pool,
                pre_filtered=True,
                min_r18_tags=min_r18_tags_per_sample,
                r18_topic_control=r18_topic_control,
                multi_character_cfg=multi_character_cfg,
            )
            payload = assembler.build_prompt_payload(sampled, max_rating=max_rating)
            sampled_text = assembler.format_tags_for_llm(payload)

            # r18 模式：将 r18 tag 替换为占位符，避免 LLM 输出层拒绝露骨词；
            # 输出后在 _generate_one 中按映射还原真实 tag。
            r18_placeholder_map: dict[str, str] = {}
            if max_rating in ("r18", "r18g") and min_r18_tags_per_sample > 0:
                sampled_text, r18_placeholder_map = client.assign_r18_placeholders(
                    sampled_text, _collect_r18_tags(sampled, rating_map)
                )

            # 关闭双人/多人角色（multi_character.enabled=false）时强制按单人处理。
            is_multi = (
                multi_character_cfg.get("enabled", True)
                and _is_multi_character(sampled_text)
            )
            eff_min_tags, eff_max_tags, eff_focus_text = _resolve_sample_constraints(
                is_multi, min_tags, max_tags, focus_weights, multi_character_cfg
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
                probability = float(character_pool.get("use_core_clothing_probability", 0.5))
                clothing_strategy = (
                    "core_mixed" if random.random() < probability else "sampled_only"
                )
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

            if extra_requirements_pool.get("enabled", False):
                current_extra_requirements = sample_extra_requirements(extra_requirements_pool)
            else:
                current_extra_requirements = extra_requirements

            tasks.append(
                {
                    "idx": idx,
                    "seed": task_seed,
                    "sampled": sampled,
                    "sampled_text": sampled_text,
                    "character_tag": character_tag,
                    "character_pool_info": character_pool_info,
                    "safety": safety,
                    "extra_requirements": current_extra_requirements,
                    "min_tags": eff_min_tags,
                    "max_tags": eff_max_tags,
                    "theme_hint": build_args.theme_hint,
                    "focus_text": eff_focus_text,
                    "subject_control": build_args.subject_control,
                    "forced_tags": forced_tags,
                    "forbidden_tags": forbidden_tags,
                    "max_rating": max_rating,
                    "r18_instructions": r18_instructions,
                    "r18_placeholder_map": r18_placeholder_map,
                    "placeholder_meanings": (
                        client.build_placeholder_meanings(r18_placeholder_map)
                        if r18_placeholder_map
                        else None
                    ),
                    "temperature": deepseek_cfg.get("temperature", 0.7),
                    "max_tokens": deepseek_cfg.get("max_tokens", 2000),
                    "timeout": deepseek_cfg.get("timeout", 120),
                    "reasoning_effort": deepseek_cfg.get("reasoning_effort", "none"),
                }
            )
        return tasks

    def _worker(task: dict[str, Any]) -> dict[str, Any]:
        try:
            result = _generate_one(
                task=task,
                api_key=api_key,
                api_base=api_base,
                model=model,
                temperature=task["temperature"],
                max_tokens=task["max_tokens"],
                timeout=task["timeout"],
                max_parse_retries=args.max_parse_retries,
                artist_blacklist=artist_blacklist,
                database=database,
                ledger=ledger,
                v2_enhance=v2_enhance,
                reasoning_effort=task["reasoning_effort"],
            )
            return {"ok": True, "result": result, "task": task}
        except QuotaExceededError as exc:
            # 额度/限流错误单独标记，由主循环累计后触发冷却等待。
            return {"ok": False, "quota": True, "error": str(exc), "task": task}
        except Exception as exc:  # noqa: BLE001
            # 只记录错误类型用于结束汇总，运行中不打印详情（避免刷屏）。
            with write_lock:
                error_types[exc.__class__.__name__] += 1
            return {"ok": False, "quota": False, "error": str(exc), "task": task}

    def _flush_result(res: dict[str, Any]) -> None:
        """将一条成功结果写入 jsonl/txt（带写锁）。"""
        task = res["task"]
        with write_lock:
            record = _record_to_jsonl(
                res["result"], task["sampled"], False, task["focus_text"]
            )
            record["seed"] = task["seed"]
            jsonl_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            jsonl_handle.flush()
            # v2 已关闭，txt 侧车输出 version_1（原只写 version_2）。
            version_1 = res["result"].get("version_1", "")
            if version_1:
                txt_handle.write(version_1 + "\n")
                txt_handle.flush()

    # ---- 主循环：按批抽样 → 预算检查 → 冷却等待 → 继续 ----
    infinite = args.count <= 0  # count<=0 表示无限运行，直到手动中断
    if infinite:
        print("无限循环模式已启用（--count<=0），额度耗尽后自动冷却等待，Ctrl+C 停止。")
    executor = ThreadPoolExecutor(max_workers=args.workers)
    total_attempted = 0
    ok_count = 0
    fail_count = 0
    retry_count = 0
    total_cost = 0.0
    batch_size = max(args.workers * 2, 8)
    consecutive_fail_batches = 0
    start_time = time.time()
    recent_finish: deque[float] = deque()  # 完成时间戳（近 60s 滑动窗口速率）
    error_types: Counter[str] = Counter()  # 错误类型统计（运行中不打印，结束汇总）
    quota_total = 0  # 额度/限流失败累计（仅展示，不占普通失败计数）
    quota_held: list[dict[str, Any]] = []  # 额度失败任务，冷却后重新排队重试
    # 状态栏缓存：ledger.status()/avg_cost() 是对全部账本记录的 O(n) 全量扫描，
    # 随账本增长开销线性上涨，故每 0.5s 重算一次并缓存，避免每条完成时阻塞主调度线程。
    _last_ledger_refresh = 0.0
    _cached_ledger_status: list[dict[str, Any]] = []
    _cached_ledger_avg = 0.0
    _last_draw_time = 0.0

    def _render_status(cooldown_left: float = 0.0) -> str:
        """单行状态栏：运行时长 | 进度/完成 | 成功 | 已用金额 | 速度 |
        平均成本 | 预算窗口 | 预计剩余条数 | 重试 | 失败（行末）。"""
        nonlocal _last_ledger_refresh, _cached_ledger_status, _cached_ledger_avg
        elapsed = time.time() - start_time
        cutoff = time.time() - 60.0
        while recent_finish and recent_finish[0] < cutoff:
            recent_finish.popleft()
        speed = len(recent_finish) / 60.0 if recent_finish else 0.0
        done = ok_count + fail_count
        # ledger.status()/avg_cost() 为 O(n) 全量扫描，每 0.5s 重算一次并缓存
        now = time.time()
        if now - _last_ledger_refresh >= 0.5 or not _cached_ledger_status:
            _cached_ledger_status = ledger.status()
            _cached_ledger_avg = ledger.avg_cost()
            _last_ledger_refresh = now
        status = _cached_ledger_status
        avg = _cached_ledger_avg
        min_remaining = min(s["remaining"] for s in status)
        est_left = int(min_remaining / avg) if avg > 0 else 0
        windows = " ".join(f"{s['name']}{s['ratio'] * 100:.0f}%" for s in status)
        elapsed_str = (
            f"{int(elapsed // 3600):02d}:{int(elapsed % 3600 // 60):02d}:{int(elapsed % 60):02d}"
        )

        parts = [
            f"冷却中 剩 {cooldown_left / 60:.1f} 分" if cooldown_left > 0 else f"运行 {elapsed_str}",
        ]
        if infinite:
            parts.append(f"完成 {done}")
        elif args.count:
            parts.append(f"进度 {done}/{args.count} ({done / args.count * 100:.1f}%)")
        else:
            parts.append(f"完成 {done}")
        parts += [
            f"成功 {ok_count}",
            f"已用 ${total_cost:.4f}",
            f"速度 {speed:.1f} 条/s",
        ]
        if avg > 0:
            parts.append(f"均 ${avg:.6f}/条")
        if est_left > 0:
            parts.append(f"约剩 {est_left} 条")
        parts.append(f"预算 {windows}")
        if retry_count:
            parts.append(f"重试 {retry_count}")
        if quota_total:
            parts.append(f"限流 {quota_total}")
        parts.append(f"失败 {fail_count}")  # 行末：失败次数
        return " | ".join(parts)

    def _draw_status(cooldown_left: float = 0.0) -> None:
        """覆盖输出单行状态栏（\r），每 0.5s 最多重绘一次，不留多余行。"""
        nonlocal _last_draw_time
        now = time.time()
        if now - _last_draw_time < 0.5:
            return
        _last_draw_time = now
        sys.stdout.write("\r" + _render_status(cooldown_left).ljust(100))
        sys.stdout.flush()

    def _wait_cooldown() -> None:
        """预算达到阈值时冷却等待；等待期间状态栏实时刷新剩余时间。"""
        while not ledger.can_proceed(args.limit_ratio):
            wait = ledger.cooldown_seconds(args.limit_ratio)
            if wait <= 0:
                wait = 60
            print(f"\n预算窗口已达到阈值，冷却等待约 {wait / 60:.1f} 分钟...")
            waited = 0
            while waited < wait:
                time.sleep(min(10, wait - waited))
                waited += 10
                _draw_status(cooldown_left=max(wait - waited, 0.0))
                if ledger.can_proceed(args.limit_ratio):
                    print("\n预算已恢复，继续生成。")
                    return
        print("\n预算已恢复，继续生成。")

    def _wait_quota_cooldown() -> None:
        """平台额度/限流错误触发冷却；按 --quota-cooldown 分钟等待后重试暂缓任务。"""
        wait = float(args.quota_cooldown) * 60.0
        print(
            f"\n平台返回额度/限流错误（本波 {quota_total} 次），"
            f"冷却等待约 {wait / 60:.1f} 分钟，之后自动重试..."
        )
        waited = 0
        while waited < wait:
            time.sleep(min(10, wait - waited))
            waited += 10
            _draw_status(cooldown_left=max(wait - waited, 0.0))
        print("\n冷却结束，继续生成。")

    # ---- 滑动窗口调度回调（_dispatch_batch 完成时回调更新计数/写盘/状态栏）----
    def _on_success(res: dict[str, Any]) -> None:
        nonlocal ok_count, total_cost
        _flush_result(res)
        ok_count += 1
        total_cost += res["result"].get("cost", 0.0)

    def _on_quota() -> None:
        nonlocal quota_total
        quota_total += 1

    def _on_retry() -> None:
        nonlocal retry_count
        retry_count += 1

    def _on_fail() -> None:
        nonlocal fail_count
        fail_count += 1

    def _on_report() -> None:
        recent_finish.append(time.time())
        _draw_status()

    def _budget_check() -> bool:
        return ledger.can_proceed(args.limit_ratio)

    try:
        while infinite or total_attempted < args.count:
            # 预算检查：超额则冷却等待后继续（仅 --ledger-guard 开启时生效；
            # 默认账本仅作参考展示，实际止损由平台额度/限流错误冷却承担）
            if args.ledger_guard and not ledger.can_proceed(args.limit_ratio):
                _wait_cooldown()
                continue

            # 确定本批任务数
            if infinite:
                batch_n = batch_size
            else:
                batch_n = min(batch_size, args.count - total_attempted)
            tasks = _sample_tasks(batch_n, total_attempted)
            if not tasks:
                break

            stats = _dispatch_batch(
                executor=executor,
                tasks=tasks,
                worker=_worker,
                max_workers=args.workers,
                max_retries=args.max_retries,
                quota_fail_n=args.quota_fail_n,
                on_success=_on_success,
                on_quota=_on_quota,
                on_retry=_on_retry,
                on_fail=_on_fail,
                on_report=_on_report,
                wait_quota_cooldown=_wait_quota_cooldown,
                budget_check=(_budget_check if args.ledger_guard else None),
                wait_budget_cooldown=_wait_cooldown if args.ledger_guard else None,
                quota_held=quota_held,
            )

            total_attempted += batch_n
            if stats["batch_fail"] >= batch_n:  # 整批全失败，连续计数以提前止损
                consecutive_fail_batches += 1
            else:
                consecutive_fail_batches = 0
            if consecutive_fail_batches >= 5:
                print("\n连续 5 批全部失败，疑似 API 不可用，停止运行。")
                break
    except KeyboardInterrupt:
        print("\n收到中断，正在保存已完成但未写入的结果...")
        print(f"中断后共成功 {ok_count} 条。")
    finally:
        balance_stop.set()
        executor.shutdown(wait=False, cancel_futures=True)
        jsonl_handle.close()
        txt_handle.close()

    print()
    print(
        f"\n运行结束: 成功 {ok_count} 条, 失败 {fail_count} 条, 重试 {retry_count} 次, "
        f"本次消耗 ${total_cost:.4f}"
    )
    if error_types:
        detail = ", ".join(f"{name} x{n}" for name, n in error_types.most_common())
        print(f"错误类型统计: {detail}")
    ledger.print_status()
    print(f"结果已追加保存到 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
