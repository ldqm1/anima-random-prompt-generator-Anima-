#!/usr/bin/env python3
"""Anima 随机提示词生成器 - 桌面版入口。

开发运行：python anima_gui.py
打包：python build_exe.py
自检：python anima_gui.py --self-test   # 加载资源+预览后退出（验证打包完整性）
"""
import sys


def _self_test() -> int:
    """加载全部资源并生成一条预览，验证打包资源完整后退出。

    结果写入 exe 同目录的 ``self_test_result.txt``（窗口化 exe 无 stdout）。
    """
    import os

    from prompt.random_generator import gui_engine as ge
    from prompt.random_generator.gui_engine import GenConfig

    lines: list[str] = []
    logs: list[str] = []

    def on_log(m: str) -> None:
        logs.append(m)
        lines.append(f"[load] {m}")

    try:
        res = ge.load_resources(progress=on_log, max_rating="r15")
        kb = res["knowledge_database"]
        lines.append(
            f"[self-test] 知识库类别: {len(kb)} 类，共 {sum(len(v) for v in kb.values())} 条"
        )
        cfg = GenConfig(max_rating="r15", count=1, seed=12345, min_tags=50, max_tags=75)
        pv = ge.preview(res, cfg)
        lines.append(
            f"[self-test] 预览成功 seed={pv['seed']} safety={pv['safety']} "
            f"渲染长度={len(pv['user_prompt'])}"
        )
        # 验证配置编辑模块可用（表单生成器 + 注释提取 + 深合并）
        from prompt.random_generator import gui_forms, yaml_comments, config
        from prompt.random_generator.config_merge import deep_merge

        help_map = yaml_comments.build_help_map(config.GENERATION_CONFIG_FILE)
        lines.append(f"[self-test] 帮助文本键数: {len(help_map)}")
        import yaml

        with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
            gen_cfg = yaml.safe_load(f) or {}
        merged = deep_merge(gen_cfg, {"min_tags": 55})
        lines.append(f"[self-test] 深合并 min_tags: {merged.get('min_tags')}")
        ok = True
    except Exception as exc:  # noqa: BLE001
        lines.append(f"[self-test] 失败: {exc!r}")
        ok = False

    base = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
    out = os.path.join(base, "self_test_result.txt")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return 0 if ok else 1


def main() -> None:
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    from prompt.random_generator.gui_app import main as gui_main

    gui_main()


if __name__ == "__main__":
    main()
