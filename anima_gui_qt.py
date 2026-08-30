#!/usr/bin/env python3
"""Anima 随机提示词生成器 - PySide6 桌面版入口。

开发运行：python anima_gui_qt.py
打包：python build_exe_qt.py
自检：python anima_gui_qt.py --self-test
"""
import os
import sys


def _self_test() -> int:
    """加载全部资源并验证核心模块（无头模式），写结果文件。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    lines: list[str] = []

    def _out(m: str) -> None:
        lines.append(m)

    try:
        from prompt.random_generator import config_presets, gui_engine, yaml_comments
        from prompt.random_generator import config
        from prompt.random_generator.gui_engine import GenConfig
        from prompt.random_generator.config_merge import deep_merge
        import yaml

        # 资源加载 + 预览
        logs: list[str] = []
        res = gui_engine.load_resources(
            progress=lambda m: logs.append(m), max_rating="r15"
        )
        kb = res["knowledge_database"]
        _out(f"[self-test] 知识库: {len(kb)} 类, 共 {sum(len(v) for v in kb.values())} 条")
        cfg = GenConfig(max_rating="r15", count=1, seed=12345, min_tags=50, max_tags=75)
        pv = gui_engine.preview(res, cfg)
        _out(f"[self-test] 预览 seed={pv['seed']} 渲染长度={len(pv['user_prompt'])}")

        # 帮助 100% 覆盖
        help_map = yaml_comments.build_help_map(config.GENERATION_CONFIG_FILE)
        with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
            gen_cfg = yaml.safe_load(f) or {}

        def _leaves(data, prefix=""):
            out = []
            for k, v in data.items():
                p = f"{prefix}.{k}" if prefix else k
                if isinstance(v, dict):
                    out.extend(_leaves(v, p))
                else:
                    out.append((p, v))
            return out

        no_help = [
            p for p, v in _leaves(gen_cfg)
            if not help_map.get(p) and not yaml_comments.semantic_help(p, v)
        ]
        _out(f"[self-test] 无帮助字段: {len(no_help)}（应为 0）")
        _out(f"[self-test] 预设默认: {config_presets.DEFAULT_PROFILE}")

        # Qt 表单构建（无头）
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
        from prompt.random_generator.gui_qt.forms import ConfigFormBuilder

        app = QApplication([])
        root = QWidget()
        lay = QVBoxLayout(root)
        collapsed = {
            "r18_topic_control", "extra_requirements_pool", "character_pool",
            "character_whitelist", "category_whitelists", "r18_sample_counts",
            "r18_focus_weights", "default_word_quota", "subcategory_quotas", "sample_counts",
        }
        builder = ConfigFormBuilder(root, help_map, collapsed_paths=collapsed)
        builder.build_dict(gen_cfg)
        _out(f"[self-test] Qt 表单字段: {len(builder.fields)}")
        out = builder.get_dict()
        _out(f"[self-test] Qt 表单收集 min_tags: {out.get('min_tags')}")
        ok = True
    except Exception as exc:  # noqa: BLE001
        _out(f"[self-test] 失败: {exc!r}")
        ok = False

    base = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
    out_path = os.path.join(base, "self_test_result.txt")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return 0 if ok else 1


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    from prompt.random_generator.gui_qt.app import run

    run()


if __name__ == "__main__":
    main()
