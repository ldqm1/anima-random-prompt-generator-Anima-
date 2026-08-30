"""Anima 随机提示词生成器 - 桌面图形界面。

面向不熟悉 Python / 配置文件的用户：常用参数在窗口里直接调整，
API Key 可记住到用户目录（绝不写入仓库），支持大批量生成（断点续存 + 进度），
生成结果实时预览与复制。

打包：python -m PyInstaller anima_gui.spec
开发运行：python anima_gui.py
"""
from __future__ import annotations

import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from . import config
from .gui_engine import (
    GenConfig,
    ProgressEvent,
    generate_batch,
    load_resources,
    preview,
)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover
    tk = tb
    filedialog = messagebox = ttk = None


APP_NAME = "Anima 随机提示词生成器"
APP_VERSION = "3.0.0"

# 记住的 API 设置保存位置（用户目录，非仓库）
SETTINGS_DIR = os.path.join(
    os.environ.get("APPDATA") or str(Path.home()), "AnimaPromptGenerator"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

RATING_LABELS = {
    "general": "general（全年龄）",
    "pg12": "pg12（12+）",
    "r15": "r15（15+，推荐）",
    "r18": "r18（18+，成人向）",
    "r18g": "r18g（18+ 重口，慎用）",
}
RATING_VALUES = {v: k for k, v in RATING_LABELS.items()}


def rating_to_label(rating: str) -> str:
    """评级短名 -> 下拉框显示文本（未知值回退 r15）。"""
    return RATING_LABELS.get(rating, RATING_LABELS["r15"])


def app_output_dir() -> str:
    """默认输出目录：打包后为 exe 同目录/output，开发时为项目 output。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "output")
    return str(config.OUTPUT_DIR)


def _load_settings() -> dict[str, Any]:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_settings(settings: dict[str, Any]) -> None:
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 工具：在冻结（PyInstaller）环境下找资源
# ---------------------------------------------------------------------------
def _resource_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return str(config.PROJECT_DIR)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class AnimaGui(tb.Window):
    def __init__(self) -> None:
        super().__init__(themename="flatly")
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("980x720")
        self.minsize(860, 620)

        # 状态
        self._resources: dict[str, Any] | None = None
        self._resource_error: str | None = None
        self._running = False
        self._cancel_event = threading.Event()
        self._gen_thread: threading.Thread | None = None
        self._load_thread: threading.Thread | None = None
        self._pending_start = False
        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._gen_config: GenConfig | None = None
        self._result_rows: list[dict[str, Any]] = []
        self._r18_confirmed = False

        # 从 yaml 读默认生成参数（不触发大数据加载）
        self._gen_defaults = self._read_gen_defaults()

        self._build_ui()
        self._load_saved_settings()
        self.after(120, self._poll_queue)
        self._log(f"{APP_NAME} v{APP_VERSION} 已启动。")

    # ------------------------------------------------------------------
    # 默认参数读取
    # ------------------------------------------------------------------
    def _read_gen_defaults(self) -> dict[str, Any]:
        try:
            import yaml

            with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg
        except (OSError, ImportError):
            return {}

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        nb = tb.Notebook(self, bootstyle="primary")
        nb.pack(fill=BOTH, expand=True, padx=8, pady=(8, 0))

        self.tab_gen = tb.Frame(nb)
        self.tab_api = tb.Frame(nb)
        self.tab_adv = tb.Frame(nb)
        self.tab_log = tb.Frame(nb)
        nb.add(self.tab_gen, text="  生成  ")
        nb.add(self.tab_api, text="  API 设置  ")
        nb.add(self.tab_adv, text="  高级  ")
        nb.add(self.tab_log, text="  日志 / 输出  ")

        self._build_gen_tab()
        self._build_api_tab()
        self._build_adv_tab()
        self._build_log_tab()

        # 状态栏
        self._status = tb.StringVar(value="就绪")
        status_bar = tb.Label(
            self, textvariable=self._status, anchor="w", bootstyle="secondary"
        )
        status_bar.pack(fill=X, side=BOTTOM, padx=8, pady=4)

    # ---------------- 生成页 ----------------
    def _build_gen_tab(self) -> None:
        f = self.tab_gen

        # 左：参数区
        left = tb.Frame(f)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(8, 4), pady=8)
        self._gen_left = left

        r1 = tb.Frame(left)
        r1.pack(fill=X, pady=3)
        tb.Label(r1, text="生成数量:", width=12).pack(side=LEFT)
        self.var_count = tk.IntVar(value=10)
        sb_count = ttk.Spinbox(r1, from_=1, to=100000, textvariable=self.var_count, width=10)
        sb_count.pack(side=LEFT)
        tb.Label(r1, text="  内容分级:").pack(side=LEFT, padx=(12, 0))
        self.var_rating = tk.StringVar(value="r15（15+，推荐）")
        cb_rating = tb.Combobox(
            r1, textvariable=self.var_rating, values=list(RATING_LABELS.values()),
            state="readonly", width=24,
        )
        cb_rating.pack(side=LEFT)
        cb_rating.bind("<<ComboboxSelected>>", self._on_rating_change)

        r2 = tb.Frame(left)
        r2.pack(fill=X, pady=3)
        tb.Label(r2, text="随机种子:", width=12).pack(side=LEFT)
        self.var_seed_mode = tk.StringVar(value="random")
        tb.Radiobutton(r2, text="随机", variable=self.var_seed_mode, value="random",
                       command=self._sync_seed_ui).pack(side=LEFT)
        tb.Radiobutton(r2, text="固定", variable=self.var_seed_mode, value="fixed",
                       command=self._sync_seed_ui).pack(side=LEFT)
        self.var_seed = tk.IntVar(value=42)
        self.entry_seed = ttk.Spinbox(r2, from_=0, to=2**32 - 1, textvariable=self.var_seed, width=14)
        self.entry_seed.pack(side=LEFT, padx=(6, 0))
        self.entry_seed.configure(state="disabled")

        r3 = tb.Frame(left)
        r3.pack(fill=X, pady=3)
        tb.Label(r3, text="主题提示:", width=12).pack(side=LEFT)
        self.var_theme = tk.StringVar(value="")
        ttk.Entry(r3, textvariable=self.var_theme).pack(side=LEFT, fill=X, expand=True)

        r4 = tb.Frame(left)
        r4.pack(fill=X, pady=3)
        tb.Label(r4, text="额外要求:", width=12).pack(side=LEFT, anchor="n")
        self.txt_extra = tk.Text(r4, width=30, height=4)
        self.txt_extra.pack(side=LEFT, fill=BOTH, expand=True)

        r5 = tb.Frame(left)
        r5.pack(fill=X, pady=3)
        tb.Label(r5, text="强制保留 tag:", width=12).pack(side=LEFT)
        self.var_forced = tk.StringVar(value="")
        ttk.Entry(r5, textvariable=self.var_forced).pack(side=LEFT, fill=X, expand=True)

        r6 = tb.Frame(left)
        r6.pack(fill=X, pady=3)
        tb.Label(r6, text="强制排除 tag:", width=12).pack(side=LEFT)
        self.var_forbidden = tk.StringVar(value="")
        ttk.Entry(r6, textvariable=self.var_forbidden).pack(side=LEFT, fill=X, expand=True)

        r7 = tb.Frame(left)
        r7.pack(fill=X, pady=3)
        tb.Label(r7, text="输出:", width=12).pack(side=LEFT)
        self.var_output_dir = tk.StringVar(value=app_output_dir())
        ttk.Entry(r7, textvariable=self.var_output_dir).pack(side=LEFT, fill=X, expand=True)
        tb.Button(r7, text="浏览…", bootstyle="secondary-outline",
                  command=self._pick_output_dir).pack(side=LEFT, padx=(4, 0))

        r8 = tb.Frame(left)
        r8.pack(fill=X, pady=3)
        tb.Label(r8, text="文件名:", width=12).pack(side=LEFT)
        self.var_output_name = tk.StringVar(value="random_prompts")
        ttk.Entry(r8, textvariable=self.var_output_name, width=26).pack(side=LEFT)
        tb.Label(r8, text="  （.jsonl / .txt 自动追加）", bootstyle="secondary").pack(side=LEFT, padx=6)

        # 开关行
        r9 = tb.Frame(left)
        r9.pack(fill=X, pady=4)
        self.var_anchors = tk.BooleanVar(value=self._gen_defaults.get("creative_anchors", {}).get("enabled", True))
        tb.Checkbutton(r9, text="启用创意锚点", variable=self.var_anchors, bootstyle="round-toggle").pack(side=LEFT, padx=(0, 16))
        mc = self._gen_defaults.get("multi_character", {})
        self.var_multi = tk.BooleanVar(value=bool(mc.get("enabled", True)))
        tb.Checkbutton(r9, text="允许多角色场景", variable=self.var_multi, bootstyle="round-toggle").pack(side=LEFT)

        # 操作按钮
        r10 = tb.Frame(left)
        r10.pack(fill=X, pady=8)
        self.btn_preview = tb.Button(r10, text="预览样本", bootstyle="info-outline", command=self._on_preview)
        self.btn_preview.pack(side=LEFT, padx=(0, 8))
        self.btn_start = tb.Button(r10, text="开始生成", bootstyle="success", command=self._on_start)
        self.btn_start.pack(side=LEFT, padx=(0, 8))
        self.btn_cancel = tb.Button(r10, text="停止", bootstyle="danger-outline", command=self._on_cancel, state="disabled")
        self.btn_cancel.pack(side=LEFT)

        # 进度
        r11 = tb.Frame(left)
        r11.pack(fill=X, pady=4)
        self.var_progress_text = tb.StringVar(value="")
        self.progress = tb.Progressbar(r11, maximum=100, bootstyle="success-striped")
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        tb.Label(r11, textvariable=self.var_progress_text, width=14).pack(side=LEFT)

        # 右：结果列表
        right = tb.Frame(f)
        right.pack(side=RIGHT, fill=BOTH, expand=True, padx=(4, 8), pady=8)
        tb.Label(right, text="生成结果（双击查看全文）", bootstyle="secondary").pack(anchor="w")
        cols = ("seed", "rating", "tags", "preview")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=20)
        self.tree.heading("seed", text="Seed")
        self.tree.heading("rating", text="分级")
        self.tree.heading("tags", text="Tag数")
        self.tree.heading("preview", text="提示词预览")
        self.tree.column("seed", width=90, anchor="center")
        self.tree.column("rating", width=70, anchor="center")
        self.tree.column("tags", width=60, anchor="center")
        self.tree.column("preview", width=360)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self._on_row_double)

    def _pick_output_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.var_output_dir.get())
        if d:
            self.var_output_dir.set(d)

    # ---------------- API 页 ----------------
    def _build_api_tab(self) -> None:
        f = self.tab_api
        card = tb.Frame(f, bootstyle="light", padding=12)
        card.pack(fill=X, padx=16, pady=12)

        tb.Label(card, text="DeepSeek API 设置", bootstyle="primary").pack(anchor="w")
        tb.Label(card, text="请填写你自己的 DeepSeek 平台 API Key（https://platform.deepseek.com）", bootstyle="secondary").pack(anchor="w", pady=(0, 8))

        grid = tb.Frame(card)
        grid.pack(fill=X)

        tb.Label(grid, text="API Key:").grid(row=0, column=0, sticky="e", pady=3, padx=(0, 8))
        kf = tb.Frame(grid)
        kf.grid(row=0, column=1, sticky="we", pady=3)
        self.var_api_key = tk.StringVar(value="")
        self.entry_key = ttk.Entry(kf, textvariable=self.var_api_key, show="*")
        self.entry_key.pack(side=LEFT, fill=X, expand=True)
        self.var_show_key = tk.BooleanVar(value=False)
        tb.Checkbutton(kf, text="显示", variable=self.var_show_key, command=self._toggle_key_show,
                       bootstyle="secondary").pack(side=LEFT, padx=(6, 0))
        self.var_remember_key = tk.BooleanVar(value=True)
        tb.Checkbutton(card, text="记住 API Key（保存到用户目录，不会写入项目）", variable=self.var_remember_key,
                       bootstyle="round-toggle").pack(anchor="w", pady=(4, 0))
        grid.columnconfigure(1, weight=1)

        tb.Label(grid, text="接口地址:").grid(row=1, column=0, sticky="e", pady=3, padx=(0, 8))
        self.var_api_base = tk.StringVar(value="https://api.deepseek.com/v1")
        ttk.Entry(grid, textvariable=self.var_api_base).grid(row=1, column=1, sticky="we", pady=3)

        tb.Label(grid, text="模型:").grid(row=2, column=0, sticky="e", pady=3, padx=(0, 8))
        self.var_model = tk.StringVar(value="deepseek-chat")
        ttk.Entry(grid, textvariable=self.var_model).grid(row=2, column=1, sticky="we", pady=3)

        tb.Label(grid, text="Temperature:").grid(row=3, column=0, sticky="e", pady=3, padx=(0, 8))
        tf = tb.Frame(grid)
        tf.grid(row=3, column=1, sticky="w", pady=3)
        self.var_temperature = tk.DoubleVar(value=0.7)
        ttk.Spinbox(tf, from_=0.0, to=2.0, increment=0.1, textvariable=self.var_temperature, width=8).pack(side=LEFT)
        tb.Label(tf, text="  超时(秒):", bootstyle="secondary").pack(side=LEFT, padx=(16, 4))
        self.var_timeout = tk.DoubleVar(value=120.0)
        ttk.Spinbox(tf, from_=10, to=600, increment=10, textvariable=self.var_timeout, width=8).pack(side=LEFT)

        tb.Label(grid, text="思考模式:").grid(row=4, column=0, sticky="e", pady=3, padx=(0, 8))
        self.var_reasoning = tk.StringVar(value="none")
        tb.Combobox(grid, textvariable=self.var_reasoning, values=["none", "low", "medium", "high"],
                    state="readonly", width=12).grid(row=4, column=1, sticky="w", pady=3)

        btns = tb.Frame(card)
        btns.pack(fill=X, pady=(10, 0))
        self.btn_test = tb.Button(btns, text="测试连接", bootstyle="primary-outline", command=self._on_test_api)
        self.btn_test.pack(side=LEFT)
        tb.Label(btns, text="  （测试会调用一次模型，消耗少量额度）", bootstyle="secondary").pack(side=LEFT, padx=6)

    def _toggle_key_show(self) -> None:
        self.entry_key.configure(show="" if self.var_show_key.get() else "*")

    # ---------------- 高级页 ----------------
    def _build_adv_tab(self) -> None:
        from . import gui_forms
        from . import yaml_comments
        from .config_merge import load_user_config, merge_with_defaults

        f = self.tab_adv

        # 生成页/引擎依赖的顶层参数变量（先创建，避免 _sync_adv_vars 之前被引用）
        if not hasattr(self, "var_min_tags"):
            self.var_min_tags = tk.IntVar(value=int(self._gen_defaults.get("min_tags", 40)))
            self.var_max_tags = tk.IntVar(value=int(self._gen_defaults.get("max_tags", 60)))
            self.var_workers = tk.IntVar(value=4)
            dk0 = self._gen_defaults.get("deepseek", {})
            self.var_max_tokens = tk.IntVar(value=int(dk0.get("max_tokens", 1000)))
            self.var_max_retries = tk.IntVar(value=int(dk0.get("max_parse_retries", 2)))
            self.var_extra_pool = tk.BooleanVar(
                value=bool(self._gen_defaults.get("extra_requirements_pool", {}).get("enabled", False))
            )

        # 顶部说明 + 操作按钮
        top = tb.Frame(f)
        top.pack(fill=X, padx=12, pady=(8, 4))
        tb.Label(
            top,
            text="完整配置编辑（对应 generation_config.yaml 与 creative_anchors.yaml）。"
                 "悬停任意控件可查看该项说明与效果；修改后点「保存设置」立即生效。",
            bootstyle="secondary", wraplength=700,
        ).pack(anchor="w")
        btns = tb.Frame(f)
        btns.pack(fill=X, padx=12, pady=(0, 6))
        self.btn_save_cfg = tb.Button(btns, text="💾 保存设置", bootstyle="success",
                                      command=self._on_save_config)
        self.btn_save_cfg.pack(side=LEFT, padx=(0, 6))
        self.btn_reset_cfg = tb.Button(btns, text="恢复默认", bootstyle="danger-outline",
                                       command=self._on_reset_config)
        self.btn_reset_cfg.pack(side=LEFT, padx=(0, 6))
        self.btn_expand_all = tb.Button(btns, text="全部展开", bootstyle="secondary-outline",
                                        command=self._on_expand_all)
        self.btn_expand_all.pack(side=LEFT, padx=(0, 6))
        self.btn_collapse_all = tb.Button(btns, text="全部折叠", bootstyle="secondary-outline",
                                          command=self._on_collapse_all)
        self.btn_collapse_all.pack(side=LEFT)
        self.lbl_cfg_status = tb.Label(btns, text="", bootstyle="success")
        self.lbl_cfg_status.pack(side=LEFT, padx=(12, 0))

        # 可滚动容器
        canvas_wrap = tb.Frame(f)
        canvas_wrap.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        self.adv_canvas = tk.Canvas(canvas_wrap, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.adv_canvas.yview)
        self.adv_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.adv_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self.adv_inner = tb.Frame(self.adv_canvas)
        self.adv_win = self.adv_canvas.create_window((0, 0), window=self.adv_inner, anchor="nw")
        self.adv_inner.bind(
            "<Configure>",
            lambda _e: self.adv_canvas.configure(scrollregion=self.adv_canvas.bbox("all")),
        )
        self.adv_canvas.bind(
            "<Configure>",
            lambda e: self.adv_canvas.itemconfigure(self.adv_win, width=e.width),
        )

        # 读取生效配置（默认 + 用户覆盖）
        default_gen = self._gen_defaults
        user_cfg = load_user_config()
        merged = merge_with_defaults(default_gen, user_cfg)

        help_map = yaml_comments.build_help_map(config.GENERATION_CONFIG_FILE)
        anchor_help = yaml_comments.build_help_map(config.CREATIVE_ANCHORS_FILE)
        merged_help = dict(help_map)
        merged_help.update(anchor_help)

        # 危险区默认折叠
        collapsed = {
            "r18_topic_control", "extra_requirements_pool", "character_pool",
            "character_whitelist", "category_whitelists", "r18_sample_counts",
            "r18_focus_weights", "default_word_quota",
        }

        self.adv_builder = gui_forms.ConfigFormBuilder(
            self.adv_inner, merged_help, collapsed_paths=collapsed
        )
        # 顶层分类：生成配置 与 创意锚点（两者都可折叠）
        gen_section = tb.Frame(self.adv_inner)
        self.adv_builder.build_dict(merged, prefix="", parent=gen_section)
        gui_forms.CollapsibleSection(
            self.adv_inner, "生成配置（generation_config.yaml）", gen_section,
            default_open=True,
            help_text="生成器全部配置，对应 generation_config.yaml。"
        )

        # 创意锚点：单独加载并构建
        try:
            import yaml as _yaml

            with config.CREATIVE_ANCHORS_FILE.open("r", encoding="utf-8") as af:
                anchors_cfg = _yaml.safe_load(af) or {}
        except (OSError, ValueError):
            anchors_cfg = {}
        # 用户覆盖锚点
        user_anchors = user_cfg.get("creative_anchors_override")
        if isinstance(user_anchors, dict) and user_anchors:
            anchors_cfg = merge_with_defaults(anchors_cfg, user_anchors)
        self._anchor_top_keys = list(anchors_cfg.keys())
        anchor_section = tb.Frame(self.adv_inner)
        self.adv_builder.build_dict(anchors_cfg, prefix="", parent=anchor_section)
        gui_forms.CollapsibleSection(
            self.adv_inner, "创意锚点池（creative_anchors.yaml）", anchor_section,
            default_open=False,
            help_text="78 个高概念设定锚点，按 7 类组织；可增删/编辑每个锚点的 name/cn/tags/narrative。"
        )

        # 收集按钮引用，供展开/折叠（builder 已记录全部折叠区块）
        self._adv_collapsibles: list[Any] = list(self.adv_builder.collapsibles)

        # 同步 var_*（生成页/引擎读取的顶层参数）
        self._sync_adv_vars(merged)

    def _sync_adv_vars(self, merged: dict[str, Any]) -> None:
        """从合并配置同步生成页依赖的顶层参数变量。"""
        self.var_min_tags.set(int(merged.get("min_tags", 40)))
        self.var_max_tags.set(int(merged.get("max_tags", 60)))
        self.var_workers.set(4)  # 并发数不来自 yaml，保持默认
        dk = merged.get("deepseek", {})
        self.var_max_tokens.set(int(dk.get("max_tokens", 1000)))
        self.var_max_retries.set(int(dk.get("max_parse_retries", 2)))
        pool = merged.get("extra_requirements_pool", {})
        self.var_extra_pool.set(bool(pool.get("enabled", False)))

    # ---- 高级页操作 ----
    def _on_save_config(self) -> None:
        """收集表单 → 与默认 diff → 只写用户覆盖部分到用户目录。"""
        from .config_merge import save_user_config

        collected = self.adv_builder.get_dict()
        # 分离：生成配置顶层键 与 创意锚点顶层键（surreal_scene 等）
        anchor_top_keys = set(self._anchor_top_keys)
        gen_collected: dict[str, Any] = {}
        anchor_collected: dict[str, Any] = {}
        for key, value in collected.items():
            if key in anchor_top_keys:
                anchor_collected[key] = value
            else:
                gen_collected[key] = value
        # 只保留与默认不同的键（diff）
        user_part = self._diff_user(gen_collected, self._gen_defaults)
        # 锚点：与默认锚点比较，仅当确实不同才保存（避免 78 个锚点全量落盘）
        if anchor_collected:
            try:
                import yaml as _yaml

                with config.CREATIVE_ANCHORS_FILE.open("r", encoding="utf-8") as af:
                    default_anchors = _yaml.safe_load(af) or {}
                if anchor_collected != default_anchors:
                    user_part["creative_anchors_override"] = anchor_collected
            except (OSError, ValueError):
                user_part["creative_anchors_override"] = anchor_collected
        ok = save_user_config(user_part)
        if ok:
            self.lbl_cfg_status.configure(text="已保存 ✓", bootstyle="success")
            self._log("高级设置已保存到用户目录（下次生成生效）。")
            self._invalidate_engine_cache()
        else:
            self.lbl_cfg_status.configure(text="保存失败", bootstyle="danger")
            messagebox.showerror("保存失败", "无法写入用户配置文件。")

    def _diff_user(self, collected: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
        """返回 collected 中与 default 不同的部分（递归 diff）。

        字符串比较忽略尾部换行（Text 控件 strip 掉了 yaml 块尾的 \\n）。
        """
        out: dict[str, Any] = {}
        for key, value in collected.items():
            if key not in default:
                out[key] = value
                continue
            if isinstance(value, dict) and isinstance(default[key], dict):
                sub = self._diff_user(value, default[key])
                if sub:
                    out[key] = sub
            elif isinstance(value, str) and isinstance(default[key], str):
                if value.rstrip("\n") != default[key].rstrip("\n"):
                    out[key] = value
            elif value != default[key]:
                out[key] = value
        return out

    def _invalidate_engine_cache(self) -> None:
        from .gui_engine import _cache

        _cache.pop("gen_cfg", None)
        # 评级相关缓存也失效（配置可能影响抽样）
        for k in list(_cache.keys()):
            if k.startswith("r_"):
                _cache.pop(k, None)
        self._log("配置缓存已重置，下次生成将使用新设置。")

    def _on_reset_config(self) -> None:
        from .config_merge import clear_user_config

        if not messagebox.askyesno(
            "恢复默认",
            "将删除全部自定义设置并恢复默认配置。\n（API Key 不受影响）\n确定继续？",
            icon="warning",
        ):
            return
        clear_user_config()
        self.lbl_cfg_status.configure(text="已恢复默认 ✓", bootstyle="success")
        self._log("已删除用户配置，恢复默认。请重启窗口以重新加载表单。")
        # 重建表单
        self._rebuild_adv_form()

    def _rebuild_adv_form(self) -> None:
        """清空并重建高级页表单（恢复默认后）。"""
        for child in self.adv_inner.winfo_children():
            child.destroy()
        self._build_adv_tab()
        self._sync_adv_vars(self._gen_defaults)

    def _on_expand_all(self) -> None:
        for c in getattr(self, "_adv_collapsibles", []):
            if not c.open:
                c._toggle()

    def _on_collapse_all(self) -> None:
        for c in getattr(self, "_adv_collapsibles", []):
            if c.open:
                c._toggle()

    # ---------------- 日志页 ----------------
    def _build_log_tab(self) -> None:
        f = self.tab_log
        tb.Label(f, text="运行日志", bootstyle="secondary").pack(anchor="w", padx=8, pady=(8, 4))
        tf = tb.Frame(f)
        tf.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        self.txt_log = tk.Text(tf, width=100, height=22, state="disabled", wrap="word")
        self.txt_log.pack(side=LEFT, fill=BOTH, expand=True)
        sb = ttk.Scrollbar(tf, orient="vertical", command=self.txt_log.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.txt_log.configure(yscrollcommand=sb.set)

        row = tb.Frame(f)
        row.pack(fill=X, padx=8, pady=(0, 10))
        tb.Button(row, text="打开输出文件夹", bootstyle="primary-outline",
                  command=self._open_output_folder).pack(side=LEFT)
        tb.Label(row, text="  ", bootstyle="secondary").pack(side=LEFT)
        self.lbl_output_path = tb.Label(row, text="", bootstyle="secondary")
        self.lbl_output_path.pack(side=LEFT)
        self._update_output_path_label()

    def _update_output_path_label(self) -> None:
        out = self.var_output_dir.get() if hasattr(self, "var_output_dir") else app_output_dir()
        self.lbl_output_path.configure(text=out)

    def _open_output_folder(self) -> None:
        out = self.var_output_dir.get()
        if not os.path.isdir(out):
            os.makedirs(out, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(out)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", out])
        except Exception as exc:  # noqa: BLE001
            self._log(f"无法打开输出文件夹：{exc}")

    # ------------------------------------------------------------------
    # 设置持久化
    # ------------------------------------------------------------------
    def _load_saved_settings(self) -> None:
        s = _load_settings()
        if s.get("api_base"):
            self.var_api_base.set(s["api_base"])
        if s.get("model"):
            self.var_model.set(s["model"])
        if "temperature" in s:
            self.var_temperature.set(float(s["temperature"]))
        if "timeout" in s:
            self.var_timeout.set(float(s["timeout"]))
        if s.get("reasoning"):
            self.var_reasoning.set(s["reasoning"])
        if s.get("output_dir"):
            self.var_output_dir.set(s["output_dir"])
        if s.get("output_name"):
            self.var_output_name.set(s["output_name"])
        if s.get("min_tags") is not None:
            self.var_min_tags.set(int(s["min_tags"]))
        if s.get("max_tags") is not None:
            self.var_max_tags.set(int(s["max_tags"]))
        if s.get("workers") is not None:
            self.var_workers.set(int(s["workers"]))
        if s.get("max_tokens") is not None:
            self.var_max_tokens.set(int(s["max_tokens"]))
        if s.get("max_rating") in RATING_LABELS:
            self.var_rating.set(RATING_LABELS[s["max_rating"]])
        if s.get("theme_hint") is not None:
            self.var_theme.set(s["theme_hint"])
        if s.get("forced_tags") is not None:
            self.var_forced.set(s["forced_tags"])
        if s.get("forbidden_tags") is not None:
            self.var_forbidden.set(s["forbidden_tags"])
        if s.get("remember_key"):
            self.var_remember_key.set(True)
            if s.get("api_key"):
                self.var_api_key.set(s["api_key"])
        self._sync_seed_ui()

    def _persist_settings(self) -> None:
        s = {
            "api_base": self.var_api_base.get(),
            "model": self.var_model.get(),
            "temperature": self.var_temperature.get(),
            "timeout": self.var_timeout.get(),
            "reasoning": self.var_reasoning.get(),
            "output_dir": self.var_output_dir.get(),
            "output_name": self.var_output_name.get(),
            "min_tags": self.var_min_tags.get(),
            "max_tags": self.var_max_tags.get(),
            "workers": self.var_workers.get(),
            "max_tokens": self.var_max_tokens.get(),
            "max_rating": RATING_VALUES.get(self.var_rating.get(), "r15"),
            "theme_hint": self.var_theme.get(),
            "forced_tags": self.var_forced.get(),
            "forbidden_tags": self.var_forbidden.get(),
            "remember_key": bool(self.var_remember_key.get()),
        }
        if self.var_remember_key.get() and self.var_api_key.get():
            s["api_key"] = self.var_api_key.get()
        elif "api_key" in s:
            s.pop("api_key", None)
        _save_settings(s)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _sync_seed_ui(self) -> None:
        fixed = self.var_seed_mode.get() == "fixed"
        self.entry_seed.configure(state="normal" if fixed else "disabled")

    def _on_rating_change(self, _event: Any = None) -> None:
        rating = RATING_VALUES.get(self.var_rating.get(), "r15")
        if self._running:
            # 生成中不允许切评级（后台任务正使用当前资源）
            self._log(f"生成进行中，评级保持为当前档位。")
            self.var_rating.set(RATING_LABELS.get(self._resources.get("max_rating", "r15"), "r15（15+，推荐）")
                                if self._resources else "r15（15+，推荐）")
            return
        if rating in ("r18", "r18g") and not self._r18_confirmed:
            ok = messagebox.askokcancel(
                "成人内容确认",
                f"你选择了【{rating}】档位。\n\n"
                "该档位会生成成人向（NSFW）内容。\n"
                "生成器已内置硬排除规则（性行为、猎奇血腥、兽化、男性角色等），\n"
                "但输出仍可能包含裸露等内容，请确保你已满 18 岁且合法使用。\n\n"
                "是否继续？",
                icon="warning",
            )
            if not ok:
                self.var_rating.set("r15（15+，推荐）")
                return
            self._r18_confirmed = True
        self._log(f"内容分级已切换为 {rating}")
        # 若资源已按旧评级加载，立即按新评级重建，避免生成时等待。
        if self._resources is not None and self._resources.get("max_rating") != rating:
            self._resources = None
            self._ensure_resources()

    def _collect_config(self) -> GenConfig:
        rating = RATING_VALUES.get(self.var_rating.get(), "r15")
        seed = None
        if self.var_seed_mode.get() == "fixed":
            try:
                seed = int(self.var_seed.get())
            except (tk.TclError, ValueError):
                seed = None
        return GenConfig(
            max_rating=rating,
            count=max(int(self.var_count.get()), 1),
            min_tags=int(self.var_min_tags.get()),
            max_tags=int(self.var_max_tags.get()),
            theme_hint=self.var_theme.get().strip(),
            extra_requirements=self.txt_extra.get("1.0", "end").strip(),
            forced_tags=self.var_forced.get().strip(),
            forbidden_tags=self.var_forbidden.get().strip(),
            seed=seed,
            workers=int(self.var_workers.get()),
            temperature=float(self.var_temperature.get()),
            max_tokens=int(self.var_max_tokens.get()),
            timeout=float(self.var_timeout.get()),
            max_parse_retries=int(self.var_max_retries.get()),
            reasoning_effort=self.var_reasoning.get() or None,
            output_dir=self.var_output_dir.get().strip() or app_output_dir(),
            output_name=self.var_output_name.get().strip() or "random_prompts",
            api_key=self.var_api_key.get().strip() or None,
            api_base=self.var_api_base.get().strip() or None,
            model=self.var_model.get().strip() or None,
            creative_anchors_enabled=bool(self.var_anchors.get()),
            proxies=None,
        )

    def _apply_switch_overrides(self, cfg: GenConfig) -> GenConfig:
        """把界面开关写回 gen_cfg 对应的配置快照（生成前在后台线程执行）。"""
        # 开关会通过 _build_task 从 gen_cfg 读取，这里把开关值注入 gen_cfg 缓存。
        gen_cfg = self._resources["gen_cfg"]
        gen_cfg["creative_anchors"] = {
            **gen_cfg.get("creative_anchors", {}),
            "enabled": bool(self.var_anchors.get()),
        }
        gen_cfg["multi_character"] = {
            **gen_cfg.get("multi_character", {}),
            "enabled": bool(self.var_multi.get()),
        }
        gen_cfg["extra_requirements_pool"] = {
            **gen_cfg.get("extra_requirements_pool", {}),
            "enabled": bool(self.var_extra_pool.get()),
        }
        return cfg

    # ---------------- 预览 ----------------
    def _on_preview(self) -> None:
        if self._running:
            self._log("生成进行中，请先停止再预览。")
            return
        cfg = self._collect_config()
        if not self._ensure_resources():
            return
        self._log("正在生成预览样本（仅抽样+渲染，不调用 API）…")
        try:
            res = preview(self._resources, cfg)
        except Exception as exc:  # noqa: BLE001
            self._log(f"预览失败：{exc}")
            messagebox.showerror("预览失败", str(exc))
            return
        self._show_preview_window(res)

    def _show_preview_window(self, res: dict[str, Any]) -> None:
        win = tb.Toplevel(self)
        win.title(f"预览样本 (seed={res['seed']})")
        win.geometry("720x640")
        tb.Label(win, text=f"Seed: {res['seed']}   分级: {res['safety']}   多角色: {'是' if res['is_multi'] else '否'}",
                 bootstyle="primary").pack(anchor="w", padx=8, pady=(8, 4))
        tb.Label(win, text=f"角色: {res['character_tag'] or '（无）'}", bootstyle="secondary").pack(anchor="w", padx=8)

        tb.Label(win, text="抽样标签：", bootstyle="secondary").pack(anchor="w", padx=8, pady=(8, 2))
        txt_sampled = tk.Text(win, height=8, wrap="word")
        txt_sampled.insert("1.0", res["sampled_text"])
        txt_sampled.configure(state="disabled")
        txt_sampled.pack(fill=X, padx=8)

        tb.Label(win, text="渲染后的用户提示词（将发送给 DeepSeek）：", bootstyle="secondary").pack(anchor="w", padx=8, pady=(8, 2))
        txt_prompt = tk.Text(win, height=16, wrap="word")
        txt_prompt.insert("1.0", res["user_prompt"])
        txt_prompt.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))
        tb.Button(win, text="复制全文", bootstyle="info-outline",
                  command=lambda: self._copy_to_clipboard(res["user_prompt"])).pack(pady=(0, 8))

    # ---------------- 生成 ----------------
    def _ensure_resources(self) -> bool:
        """确保资源按当前评级加载；评级变化时自动重建（后台线程）。"""
        rating = RATING_VALUES.get(self.var_rating.get(), "r15")
        if self._resources is not None:
            if self._resources.get("max_rating") == rating:
                return True
            # 评级变了，需要重建
            self._log(f"检测到评级切换为 {rating}，重新预过滤知识库…")
            self._resources = None
        if self._resource_error:
            messagebox.showerror("加载失败", self._resource_error)
            return False
        if self._load_thread is not None and self._load_thread.is_alive():
            self._log("资源仍在加载中，请稍候…")
            return False
        self._status.set("正在加载知识库资源（首次约需 10~30 秒）…")
        self._load_thread = threading.Thread(
            target=self._load_resources_worker, args=(rating,), daemon=True
        )
        self._load_thread.start()
        return False

    def _load_resources_worker(self, rating: str) -> None:
        try:
            res = load_resources(
                progress=lambda m: self._queue.put(("log", m)),
                max_rating=rating,
            )
            self._queue.put(("resources", res))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("resource_error", str(exc)))

    def _on_start(self) -> None:
        if self._running:
            return
        cfg = self._collect_config()
        if not self.var_api_key.get().strip():
            messagebox.showwarning("缺少 API Key", "请先在「API 设置」页填写你的 DeepSeek API Key。")
            self._log("未填写 API Key，已取消生成。")
            return
        if cfg.seed is None:
            cfg.seed = random.randint(0, 2**32 - 1)
        self._gen_config = cfg
        self._persist_settings()
        self._log(f"开始生成 {cfg.count} 条（{cfg.max_rating}）…")
        if not self._ensure_resources():
            self._log("等待资源加载完成…")
            # 资源加载完成后自动开始
            self._pending_start = True
            return
        self._launch_generation(cfg)

    def _launch_generation(self, cfg: GenConfig) -> None:
        if self._running:
            return
        self._running = True
        self._cancel_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress.configure(value=0)
        self.var_progress_text.set("0%")
        self._tree_clear()
        self._result_rows = []
        self._status.set("正在生成…")
        self._gen_thread = threading.Thread(target=self._gen_worker, args=(cfg,), daemon=True)
        self._gen_thread.start()

    def _gen_worker(self, cfg: GenConfig) -> None:
        try:
            self._apply_switch_overrides(cfg)
            self._queue.put(("log", f"工作目录：{cfg.output_dir}"))
            result = generate_batch(
                self._resources,
                cfg,
                on_progress=lambda ev: self._queue.put(("progress", ev)),
                cancel_event=self._cancel_event,
            )
            self._queue.put(("batch_done", result))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("gen_error", str(exc)))

    def _on_cancel(self) -> None:
        if self._running:
            self._cancel_event.set()
            self._log("正在停止…（已生成的结果不会丢失）")
            self.btn_cancel.configure(state="disabled")

    def _on_test_api(self) -> None:
        key = self.var_api_key.get().strip()
        if not key:
            messagebox.showwarning("缺少 API Key", "请先填写 API Key。")
            return
        self.btn_test.configure(state="disabled")
        self._status.set("正在测试连接…")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self) -> None:
        try:
            from . import client as c

            model = self.var_model.get().strip() or None
            base = self.var_api_base.get().strip() or None
            resp = c.call_deepseek(
                system_prompt="ping",
                user_prompt="Reply with exactly: pong",
                api_key=self.var_api_key.get().strip(),
                api_base=base,
                model=model,
                temperature=0,
                max_tokens=8,
                timeout=min(float(self.var_timeout.get()), 60),
            )
            msg = (resp.get("choices") or [{}])[0].get("message", {})
            content = (msg.get("content") or "").strip()
            self._queue.put(("test_result", content or "(空响应)"))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("test_error", str(exc)))

    # ---------------- 结果展示 ----------------
    def _tree_clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _add_result_row(self, record: dict[str, Any]) -> None:
        version_1 = record.get("version_1", "")
        tag_count = len([t for t in version_1.split(", ") if t.strip()])
        preview_txt = (version_1[:120] + "…") if len(version_1) > 120 else version_1
        self.tree.insert(
            "", "end",
            values=(record.get("seed", ""), record.get("max_rating", ""), tag_count, preview_txt),
        )
        self._result_rows.append({"version_1": version_1, "record": record})

    def _on_row_double(self, _event: Any = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        idx = int(self.tree.index(sel[0]))
        if idx >= len(self._result_rows):
            return
        row = self._result_rows[idx]
        win = tb.Toplevel(self)
        win.title(f"提示词全文 (seed={row['record'].get('seed', '')})")
        win.geometry("760x520")
        txt = tk.Text(win, wrap="word")
        txt.insert("1.0", row["version_1"])
        txt.configure(state="disabled")
        txt.pack(fill=BOTH, expand=True, padx=8, pady=8)
        btns = tb.Frame(win)
        btns.pack(fill=X, padx=8, pady=(0, 8))
        tb.Button(btns, text="复制", bootstyle="info-outline",
                  command=lambda: self._copy_to_clipboard(row["version_1"])).pack(side=LEFT)

    def _copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self._log("已复制到剪贴板。")

    # ---------------- 队列轮询 ----------------
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    self._on_progress(msg[1])
                elif kind == "resources":
                    self._resources = msg[1]
                    self._resource_error = None
                    self._status.set("资源加载完成。")
                    self._log("知识库资源加载完成。")
                    # 如果用户在等待加载后开始，自动继续（校验评级未变，避免不一致）
                    if getattr(self, "_pending_start", False):
                        self._pending_start = False
                        cfg = self._gen_config
                        want_rating = RATING_VALUES.get(self.var_rating.get(), "r15")
                        if cfg is not None and cfg.max_rating == want_rating:
                            self._launch_generation(cfg)
                        elif cfg is not None:
                            # 评级在等待期间变了：重载资源
                            self._log("评级已变化，重新加载资源…")
                            self._ensure_resources()
                elif kind == "resource_error":
                    self._resource_error = msg[1]
                    self._status.set("资源加载失败。")
                    self._log(f"资源加载失败：{msg[1]}")
                elif kind == "batch_done":
                    self._on_batch_done(msg[1])
                elif kind == "gen_error":
                    self._running = False
                    self._reset_buttons()
                    self._status.set("生成失败。")
                    self._log(f"生成失败：{msg[1]}")
                    messagebox.showerror("生成失败", str(msg[1]))
                elif kind == "test_result":
                    self.btn_test.configure(state="normal")
                    self._status.set("连接正常。")
                    self._log(f"API 连接测试成功，响应：{msg[1]!r}")
                    messagebox.showinfo("测试成功", f"API 连接正常。\n模型响应：{msg[1]!r}")
                elif kind == "test_error":
                    self.btn_test.configure(state="normal")
                    self._status.set("连接失败。")
                    self._log(f"API 连接测试失败：{msg[1]}")
                    messagebox.showerror("测试失败", str(msg[1]))
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _on_progress(self, ev: ProgressEvent) -> None:
        if ev.total > 0:
            pct = int(100 * ev.done / ev.total)
            self.progress.configure(value=pct)
            self.var_progress_text.set(f"{ev.done}/{ev.total}")
            self._status.set(f"生成中… {ev.done}/{ev.total} 完成，失败 {ev.failed}")

    def _on_batch_done(self, result: Any) -> None:
        self._running = False
        self._reset_buttons()
        self._status.set("生成完成。" if not result.canceled else "已停止。")
        for err in result.errors[:20]:
            self._log(f"失败：{err}")
        self._log(
            f"完成：成功 {result.ok} 条，失败 {result.failed} 条"
            + ("（用户停止）" if result.canceled else "")
        )
        self._log(f"JSONL: {result.output_jsonl}")
        self._log(f"TXT:   {result.output_txt}")
        self.var_progress_text.set(f"{result.ok}/{result.ok + result.failed}")
        if result.ok > 0:
            self._status.set(f"完成：{result.ok} 条。")
            messagebox.showinfo(
                "生成完成",
                f"成功生成 {result.ok} 条，失败 {result.failed} 条。\n\n"
                f"JSONL：{result.output_jsonl}\n"
                f"TXT：{result.output_txt}",
            )

    def _reset_buttons(self) -> None:
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"[{ts}] {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")


def main() -> None:
    app = AnimaGui()
    app.mainloop()


if __name__ == "__main__":
    main()
