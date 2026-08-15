"""配置项应用测试：验证各类配置是否被正确应用到完整 prompt 生成链路。

覆盖范围：
- extra_requirements_pool：互斥组至多抽一、权重分布、skip_probability、可选特效概率、渲染注入
- multi_character：tag_count_bonus（min/max tags 加成）与 focus_character_bonus（character 权重加成）
- character_pool：多角色场景下 Character N 块与核心特征注入
- 完整 dry-run 链路：cli.main 渲染出的完整 user prompt 包含上述配置产物

运行方式（项目根目录）：
    python -m unittest prompt.random_generator.tests.test_config_application -v
"""

from __future__ import annotations

import contextlib
import io
import random
import unittest
from collections import Counter

import yaml

from prompt.random_generator import assembler, client, config, retrieval
from prompt.random_generator import cli


def _load_pool_from_config() -> dict:
    """从 generation_config.yaml 读取 extra_requirements_pool 真实配置。"""
    with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg["extra_requirements_pool"]


class TestExtraRequirementsPool(unittest.TestCase):
    """extra_requirements_pool 配置解析与抽样逻辑。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = _load_pool_from_config()

    def test_pool_config_loaded(self) -> None:
        """配置应从 generation_config.yaml 正确解析且启用。"""
        self.assertTrue(self.pool["enabled"])
        self.assertGreaterEqual(len(self.pool["mutex_groups"]), 2)
        self.assertIsInstance(self.pool.get("optional_items"), list)

    def test_mutex_group_selects_at_most_one(self) -> None:
        """每组最多抽取 1 条，同组两条不会同时出现。"""
        random.seed(2026)
        group_texts = [
            {item["text"] for item in group.get("items", [])}
            for group in self.pool["mutex_groups"]
        ]
        for _ in range(3000):
            text = cli.sample_extra_requirements(self.pool)
            for texts in group_texts:
                present = [line for line in text.splitlines() if line in texts]
                self.assertLessEqual(len(present), 1, f"同组抽到多条: {present}")

    def test_weight_distribution(self) -> None:
        """权重应影响抽样分布：仅在组被抽中时，组内条目按权重分布。

        A 组带 skip_probability，因此在整轮抽样中整体出现比例会按 1-skip 稀释；
        组内相对分布（weight / 权重和）不应受影响。
        """
        random.seed(2026)
        group_a = self.pool["mutex_groups"][0]
        items_a = group_a["items"]
        skip = float(group_a.get("skip_probability", 0.0))
        weight_total = sum(item["weight"] for item in items_a)
        counts: Counter[str] = Counter()
        n = 20000
        for _ in range(n):
            text = cli.sample_extra_requirements(self.pool)
            present = [item["text"] for item in items_a if item["text"] in text]
            if len(present) == 1:
                counts[present[0]] += 1
        appeared_total = sum(counts.values())
        self.assertAlmostEqual(
            appeared_total / n,
            1 - skip,
            delta=0.03,
            msg=f"A 组整体出现比例异常: {appeared_total / n:.3f} vs {1 - skip:.3f}",
        )
        for item in items_a:
            expected = item["weight"] / weight_total
            actual = counts.get(item["text"], 0) / appeared_total
            self.assertAlmostEqual(
                actual,
                expected,
                delta=0.03,
                msg=f"权重 {item['weight']} 的抽样比例异常: {actual:.3f} vs {expected:.3f}",
            )

    def test_skip_probability_effective(self) -> None:
        """带 skip_probability 的组应按概率整组跳过。"""
        random.seed(2026)
        group_c = self.pool["mutex_groups"][2]
        skip = float(group_c.get("skip_probability", 0.0))
        items = group_c["items"]
        n = 20000
        appeared = 0
        for _ in range(n):
            text = cli.sample_extra_requirements(self.pool)
            if any(item["text"] in text for item in items):
                appeared += 1
        self.assertAlmostEqual(
            appeared / n,
            1 - skip,
            delta=0.05,
            msg=f"skip_probability={skip} 但出现比例 {appeared / n:.3f}",
        )

    def test_optional_items_independent_probability(self) -> None:
        """optional_items 每项按自身 probability 独立出现。"""
        random.seed(2026)
        optional = self.pool["optional_items"]
        self.assertTrue(optional, "optional_items 不应为空")
        n = 20000
        for item in optional:
            prob = float(item["probability"])
            appeared = sum(
                1
                for _ in range(n)
                if item["text"]
                in cli.sample_extra_requirements(self.pool)
            )
            self.assertAlmostEqual(
                appeared / n,
                prob,
                delta=0.05,
                msg=f"optional {item['text']} 出现比例 {appeared / n:.3f} vs {prob}",
            )

    def test_all_entries_reachable(self) -> None:
        """所有条目在大量抽样下都应能被抽到（配置无死条目）。"""
        random.seed(7)
        seen: set[str] = set()
        for _ in range(5000):
            seen.update(cli.sample_extra_requirements(self.pool).splitlines())
        all_texts = {
            item["text"]
            for group in self.pool["mutex_groups"]
            for item in group.get("items", [])
        } | {
            item["text"] for item in self.pool.get("optional_items", [])
        }
        missing = all_texts - seen
        self.assertEqual(missing, set(), f"以下条目从未被抽到: {missing}")

    def test_empty_pool_returns_empty(self) -> None:
        """空池或未启用时返回空字符串。"""
        self.assertEqual(cli.sample_extra_requirements({}), "")
        self.assertEqual(cli.sample_extra_requirements({"enabled": False}), "")

    def test_item_exclusion_prevents_conflicting_pairs(self) -> None:
        """条目级互斥：excludes 声明的条目对不应同时出现。"""
        random.seed(2026)
        text_to_excludes: dict[str, list[str]] = {}
        for group in self.pool["mutex_groups"]:
            for item in group.get("items", []):
                if item.get("excludes"):
                    text_to_excludes[item["text"]] = item["excludes"]
        self.assertTrue(text_to_excludes, "配置中应存在 excludes 互斥声明")

        for _ in range(5000):
            text = cli.sample_extra_requirements(self.pool)
            for source, excludes in text_to_excludes.items():
                if source not in text:
                    continue
                for target in excludes:
                    self.assertNotIn(
                        target,
                        text,
                        f"互斥条目同时出现: {source!r} 与 {target!r}",
                    )

    def test_exclusion_allows_fallback_within_group(self) -> None:
        """互斥候选被过滤后，组内仍应从剩余条目中加权抽取。"""
        random.seed(2026)
        pool = {
            "enabled": True,
            "mutex_groups": [
                {"items": [{"text": "a", "weight": 1}, {"text": "b", "weight": 1}]},
                {
                    "items": [
                        {"text": "x", "weight": 1, "excludes": ["a", "b"]},
                        {"text": "y", "weight": 1},
                    ]
                },
            ],
        }
        seen_y_with_a_or_b = 0
        n = 5000
        for _ in range(n):
            text = cli.sample_extra_requirements(pool)
            if "a" in text or "b" in text:
                self.assertNotIn("x", text, "x 不应与 a/b 同时出现")
                if "y" in text:
                    seen_y_with_a_or_b += 1
        self.assertGreater(seen_y_with_a_or_b, 0, "组内应回退到 y")

    def test_exclusion_all_group_candidates_blocked_skips_group(self) -> None:
        """组内全部候选与已选条目互斥时，整组跳过。"""
        random.seed(2026)
        pool = {
            "enabled": True,
            "mutex_groups": [
                {"items": [{"text": "a", "weight": 1}]},
                {
                    "items": [
                        {"text": "x", "weight": 1, "excludes": ["a"]},
                        {"text": "y", "weight": 1, "excludes": ["a"]},
                    ]
                },
            ],
        }
        for _ in range(300):
            text = cli.sample_extra_requirements(pool)
            if "a" in text:
                self.assertNotIn("x", text)
                self.assertNotIn("y", text)


class TestExtraRequirementsInjection(unittest.TestCase):
    """extra_requirements 渲染注入 user prompt。"""

    def test_requirements_injected_into_user_prompt(self) -> None:
        """抽样得到的每条要求都应出现在「Additional requirements:」区块。"""
        pool = _load_pool_from_config()
        random.seed(42)
        for _ in range(30):
            req = cli.sample_extra_requirements(pool)
            if not req:
                continue
            prompt = client.render_user_prompt(
                sampled_tags_text="【人数与性别】\n1girl\n",
                safety="safe",
                min_tags=50,
                max_tags=75,
                max_rating="r15",
                extra_requirements=req,
            )
            self.assertIn("Additional requirements:", prompt)
            for line in req.splitlines():
                self.assertIn(line, prompt)

    def test_no_section_when_empty(self) -> None:
        """extra_requirements 为空时不渲染 Additional requirements 区块。"""
        prompt = client.render_user_prompt(
            sampled_tags_text="【人数与性别】\n1girl\n",
            safety="safe",
            min_tags=50,
            max_tags=75,
            extra_requirements="",
        )
        self.assertNotIn("Additional requirements:", prompt)


class TestMultiCharacterConstraints(unittest.TestCase):
    """多角色触发的 tag 数量加成与 focus 权重调整。"""

    FOCUS = {"character": 40, "background": 40, "other": 20}
    MULTI_CFG = {"tag_count_bonus": 20, "focus_character_bonus": 10}

    def test_multi_character_tag_count_bonus(self) -> None:
        """多角色时 min/max tags 各加 tag_count_bonus。"""
        eff_min, eff_max, _ = cli._resolve_sample_constraints(
            True, 50, 75, self.FOCUS, self.MULTI_CFG
        )
        self.assertEqual(eff_min, 70)
        self.assertEqual(eff_max, 95)

    def test_multi_character_focus_adjustment(self) -> None:
        """character +10 且由 background/other 按比例扣减。"""
        _, _, focus_text = cli._resolve_sample_constraints(
            True, 50, 75, self.FOCUS, self.MULTI_CFG
        )
        self.assertIn("character ~50%", focus_text)
        self.assertIn("background ~33%", focus_text)
        self.assertIn("other ~17%", focus_text)

    def test_single_character_no_adjustment(self) -> None:
        """单角色时不触发任何加成。"""
        eff_min, eff_max, focus_text = cli._resolve_sample_constraints(
            False, 50, 75, self.FOCUS, self.MULTI_CFG
        )
        self.assertEqual((eff_min, eff_max), (50, 75))
        self.assertIn("character ~40%", focus_text)


class TestFullPromptGeneration(unittest.TestCase):
    """集成测试：真实抽样 + 渲染完整 user prompt，验证配置产物落地。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.database = retrieval.load_knowledge_v1_database()
        cls.curated_tags = retrieval.load_curated_tags(config.CURATED_TAGS_FILE)
        cls.database = retrieval.build_filtered_knowledge_database(
            cls.database, cls.curated_tags, max_rating="r15"
        )
        # 合并真实 character_pool 配置（generation_config.yaml 覆盖默认值）。
        with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
            gen_cfg = yaml.safe_load(f)
        cls.character_pool = dict(config.DEFAULT_CHARACTER_POOL)
        cls.character_pool.update(gen_cfg.get("character_pool", {}))

    def _sample_until_2girls_with_pool(self, max_attempts: int = 60) -> dict:
        """抽样直到 2girls 且角色池提供 2 个角色。"""
        random.seed(20260803)
        for _ in range(max_attempts):
            sampled = retrieval.sample_from_knowledge_v1(
                self.database,
                dict(config.DEFAULT_KNOWLEDGE_SAMPLE_COUNTS),
                self.curated_tags,
                max_rating="r15",
                character_whitelist=config.DEFAULT_CHARACTER_WHITELIST,
                category_whitelists={
                    "enabled": True,
                    "pools": {"count_gender": ["2girls"]},
                },
                character_pool=self.character_pool,
                pre_filtered=True,
            )
            chars = sampled.get("character_series") or []
            pool_chars = [c for c in chars if c.get("source") == "character_pool"]
            if len(pool_chars) >= 2:
                return sampled
        self.fail("未能抽样到含 2 个角色池角色的 2girls 场景")

    def test_full_prompt_contains_configured_products(self) -> None:
        """完整渲染的 user prompt 应包含 extra_requirements、Character 块与多角色指令。"""
        sampled = self._sample_until_2girls_with_pool()
        payload = assembler.build_prompt_payload(sampled)
        sampled_text = assembler.format_tags_for_llm(payload)
        self.assertTrue(cli._is_multi_character(sampled_text))

        character_tag = sampled["character_series"][0]["tag"]
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
            "clothing_strategy": "core_mixed",
        }

        pool = _load_pool_from_config()
        random.seed(1)
        req = cli.sample_extra_requirements(pool)

        eff_min, eff_max, eff_focus = cli._resolve_sample_constraints(
            True, 50, 75, {"character": 40, "background": 40, "other": 20},
            {"tag_count_bonus": 20, "focus_character_bonus": 10},
        )

        prompt = client.render_user_prompt(
            sampled_tags_text=sampled_text,
            safety=cli._determine_safety(sampled),
            min_tags=eff_min,
            max_tags=eff_max,
            focus_text=eff_focus,
            character_tag=character_tag,
            max_rating="r15",
            extra_requirements=req,
            character_pool_info=character_pool_info,
        )

        # extra_requirements 注入
        self.assertIn("Additional requirements:", prompt)
        for line in req.splitlines():
            self.assertIn(line, prompt)
        # 多角色指令与 tag 区间
        self.assertIn("Multi-character reminder", prompt)
        self.assertIn("at least", prompt)
        # Character 分离块
        self.assertIn("--- Character 1 ---", prompt)
        self.assertIn("--- Character 2 ---", prompt)
        # 角色核心特征注入（两条角色的 name 均在 Character 块）
        for c in character_pool_info["characters"]:
            self.assertIn(c["tag"], prompt)

    def test_cli_dry_run_integrates_config(self) -> None:
        """cli.main dry-run 完整链路：输出中包含额外要求注入与渲染结果。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = cli.main(["generate", "--dry-run", "--count", "3"])
        self.assertEqual(exit_code, 0)
        out = buf.getvalue()
        self.assertIn("渲染后的用户提示词：", out)
        self.assertIn("Additional requirements:", out)


if __name__ == "__main__":
    unittest.main()
