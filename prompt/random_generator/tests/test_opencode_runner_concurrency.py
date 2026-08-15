"""滑动窗口并发调度 `_dispatch_batch` 单元测试（opencode_runner.py）。

覆盖范围：
- 全部成功：统计与回调计数正确（test_all_success_stats）
- 滑动窗口并发上限：任意时刻在途任务数峰值 <= max_workers
  （test_concurrency_capped_at_max_workers）
- 慢任务不阻塞流水线：滑动窗口下所有快任务先于慢任务完成
  （test_slow_task_does_not_block_pipeline）
- 普通失败重试：先失败后成功 / 重试耗尽计失败
  （test_retry_then_success、test_retry_exhausted_counts_fail）
- quota 冷却：累计达 quota_fail_n 后调用冷却并把暂存任务排回队列
  （test_quota_cooldown_requeues）；尾部不足阈值的 quota 任务不丢失
  （test_quota_below_threshold_tail_is_not_lost，回归 _dispatch_batch 缺陷修复）
- 预算守门：按周期调用 budget_check 与触发冷却
  （test_budget_check_periodic、test_budget_check_triggers_cooldown）
- 空任务短路：返回全 0 统计、不调用任何回调（test_empty_tasks）
- 单 worker 退化为串行仍正确（test_single_worker_serial）

实现：真实 ThreadPoolExecutor + mock worker（不碰真实 API），依赖仅标准库；
每个测试耗时控制在亚秒级（总运行远小于 10 秒）。

运行方式（项目根目录 e:\\code\\Anima\\anima-rag-knowledge）：
    python -m unittest prompt.random_generator.tests.test_opencode_runner_concurrency -v
"""

from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from opencode_runner import _dispatch_batch

# ---------------------------------------------------------------------------
# mock worker（均为纯内存操作，无真实 API 调用）
# ---------------------------------------------------------------------------


def _success_worker(task: dict[str, Any]) -> dict[str, Any]:
    """mock worker：永远成功。"""
    return {"ok": True, "result": {"value": task["idx"]}, "task": task}


def _retry_once_then_success_worker(task: dict[str, Any]) -> dict[str, Any]:
    """mock worker：每个任务第一次普通失败、第二次成功。"""
    attempts = task.get("_attempts", 0) + 1
    task["_attempts"] = attempts
    if attempts == 1:
        return {"ok": False, "quota": False, "error": "boom", "task": task}
    return {"ok": True, "result": {"value": task["idx"]}, "task": task}


def _always_fail_worker(task: dict[str, Any]) -> dict[str, Any]:
    """mock worker：永远普通失败。"""
    return {"ok": False, "quota": False, "error": "boom", "task": task}


def _quota_then_success_worker(task: dict[str, Any]) -> dict[str, Any]:
    """mock worker：每个任务第一次 quota 失败、第二次成功。"""
    attempts = task.get("_attempts", 0) + 1
    task["_attempts"] = attempts
    if attempts == 1:
        return {"ok": False, "quota": True, "task": task}
    return {"ok": True, "result": {"value": task["idx"]}, "task": task}


class DispatchCase(unittest.TestCase):
    """_dispatch_batch 通用调用辅助：真实线程池 + 回调调用计数。"""

    def _dispatch(
        self,
        tasks: list[dict[str, Any]],
        worker: Any,
        max_workers: int = 4,
        max_retries: int = 3,
        quota_fail_n: int = 10,
        budget_check: Any = None,
        wait_budget_cooldown: Any = None,
        quota_held: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, int], dict[str, int]]:
        """调用 _dispatch_batch 并返回 (stats, 各回调调用次数)。"""
        executor = ThreadPoolExecutor(max_workers=max_workers)
        calls: dict[str, int] = {
            "success": 0,
            "quota": 0,
            "retry": 0,
            "fail": 0,
            "report": 0,
            "quota_cooldown": 0,
        }

        def _inc(key: str) -> Any:
            def _f(*args: Any) -> None:
                calls[key] += 1

            return _f

        try:
            stats = _dispatch_batch(
                executor=executor,
                tasks=tasks,
                worker=worker,
                max_workers=max_workers,
                max_retries=max_retries,
                quota_fail_n=quota_fail_n,
                on_success=_inc("success"),
                on_quota=_inc("quota"),
                on_retry=_inc("retry"),
                on_fail=_inc("fail"),
                on_report=_inc("report"),
                wait_quota_cooldown=_inc("quota_cooldown"),
                budget_check=budget_check,
                wait_budget_cooldown=wait_budget_cooldown,
                quota_held=quota_held,
            )
        finally:
            executor.shutdown(wait=True)
        return stats, calls

    @staticmethod
    def _tasks(n: int) -> list[dict[str, Any]]:
        return [{"idx": i} for i in range(n)]


class TestAllSuccessStats(DispatchCase):
    """全成功路径：统计与回调计数。"""

    def test_all_success_stats(self) -> None:
        """N=20、workers=4 全部成功：ok=20，其余统计为 0，on_success 恰好 20 次。"""
        stats, calls = self._dispatch(self._tasks(20), _success_worker, max_workers=4)
        self.assertEqual(stats["ok"], 20, f"成功数异常: {stats}")
        self.assertEqual(stats["fail"], 0, f"不应有失败: {stats}")
        self.assertEqual(stats["retry"], 0, f"不应有重试: {stats}")
        self.assertEqual(stats["quota_total"], 0, f"不应有 quota 失败: {stats}")
        self.assertEqual(stats["batch_fail"], 0, f"不应有整批失败: {stats}")
        self.assertEqual(calls["success"], 20, f"on_success 应恰好 20 次: {calls}")
        self.assertEqual(calls["report"], 20, "on_report 应每条结果调用一次")
        self.assertEqual(calls["quota_cooldown"], 0, "无 quota 失败不应触发冷却")


class TestConcurrencyWindow(DispatchCase):
    """滑动窗口核心：在途任务数上限与慢任务不拖流水线。"""

    def test_concurrency_capped_at_max_workers(self) -> None:
        """N=50、workers=8：任意时刻在途任务数峰值 <= 8，全部成功。"""
        lock = threading.Lock()
        active = [0]
        peak = [0]

        def worker(task: dict[str, Any]) -> dict[str, Any]:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.001)
            with lock:
                active[0] -= 1
            return {"ok": True, "result": {"value": task["idx"]}, "task": task}

        stats, _ = self._dispatch(self._tasks(50), worker, max_workers=8)
        self.assertLessEqual(peak[0], 8, f"并发峰值超过 max_workers: {peak[0]}")
        self.assertEqual(stats["ok"], 50, f"应全部成功: {stats}")
        self.assertEqual(stats["fail"] + stats["retry"], 0, f"不应有失败/重试: {stats}")

    def test_slow_task_does_not_block_pipeline(self) -> None:
        """workers=3：慢任务（0.3s）不拖住快任务（0.005s），快任务全部先完成。

        若仍是旧「波次屏障」调度，快任务须等慢任务所在波次整体结束才提交，
        其完成时间会晚于慢任务；滑动窗口下快任务一完成立即补提交，全部先完成。
        """
        n = 9
        slow_idx = 0
        timestamps = [0.0] * n

        def worker(task: dict[str, Any]) -> dict[str, Any]:
            if task["idx"] == slow_idx:
                time.sleep(0.3)
            else:
                time.sleep(0.005)
            timestamps[task["idx"]] = time.monotonic()
            return {"ok": True, "result": {"value": task["idx"]}, "task": task}

        stats, _ = self._dispatch(self._tasks(n), worker, max_workers=3)
        self.assertEqual(stats["ok"], n, f"应全部成功: {stats}")
        slow_time = timestamps[slow_idx]
        fast_times = [t for i, t in enumerate(timestamps) if i != slow_idx]
        self.assertTrue(fast_times, "应存在快任务")
        self.assertLess(
            max(fast_times),
            slow_time,
            f"快任务被慢任务拖住: 快任务最晚 {max(fast_times):.4f}s, 慢任务 {slow_time:.4f}s",
        )

    def test_single_worker_serial(self) -> None:
        """workers=1 退化为串行：全部成功且峰值并发 =1。"""
        lock = threading.Lock()
        active = [0]
        peak = [0]

        def worker(task: dict[str, Any]) -> dict[str, Any]:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.001)
            with lock:
                active[0] -= 1
            return {"ok": True, "result": {"value": task["idx"]}, "task": task}

        stats, _ = self._dispatch(self._tasks(5), worker, max_workers=1)
        self.assertEqual(stats["ok"], 5, f"应全部成功: {stats}")
        self.assertEqual(peak[0], 1, f"单 worker 峰值并发应为 1: {peak[0]}")


class TestRetryBehavior(DispatchCase):
    """普通失败重试路径。"""

    def test_retry_then_success(self) -> None:
        """每个任务第一次普通失败、第二次成功（max_retries=3、N=6）：retry=6、ok=6。"""
        stats, calls = self._dispatch(
            self._tasks(6),
            _retry_once_then_success_worker,
            max_workers=4,
            max_retries=3,
        )
        self.assertEqual(stats["ok"], 6, f"应全部重试成功: {stats}")
        self.assertEqual(stats["retry"], 6, f"每个任务应重试 1 次: {stats}")
        self.assertEqual(stats["fail"], 0, f"不应有最终失败: {stats}")
        self.assertEqual(stats["batch_fail"], 0, f"不应有整批失败: {stats}")
        self.assertEqual(calls["retry"], 6, f"on_retry 应恰好 6 次: {calls}")
        self.assertEqual(calls["success"], 6, f"on_success 应恰好 6 次: {calls}")

    def test_retry_exhausted_counts_fail(self) -> None:
        """永远普通失败、max_retries=2、N=4：每个任务重试 2 次后判失败。"""
        stats, calls = self._dispatch(
            self._tasks(4),
            _always_fail_worker,
            max_workers=2,
            max_retries=2,
        )
        self.assertEqual(stats["fail"], 4, f"应全部失败: {stats}")
        self.assertEqual(stats["batch_fail"], 4, f"应全部计入整批失败: {stats}")
        self.assertEqual(stats["retry"], 8, f"每个任务应重试 2 次: {stats}")
        self.assertEqual(stats["ok"], 0, f"不应有成功: {stats}")
        self.assertEqual(calls["fail"], 4, f"on_fail 应恰好 4 次: {calls}")
        self.assertEqual(calls["retry"], 8, f"on_retry 应恰好 8 次: {calls}")


class TestQuotaCooldown(DispatchCase):
    """quota 失败累计阈值触发冷却并排回暂存任务。"""

    def test_quota_cooldown_requeues(self) -> None:
        """每个任务第一次 quota 失败、第二次成功：冷却后排回暂存任务全部重试成功。

        N=4、workers=2、quota_fail_n=4：4 个任务全部 quota 失败恰好累计达阈值，
        触发一次冷却并把暂存任务（quota_held）排回队列，重试后全部成功。
        """
        quota_held: list[dict[str, Any]] = []
        stats, calls = self._dispatch(
            self._tasks(4),
            _quota_then_success_worker,
            max_workers=2,
            max_retries=3,
            quota_fail_n=4,
            quota_held=quota_held,
        )
        self.assertEqual(stats["ok"], 4, f"冷却排回后应全部成功: {stats}")
        self.assertEqual(stats["quota_total"], 4, f"每个任务 quota 失败 1 次: {stats}")
        self.assertEqual(stats["fail"], 0, f"quota 失败不应计入普通失败: {stats}")
        self.assertEqual(stats["retry"], 0, f"quota 失败不应计入普通重试: {stats}")
        self.assertGreaterEqual(
            calls["quota_cooldown"], 1,
            f"达到 quota_fail_n 应触发冷却: {calls}",
        )
        self.assertEqual(calls["quota"], 4, f"on_quota 应恰好 4 次: {calls}")
        self.assertEqual(quota_held, [], f"外部暂存列表最终应排空: {quota_held}")


    def test_quota_below_threshold_tail_is_not_lost(self) -> None:
        """quota_fail_n=2 < N=4：尾部不足阈值的 quota 任务不得丢失（回归缺陷修复）。

        滑动窗口下任务交错在途，若某轮 quota 失败数不足 quota_fail_n，任务会
        暂存于 quota_held；队列与在途均空时须把它们排回继续重试（已修复），
        否则任务随批次结束丢失、永不重试。修复前本用例 ok=3 而非 4。
        """
        quota_held: list[dict[str, Any]] = []
        stats, calls = self._dispatch(
            self._tasks(4),
            _quota_then_success_worker,
            max_workers=2,
            max_retries=3,
            quota_fail_n=2,
            quota_held=quota_held,
        )
        self.assertEqual(stats["ok"], 4, f"尾部 quota 任务不应丢失: {stats}")
        self.assertEqual(stats["quota_total"], 4, f"每个任务 quota 失败 1 次: {stats}")
        self.assertEqual(stats["fail"], 0, f"quota 失败不应计入普通失败: {stats}")
        self.assertEqual(quota_held, [], f"外部暂存列表最终应排空: {quota_held}")


class TestBudgetGuard(DispatchCase):
    """预算守门：周期性检查与触发冷却。"""

    def test_budget_check_periodic(self) -> None:
        """budget_check 每完成 max_workers 条调用一次（N=10、workers=4 → 2~4 次）。"""
        budget_checks = [0]
        cooldown_calls = [0]

        def budget_check() -> bool:
            budget_checks[0] += 1
            return True

        def wait_budget_cooldown() -> None:
            cooldown_calls[0] += 1

        stats, _ = self._dispatch(
            self._tasks(10),
            _success_worker,
            max_workers=4,
            budget_check=budget_check,
            wait_budget_cooldown=wait_budget_cooldown,
        )
        self.assertGreaterEqual(
            budget_checks[0], 2, f"budget_check 调用过少: {budget_checks[0]}"
        )
        self.assertLessEqual(
            budget_checks[0], 4, f"budget_check 调用过多: {budget_checks[0]}"
        )
        self.assertEqual(cooldown_calls[0], 0, "预算充足时不应触发冷却")
        self.assertEqual(stats["ok"], 10, f"应全部成功: {stats}")

    def test_budget_check_triggers_cooldown(self) -> None:
        """budget_check 首次返回 False：触发 wait_budget_cooldown 且任务仍全部成功。"""
        budget_checks = [0]
        cooldown_calls = [0]

        def budget_check() -> bool:
            budget_checks[0] += 1
            return budget_checks[0] > 1  # 仅首次 False，其余 True

        def wait_budget_cooldown() -> None:
            cooldown_calls[0] += 1

        stats, _ = self._dispatch(
            self._tasks(10),
            _success_worker,
            max_workers=4,
            budget_check=budget_check,
            wait_budget_cooldown=wait_budget_cooldown,
        )
        self.assertGreaterEqual(
            cooldown_calls[0], 1, f"预算不通过应触发冷却: {cooldown_calls}"
        )
        self.assertEqual(stats["ok"], 10, f"冷却后任务仍应全部成功: {stats}")


class TestEmptyTasks(DispatchCase):
    """空任务短路：返回全 0、零回调。"""

    def test_empty_tasks(self) -> None:
        """tasks=[]：stats 全 0，所有回调零调用。"""
        stats, calls = self._dispatch([], _success_worker)
        self.assertEqual(
            stats,
            {"ok": 0, "fail": 0, "retry": 0, "quota_total": 0, "batch_fail": 0},
            f"空任务统计应全 0: {stats}",
        )
        self.assertEqual(
            calls,
            {
                "success": 0,
                "quota": 0,
                "retry": 0,
                "fail": 0,
                "report": 0,
                "quota_cooldown": 0,
            },
            f"空任务不应调用任何回调: {calls}",
        )


if __name__ == "__main__":
    unittest.main()
