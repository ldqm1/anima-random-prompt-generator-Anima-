"""Anima 随机提示词生成器 - PySide6 主窗口。

功能与 tkinter 版等价：生成 / API / 高级 / 配置 / 日志 5 Tab，
动态配置表单 + 悬浮帮助、多预设管理、深色/浅色主题、断点续存、预览复制。
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
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..gui_engine import (
    GenConfig,
    ProgressEvent,
    generate_batch,
    load_resources,
    preview,
)
from .forms import ConfigFormBuilder, CollapsibleSection
from .theme import THEME_QSS
from .toast import Toast
from .tooltip import attach_tooltip

APP_NAME = "Anima 随机提示词生成器"
APP_VERSION = "3.3.0"

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

THEME_OPTIONS = ["浅色", "深色", "跟随系统"]


def app_output_dir() -> str:
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


class _QueueBridge(QObject):
    """后台线程 → GUI 主线程的队列桥（信号）。"""

    message = Signal(tuple)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1020, 760)
        self.setMinimumSize(900, 640)

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
        self._saved_theme = int(_load_settings().get("theme", 0))
        self._gen_defaults = self._read_gen_defaults()

        # 队列桥
        self._bridge = _QueueBridge()
        self._bridge.message.connect(self._on_queue_message)

        self._build_ui()
        self._apply_theme(self._saved_theme)
        self._apply_cursors()
        self._set_window_icon()
        self._load_saved_settings()
        self._poll_timer = self._start_poll()
        self._log(f"{APP_NAME} v{APP_VERSION} 已启动（PySide6）。")

    def _set_window_icon(self) -> None:
        """设置窗口图标（Qt 标准图标兜底，避免空白标题栏图标）。"""
        try:
            from PySide6.QtGui import QIcon
            from PySide6.QtWidgets import QStyle

            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:  # noqa: BLE001
            pass

    def _apply_cursors(self) -> None:
        """给所有可点击控件设手型光标，提升可点击性感知。"""
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QAbstractButton, QComboBox, QListWidget, QCheckBox, QRadioButton

        def _walk(w: QWidget) -> None:
            if isinstance(w, (QAbstractButton, QComboBox, QListWidget)):
                w.setCursor(_Qt.CursorShape.PointingHandCursor)
            for ch in w.findChildren(QWidget):
                if isinstance(ch, (QAbstractButton, QComboBox, QListWidget)):
                    ch.setCursor(_Qt.CursorShape.PointingHandCursor)

        _walk(self)

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def _read_gen_defaults(self) -> dict[str, Any]:
        try:
            import yaml

            with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except (OSError, ImportError):
            return {}

    @staticmethod
    def _system_is_dark() -> bool:
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return value == 0
        except OSError:
            return False

    def _resolve_theme_mode(self, choice: int) -> str:
        if choice == 1:
            return "dark"
        if choice == 2:
            return "dark" if self._system_is_dark() else "light"
        return "light"

    def _apply_theme(self, choice: int) -> None:
        mode = self._resolve_theme_mode(choice)
        QApplication.instance().setStyleSheet(THEME_QSS[mode])
        self._saved_theme = choice

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        self.tabs = QTabWidget(central)
        root.addWidget(self.tabs, 1)

        self.tab_gen = QWidget()
        self.tab_nomodel = QWidget()
        self.tab_api = QWidget()
        self.tab_adv = QWidget()
        self.tab_profiles = QWidget()
        self.tab_log = QWidget()
        self.tabs.addTab(self.tab_gen, "生成")
        self.tabs.addTab(self.tab_nomodel, "无 API 模式")
        self.tabs.addTab(self.tab_api, "API 设置")
        self.tabs.addTab(self.tab_adv, "高级")
        self.tabs.addTab(self.tab_profiles, "配置")
        self.tabs.addTab(self.tab_log, "日志 / 输出")

        self._build_gen_tab()
        self._build_nomodel_tab()
        self._build_api_tab()
        self._build_adv_tab()
        self._build_profiles_tab()
        self._build_log_tab()

        # 底部栏
        bottom = QWidget(central)
        bottom_lay = QHBoxLayout(bottom)
        bottom_lay.setContentsMargins(4, 2, 4, 2)
        self.lbl_status = QLabel("就绪", bottom)
        bottom_lay.addWidget(self.lbl_status, 1)
        bottom_lay.addWidget(QLabel("外观:", bottom))
        self.cb_theme = QComboBox(bottom)
        self.cb_theme.addItems(THEME_OPTIONS)
        self.cb_theme.setCurrentIndex(min(max(self._saved_theme, 0), 2))
        self.cb_theme.currentIndexChanged.connect(self._on_theme_change)
        bottom_lay.addWidget(self.cb_theme)
        root.addWidget(bottom)

    # ------------------------------------------------------------------
    # 生成页
    # ------------------------------------------------------------------
    def _build_gen_tab(self) -> None:
        f = self.tab_gen
        outer = QHBoxLayout(f)
        outer.setContentsMargins(8, 8, 8, 8)

        left = QFrame(f)
        left.setObjectName("card")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(14, 12, 14, 12)
        left_lay.setSpacing(7)
        outer.addWidget(left, 3)
        # 页面标题
        title = QLabel("随机提示词生成", left)
        title.setObjectName("sectionTitle")
        left_lay.addWidget(title)

        # 行1: 数量 + 分级
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("生成数量:"))
        self.sp_count = QSpinBox(left)
        self.sp_count.setRange(1, 100000)
        self.sp_count.setValue(10)
        row1.addWidget(self.sp_count)
        row1.addSpacing(16)
        row1.addWidget(QLabel("内容分级:"))
        self.cb_rating = QComboBox(left)
        self.cb_rating.addItems(list(RATING_LABELS.values()))
        self.cb_rating.setCurrentText(RATING_LABELS["r15"])
        self.cb_rating.currentIndexChanged.connect(self._on_rating_change)
        row1.addWidget(self.cb_rating)
        row1.addStretch(1)
        left_lay.addLayout(row1)

        # 行2: 种子（随机/固定互斥单选）
        from PySide6.QtWidgets import QRadioButton, QButtonGroup

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("随机种子:"))
        self.rb_seed_random = QRadioButton("随机", left)
        self.rb_seed_fixed = QRadioButton("固定", left)
        self._seed_group = QButtonGroup(left)
        self._seed_group.addButton(self.rb_seed_random)
        self._seed_group.addButton(self.rb_seed_fixed)
        self.rb_seed_random.setChecked(True)
        self.rb_seed_random.toggled.connect(self._sync_seed_ui)
        row2.addWidget(self.rb_seed_random)
        row2.addWidget(self.rb_seed_fixed)
        self.sp_seed = QSpinBox(left)
        self.sp_seed.setRange(0, 2**31 - 1)
        self.sp_seed.setValue(42)
        self.sp_seed.setEnabled(False)
        row2.addWidget(self.sp_seed)
        row2.addStretch(1)
        left_lay.addLayout(row2)

        # 行3: 主题
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("主题提示:"))
        self.edit_theme = QLineEdit(left)
        row3.addWidget(self.edit_theme, 1)
        left_lay.addLayout(row3)

        # 行4: 额外要求（填充剩余空间，方便写长要求）
        row4 = QVBoxLayout()
        row4.addWidget(QLabel("额外要求:"))
        self.txt_extra = QPlainTextEdit(left)
        self.txt_extra.setMinimumHeight(60)
        row4.addWidget(self.txt_extra, 1)
        left_lay.addLayout(row4, 1)

        # 行5: 强制/排除 tag
        row5 = QHBoxLayout()
        row5.addWidget(QLabel("强制 tag:"))
        self.edit_forced = QLineEdit(left)
        row5.addWidget(self.edit_forced, 1)
        left_lay.addLayout(row5)
        row5b = QHBoxLayout()
        row5b.addWidget(QLabel("排除 tag:"))
        self.edit_forbidden = QLineEdit(left)
        row5b.addWidget(self.edit_forbidden, 1)
        left_lay.addLayout(row5b)

        # 行6: 输出
        row6 = QHBoxLayout()
        row6.addWidget(QLabel("输出目录:"))
        self.edit_output_dir = QLineEdit(left)
        self.edit_output_dir.setText(app_output_dir())
        row6.addWidget(self.edit_output_dir, 1)
        btn_browse = QPushButton("浏览…", left)
        btn_browse.clicked.connect(self._pick_output_dir)
        row6.addWidget(btn_browse)
        left_lay.addLayout(row6)
        row6b = QHBoxLayout()
        row6b.addWidget(QLabel("文件名:"))
        self.edit_output_name = QLineEdit(left)
        self.edit_output_name.setText("random_prompts")
        row6b.addWidget(self.edit_output_name, 1)
        row6b.addWidget(QLabel("（.jsonl/.txt 自动追加）"))
        left_lay.addLayout(row6b)

        # 行7: 开关
        row7 = QHBoxLayout()
        self.cb_anchors = QCheckBox("启用创意锚点", left)
        self.cb_anchors.setChecked(bool(self._gen_defaults.get("creative_anchors", {}).get("enabled", True)))
        row7.addWidget(self.cb_anchors)
        mc = self._gen_defaults.get("multi_character", {})
        self.cb_multi = QCheckBox("允许多角色场景", left)
        self.cb_multi.setChecked(bool(mc.get("enabled", True)))
        row7.addWidget(self.cb_multi)
        row7.addStretch(1)
        left_lay.addLayout(row7)

        # 行8: 操作按钮
        row8 = QHBoxLayout()
        self.btn_preview = QPushButton("预览样本", left)
        self.btn_preview.setObjectName("primary")
        self.btn_preview.clicked.connect(self._on_preview)
        row8.addWidget(self.btn_preview)
        self.btn_start = QPushButton("开始生成", left)
        self.btn_start.setObjectName("success")
        self.btn_start.clicked.connect(self._on_start)
        row8.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("停止", left)
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._on_cancel)
        row8.addWidget(self.btn_cancel)
        row8.addStretch(1)
        left_lay.addLayout(row8)

        # 行9: 进度
        row9 = QHBoxLayout()
        self.progress = QProgressBar(left)
        self.progress.setRange(0, 100)
        row9.addWidget(self.progress, 1)
        self.lbl_progress = QLabel("0/0", left)
        row9.addWidget(self.lbl_progress)
        left_lay.addLayout(row9)

        # 右: 结果列表
        right = QFrame(f)
        right.setObjectName("card")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(14, 12, 14, 12)
        outer.addWidget(right, 4)
        rtitle = QLabel("生成结果（双击查看全文）", right)
        rtitle.setObjectName("sectionTitle")
        right_lay.addWidget(rtitle)
        self.tree = QListWidget(right)
        self.tree.itemDoubleClicked.connect(self._on_row_double)
        right_lay.addWidget(self.tree, 1)

    def _pick_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.edit_output_dir.text())
        if d:
            self.edit_output_dir.setText(d)

    # ------------------------------------------------------------------
    # 无 API 模式（生成完整提示词模板，复制后发网页端 LLM）
    # ------------------------------------------------------------------
    def _build_nomodel_tab(self) -> None:
        from PySide6.QtWidgets import QTextEdit

        f = self.tab_nomodel
        outer = QVBoxLayout(f)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        desc = QLabel(
            "无需 API Key。本页生成「系统提示词 + 用户提示词」完整模板，"
            "点击复制后粘贴到任意网页端 LLM（如 DeepSeek 网页），LLM 将按指令输出最终单行提示词。"
        )
        desc.setWordWrap(True)
        desc.setObjectName("hint")
        outer.addWidget(desc)

        # 参数行
        params = QHBoxLayout()
        params.addWidget(QLabel("数量:"))
        self.sp_nm_count = QSpinBox(f)
        self.sp_nm_count.setRange(1, 50)
        self.sp_nm_count.setValue(1)
        params.addWidget(self.sp_nm_count)
        params.addSpacing(12)
        params.addWidget(QLabel("内容分级:"))
        self.cb_nm_rating = QComboBox(f)
        self.cb_nm_rating.addItems(list(RATING_LABELS.values()))
        self.cb_nm_rating.setCurrentText(RATING_LABELS["r15"])
        params.addWidget(self.cb_nm_rating)
        params.addSpacing(12)
        params.addWidget(QLabel("主题:"))
        self.edit_nm_theme = QLineEdit(f)
        self.edit_nm_theme.setPlaceholderText("可选主题提示")
        params.addWidget(self.edit_nm_theme, 1)
        outer.addLayout(params)

        # 额外要求
        req = QHBoxLayout()
        req.addWidget(QLabel("额外要求:"))
        self.edit_nm_extra = QLineEdit(f)
        self.edit_nm_extra.setPlaceholderText("可选，如：画面要体现可爱的感觉")
        req.addWidget(self.edit_nm_extra, 1)
        outer.addLayout(req)

        # 操作
        ops = QHBoxLayout()
        self.btn_nm_generate = QPushButton("生成提示词模板", f)
        self.btn_nm_generate.setObjectName("success")
        self.btn_nm_generate.clicked.connect(self._on_nomodel_generate)
        ops.addWidget(self.btn_nm_generate)
        self.btn_nm_copy = QPushButton("复制全部", f)
        self.btn_nm_copy.setObjectName("primary")
        self.btn_nm_copy.clicked.connect(self._on_nomodel_copy)
        ops.addWidget(self.btn_nm_copy)
        ops.addWidget(QLabel("（可生成多条，点下方条目查看对应模板）"))
        ops.addStretch(1)
        outer.addLayout(ops)

        # 条目列表（多条时切换）
        self.lbl_nm_prompt = QLabel("生成结果：")
        outer.addWidget(self.lbl_nm_prompt)
        self.list_nm_results = QListWidget(f)
        self.list_nm_results.setMaximumHeight(90)
        self.list_nm_results.currentRowChanged.connect(self._on_nomodel_select)
        outer.addWidget(self.list_nm_results)
        # 代码框
        self.txt_nm_output = QPlainTextEdit(f)
        self.txt_nm_output.setReadOnly(True)
        self.txt_nm_output.setObjectName("codeBox")
        font = self.txt_nm_output.font()
        font.setFamily("Consolas")
        font.setPointSize(10)
        self.txt_nm_output.setFont(font)
        outer.addWidget(self.txt_nm_output, 1)
        self._nm_results: list[dict[str, Any]] = []

    def _on_nomodel_generate(self) -> None:
        from ..gui_engine import generate_plain

        if not self._ensure_resources():
            self._log("等待资源加载完成…")
            return
        rating = RATING_VALUES.get(self.cb_nm_rating.currentText(), "r15")
        cfg = GenConfig(
            max_rating=rating,
            count=1,
            min_tags=50,
            max_tags=75,
            theme_hint=self.edit_nm_theme.text().strip(),
            extra_requirements=self.edit_nm_extra.text().strip(),
            seed=None,
            workers=4,
            temperature=0.7,
            max_tokens=1000,
            timeout=120.0,
            max_parse_retries=2,
            reasoning_effort="none",
            output_dir=app_output_dir(),
            output_name="nomodel",
            creative_anchors_enabled=bool(self.cb_anchors.isChecked()),
            proxies=None,
        )
        n = max(int(self.sp_nm_count.value()), 1)
        self._nm_results = []
        self.list_nm_results.clear()
        self.lbl_nm_prompt.setText(f"生成结果（{n} 条）：")
        self._log(f"无 API 模式：生成 {n} 条提示词模板（{rating}）…")
        try:
            for i in range(n):
                r = generate_plain(self._resources, cfg)
                self._nm_results.append(r)
                self.list_nm_results.addItem(f"#{i+1}  seed={r['seed']}  {r['safety']}  {r['character_tag'] or '（无角色）'}")
            if self._nm_results:
                self.list_nm_results.setCurrentRow(0)
                self._show_nomodel_result(0)
            self._log(f"无 API 模式生成完成：{n} 条。")
            self._flash_button(self.btn_nm_generate, f"✓ 已生成 {n} 条")
            Toast.show(self, f"已生成 {n} 条提示词模板", kind="success")
        except Exception as exc:  # noqa: BLE001
            self._log(f"无 API 模式生成失败：{exc}")
            Toast.show(self, "生成失败", kind="error")
            QMessageBox.critical(self, "生成失败", str(exc))

    def _on_nomodel_select(self, row: int) -> None:
        if 0 <= row < len(self._nm_results):
            self._show_nomodel_result(row)

    def _show_nomodel_result(self, idx: int) -> None:
        r = self._nm_results[idx]
        self.txt_nm_output.setPlainText(r["full_text"])
        self.lbl_nm_prompt.setText(f"生成结果 #{idx+1}  seed={r['seed']}  分级={r['safety']}")

    def _on_nomodel_copy(self) -> None:
        text = self.txt_nm_output.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._log("无 API 模式：完整提示词模板已复制。")
        self._flash_button(self.btn_nm_copy, "✓ 已复制")
        Toast.show(self, "提示词模板已复制到剪贴板", kind="success")

    def _flash_button(self, btn: QPushButton, flash_text: str) -> None:
        """按钮短暂显示反馈文字后恢复原样。"""
        orig = btn.text()
        btn.setText(flash_text)

        def _restore() -> None:
            try:
                btn.setText(orig)
            except RuntimeError:  # 控件已销毁
                pass

        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, _restore)

    # ------------------------------------------------------------------
    # API 页
    # ------------------------------------------------------------------
    def _build_api_tab(self) -> None:
        f = self.tab_api
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 16, 16, 16)

        title = QLabel("API 设置（OpenAI 兼容格式）")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)
        desc = QLabel("支持任意 OpenAI 兼容接口（DeepSeek / Moonshot / OpenRouter / 本地 vLLM 等）："
                      "填写 Base URL + API Key + 模型名即可。")
        desc.setWordWrap(True)
        desc.setMinimumHeight(40)
        lay.addWidget(desc)

        form = QFormLayout()
        # Key
        key_row = QWidget(f)
        key_lay = QHBoxLayout(key_row)
        key_lay.setContentsMargins(0, 0, 0, 0)
        self.edit_api_key = QLineEdit(key_row)
        self.edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        key_lay.addWidget(self.edit_api_key, 1)
        self.cb_show_key = QCheckBox("显示", key_row)
        self.cb_show_key.toggled.connect(self._toggle_key_show)
        key_lay.addWidget(self.cb_show_key)
        form.addRow("API Key:", key_row)
        self.cb_remember_key = QCheckBox("记住 API Key（保存到用户目录，不会写入项目）")
        self.cb_remember_key.setChecked(True)
        form.addRow("", self.cb_remember_key)

        # Base URL
        self.edit_api_base = QLineEdit("https://api.deepseek.com/v1")
        form.addRow("接口地址:", self.edit_api_base)
        base_hint = QLabel("例：DeepSeek https://api.deepseek.com/v1 · OpenAI https://api.openai.com/v1 · 本地 http://127.0.0.1:8000/v1")
        base_hint.setWordWrap(True)
        base_hint.setStyleSheet("color: #888;")
        form.addRow("", base_hint)

        # Model
        self.cb_model = QComboBox()
        self.cb_model.setEditable(True)
        self.cb_model.addItems([
            "deepseek-chat", "deepseek-reasoner", "gpt-4o", "gpt-4o-mini",
            "moonshot-v1-8k", "qwen-plus", "qwen-max", "glm-4", "claude-3-5-sonnet",
        ])
        self.cb_model.setCurrentText("deepseek-chat")
        form.addRow("模型:", self.cb_model)

        # Temperature + timeout
        temp_row = QWidget(f)
        temp_lay = QHBoxLayout(temp_row)
        temp_lay.setContentsMargins(0, 0, 0, 0)
        self.sp_temperature = QDoubleSpinBox(temp_row)
        self.sp_temperature.setRange(0.0, 2.0)
        self.sp_temperature.setSingleStep(0.1)
        self.sp_temperature.setDecimals(1)
        self.sp_temperature.setValue(0.7)
        temp_lay.addWidget(self.sp_temperature)
        temp_lay.addWidget(QLabel("超时(秒):"))
        self.sp_timeout = QSpinBox(temp_row)
        self.sp_timeout.setRange(10, 600)
        self.sp_timeout.setValue(120)
        temp_lay.addWidget(self.sp_timeout)
        temp_lay.addStretch(1)
        form.addRow("Temperature:", temp_row)

        # Reasoning
        self.cb_reasoning = QComboBox()
        self.cb_reasoning.addItems(["none", "low", "medium", "high"])
        self.cb_reasoning.setCurrentText("none")
        form.addRow("思考模式:", self.cb_reasoning)
        re_hint = QLabel("（reasoning_effort，不支持的平台自动忽略；none 更快更省）")
        re_hint.setWordWrap(True)
        re_hint.setStyleSheet("color: #888;")
        form.addRow("", re_hint)

        lay.addLayout(form)

        btn_row = QHBoxLayout()
        self.btn_test = QPushButton("测试连接", f)
        self.btn_test.clicked.connect(self._on_test_api)
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(QLabel("（测试会调用一次模型，消耗少量额度）"))
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        lay.addStretch(1)

    def _toggle_key_show(self) -> None:
        self.edit_api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if self.cb_show_key.isChecked() else QLineEdit.EchoMode.Password
        )

    # ------------------------------------------------------------------
    # 高级页
    # ------------------------------------------------------------------
    def _build_adv_tab(self) -> None:
        from ..config_merge import load_user_config, merge_with_defaults

        f = self.tab_adv
        outer = QVBoxLayout(f)
        outer.setContentsMargins(8, 8, 8, 8)

        # 顶部按钮
        btns = QHBoxLayout()
        self.btn_save_cfg = QPushButton("💾 保存设置", f)
        self.btn_save_cfg.setObjectName("success")
        self.btn_save_cfg.clicked.connect(self._on_save_config)
        btns.addWidget(self.btn_save_cfg)
        self.btn_reset_cfg = QPushButton("恢复默认", f)
        self.btn_reset_cfg.clicked.connect(self._on_reset_config)
        btns.addWidget(self.btn_reset_cfg)
        self.lbl_cfg_status = QLabel("")
        btns.addWidget(self.lbl_cfg_status)
        btns.addStretch(1)
        outer.addLayout(btns)

        # 主体：左侧章节导航 + 右侧分页
        from .i18n import SECTIONS
        from PySide6.QtWidgets import QListWidget, QStackedWidget, QSplitter

        split = QSplitter(Qt.Orientation.Horizontal, f)
        outer.addWidget(split, 1)

        # 左：章节列表
        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 4, 0)
        left_lay.addWidget(QLabel("配置章节"))
        self.section_list = QListWidget(left)
        self.section_list.setFixedWidth(150)
        self.section_list.currentRowChanged.connect(self._on_section_change)
        left_lay.addWidget(self.section_list, 1)
        split.addWidget(left)

        # 右：分页
        self.section_stack = QStackedWidget(split)
        split.addWidget(self.section_stack)
        split.setSizes([150, 820])
        self._section_keys = [keys for _, keys in SECTIONS]
        for title, _ in SECTIONS:
            self.section_list.addItem(title)

        # 读取生效配置
        user_cfg = load_user_config()
        merged = merge_with_defaults(self._gen_defaults, user_cfg)
        anchors_over = user_cfg.get("creative_anchors_override")
        self._build_adv_form(merged, anchors_over if isinstance(anchors_over, dict) else {})
        if self.section_list.count() > 0:
            self.section_list.setCurrentRow(0)

    def _on_section_change(self, row: int) -> None:
        if 0 <= row < self.section_stack.count():
            self.section_stack.setCurrentIndex(row)

    def _build_adv_form(self, merged_gen: dict[str, Any], anchors_over: dict[str, Any]) -> None:
        """按章节构建高级页：左侧章节 → 右侧分页（每章一个滚动页）。"""
        from .. import yaml_comments
        from ..config_merge import merge_with_defaults
        from .i18n import SECTIONS, KEY_NAMES

        help_map = yaml_comments.build_help_map(config.GENERATION_CONFIG_FILE)
        anchor_help = yaml_comments.build_help_map(config.CREATIVE_ANCHORS_FILE)
        merged_help = dict(help_map)
        merged_help.update(anchor_help)

        # 创意锚点配置
        try:
            import yaml as _yaml

            with config.CREATIVE_ANCHORS_FILE.open("r", encoding="utf-8") as af:
                anchors_cfg = _yaml.safe_load(af) or {}
        except (OSError, ValueError):
            anchors_cfg = {}
        if anchors_over:
            anchors_cfg = merge_with_defaults(anchors_cfg, anchors_over)
        self._anchor_top_keys = list(anchors_cfg.keys())

        # 清空 stack
        while self.section_stack.count():
            w = self.section_stack.widget(0)
            self.section_stack.removeWidget(w)
            w.deleteLater()

        # 危险区（章节内默认折叠的小节）
        # 章节化后不再需要折叠：所有小节直接平铺显示
        self.adv_builder = ConfigFormBuilder(None, merged_help, collapsed_paths=set())
        self.adv_builder.collapsibles = []
        self._adv_collapsibles: list[Any] = []

        def _group_title(parent: QWidget, title: str, help_text: str) -> QLabel:
            lbl = QLabel(title, parent)
            lbl.setObjectName("groupTitle")
            if help_text:
                attach_tooltip(lbl, help_text)
            return lbl

        for title, keys in SECTIONS:
            page = QWidget(self.section_stack)
            page_lay = QVBoxLayout(page)
            page_lay.setContentsMargins(8, 4, 8, 8)
            page_lay.setSpacing(2)
            head = QLabel(title)
            head.setObjectName("sectionTitle")
            page_lay.addWidget(head)

            scroll = QScrollArea(page)
            scroll.setWidgetResizable(True)
            page_lay.addWidget(scroll, 1)
            inner = QWidget(scroll)
            inner.setMinimumSize(0, 0)
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(4, 4, 8, 4)
            inner_lay.setSpacing(2)
            scroll.setWidget(inner)

            if "__anchors__" in keys:
                # 创意锚点章节：整体懒加载（78 条一次性构建较重），内部 7 类平铺
                def _build_anchors(container: QWidget, _anchors=anchors_cfg) -> None:
                    for cat, items in _anchors.items():
                        from .i18n import FIELD_NAMES
                        cat_title = FIELD_NAMES.get(cat, cat)
                        cat_help = merged_help.get(cat, {}).get("help", "")
                        grp = _group_title(container, f"{cat_title}（{len(items)} 个）", cat_help or f"配置键：{cat}")
                        container.layout().addWidget(grp)
                        sub = QWidget(container)
                        sub_lay = QVBoxLayout(sub)
                        sub_lay.setContentsMargins(16, 0, 0, 0)
                        self.adv_builder.build_dict({cat: items}, "", sub)
                        container.layout().addWidget(sub)

                # 章节内直接放一个占位提示 + 构建回调（用普通 QWidget 承载）
                placeholder = QLabel("点击「展开锚点配置」加载 78 个创意锚点", inner)
                placeholder.setStyleSheet("color: #888; padding: 8px;")
                inner_lay.addWidget(placeholder)
                btn_load = QPushButton("展开锚点配置", inner)
                btn_load.setObjectName("primary")

                def _do_load(_checked: bool = False, _ph=placeholder, _bl=btn_load) -> None:
                    _ph.deleteLater()
                    _bl.deleteLater()
                    container = QWidget(inner)
                    container_lay = QVBoxLayout(container)
                    container_lay.setContentsMargins(0, 0, 0, 0)
                    _build_anchors(container)
                    inner_lay.addWidget(container)

                btn_load.clicked.connect(_do_load)
                inner_lay.addWidget(btn_load)
            else:
                for key in keys:
                    if key in merged_gen:
                        key_title = KEY_NAMES.get(key, key)
                        sec_help = merged_help.get(key, {}).get("help", "")
                        rich = f"配置键：{key}\n\n{sec_help}" if sec_help else f"配置键：{key}"
                        # 嵌套 dict 才加分组标题；叶子顶层键直接平铺（避免标题重复）
                        if isinstance(merged_gen[key], dict):
                            grp = _group_title(inner, f"{key_title}（{key}）", rich)
                            inner_lay.addWidget(grp)
                            content = QWidget(inner)
                            content_lay = QVBoxLayout(content)
                            content_lay.setContentsMargins(16, 0, 0, 0)
                            self.adv_builder.build_dict({key: merged_gen[key]}, "", content)
                            inner_lay.addWidget(content)
                        else:
                            self.adv_builder.build_dict({key: merged_gen[key]}, "", inner)
            inner_lay.addStretch(1)
            self.section_stack.addWidget(page)

        # 同步生成页参数
        self._sync_adv_vars(merged_gen)

    def _sync_adv_vars(self, merged: dict[str, Any]) -> None:
        """同步生成页依赖的顶层参数（高级页章节化后仍保持兼容）。"""
        # 生成页参数在 _collect_config 中从表单读取；这里仅为兼容旧调用保留
        pass

    # ------------------------------------------------------------------
    # 配置页
    # ------------------------------------------------------------------
    def _build_profiles_tab(self) -> None:
        from .. import config_presets as cp

        f = self.tab_profiles
        lay = QVBoxLayout(f)
        lay.setContentsMargins(12, 12, 12, 12)
        desc = QLabel("配置预设：多套生成参数可保存/切换/导入/导出，用于按不同目标自由生成提示词。")
        desc.setWordWrap(True)
        desc.setObjectName("hint")
        lay.addWidget(desc)

        split = QSplitter(Qt.Orientation.Horizontal, f)
        lay.addWidget(split, 1)

        # 左: 列表
        left = QWidget(split)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        pt = QLabel("预设列表")
        pt.setObjectName("sectionTitle")
        left_lay.addWidget(pt)
        self.profile_list = QListWidget(left)
        self.profile_list.itemSelectionChanged.connect(self._on_profile_select)
        left_lay.addWidget(self.profile_list, 1)
        split.addWidget(left)

        # 右: 操作 + 详情
        right = QWidget(split)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        ot = QLabel("操作")
        ot.setObjectName("sectionTitle")
        right_lay.addWidget(ot)

        op1 = QHBoxLayout()
        for text, objname, handler in [
            ("➕ 新建", "success", self._on_profile_new),
            ("⧉ 复制", "", self._on_profile_duplicate),
            ("✏ 重命名", "", self._on_profile_rename),
            ("🗑 删除", "danger", self._on_profile_delete),
        ]:
            b = QPushButton(text, right)
            if objname:
                b.setObjectName(objname)
            b.clicked.connect(handler)
            op1.addWidget(b)
        right_lay.addLayout(op1)

        op2 = QHBoxLayout()
        b_activate = QPushButton("☑ 切换到此预设", right)
        b_activate.setObjectName("primary")
        b_activate.clicked.connect(self._on_profile_activate)
        op2.addWidget(b_activate)
        b_save = QPushButton("💾 保存当前到预设", right)
        b_save.setObjectName("success")
        b_save.clicked.connect(self._on_profile_save)
        op2.addWidget(b_save)
        right_lay.addLayout(op2)

        op3 = QHBoxLayout()
        b_export = QPushButton("📤 导出", right)
        b_export.clicked.connect(self._on_profile_export)
        op3.addWidget(b_export)
        b_import = QPushButton("📥 导入", right)
        b_import.clicked.connect(self._on_profile_import)
        op3.addWidget(b_import)
        right_lay.addLayout(op3)

        dt = QLabel("当前预设详情")
        dt.setObjectName("sectionTitle")
        right_lay.addWidget(dt)
        self.profile_detail = QPlainTextEdit(right)
        self.profile_detail.setReadOnly(True)
        right_lay.addWidget(self.profile_detail, 1)
        self.lbl_active_profile = QLabel("")
        right_lay.addWidget(self.lbl_active_profile)
        split.addWidget(right)
        split.setSizes([280, 480])

        self._refresh_profiles()

    def _refresh_profiles(self) -> None:
        from .. import config_presets as cp

        active = cp.get_active_name()
        self.profile_list.clear()
        for name in cp.list_profile_names():
            item = QListWidgetItem(name)
            if name == active:
                item.setSelected(True)
            self.profile_list.addItem(item)
        self.lbl_active_profile.setText(f"当前激活：{active}")
        self._show_profile_detail(active)

    def _selected_profile(self) -> str | None:
        items = self.profile_list.selectedItems()
        return items[0].text() if items else None

    def _show_profile_detail(self, name: str) -> None:
        from .. import config_presets as cp

        profile = cp.get_profile(name)
        if profile is None:
            self.profile_detail.setPlainText("（无）")
            return
        gen = profile.get("gen") or {}
        anchors = profile.get("anchors") or {}
        lines = [f"预设：{name}", "", "【生成配置覆盖】"]
        if gen:
            for k, v in gen.items():
                lines.append(f"  {k}: {self._fmt_value(v)}")
        else:
            lines.append("  （使用默认）")
        lines.append("")
        lines.append("【创意锚点覆盖】")
        if anchors:
            for cat, items in anchors.items():
                lines.append(f"  {cat}: {len(items)} 个锚点")
        else:
            lines.append("  （使用默认）")
        self.profile_detail.setPlainText("\n".join(lines))

    @staticmethod
    def _fmt_value(v: Any) -> str:
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k}: {v[k]}" for k in list(v)[:4]) + ("…" if len(v) > 4 else "") + "}"
        if isinstance(v, list):
            return f"[{len(v)} 项]"
        return str(v)

    def _on_profile_select(self) -> None:
        name = self._selected_profile()
        if name:
            self._show_profile_detail(name)

    # ---- 配置页操作（复用 tkinter 版逻辑）----
    def _ask_name(self, title: str, prompt: str, initial: str) -> str:
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(340)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(prompt))
        edit = QLineEdit(initial, dlg)
        lay.addWidget(edit)
        btns = QHBoxLayout()
        ok_btn = QPushButton("确定", dlg)
        ok_btn.setObjectName("success")
        cancel_btn = QPushButton("取消", dlg)

        def _ok() -> None:
            dlg.accept()

        def _cancel() -> None:
            dlg.reject()

        ok_btn.clicked.connect(_ok)
        cancel_btn.clicked.connect(_cancel)
        btns.addStretch(1)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        lay.addLayout(btns)
        edit.setFocus()
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return edit.text().strip()
        return ""

    def _on_profile_new(self) -> None:
        from .. import config_presets as cp

        name = self._ask_name("新建预设", "预设名称：", "新预设")
        if not name:
            return
        if not cp.create_profile(name):
            QMessageBox.warning(self, "新建失败", "预设名称已存在或无效。")
            return
        self._refresh_profiles()
        self._log(f"已新建空预设「{name}」。")

    def _on_profile_duplicate(self) -> None:
        from .. import config_presets as cp

        name = self._selected_profile()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个预设。")
            return
        new_name = self._ask_name("复制预设", f"复制「{name}」为：", f"{name} 副本")
        if not new_name:
            return
        profile = cp.get_profile(name)
        if profile and cp.create_profile(new_name, profile.get("gen"), profile.get("anchors")):
            self._refresh_profiles()
            self._log(f"已复制「{name}」→「{new_name}」。")
        else:
            QMessageBox.warning(self, "复制失败", "预设名称已存在或无效。")

    def _on_profile_rename(self) -> None:
        from .. import config_presets as cp

        name = self._selected_profile()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个预设。")
            return
        if name == cp.DEFAULT_PROFILE:
            QMessageBox.information(self, "提示", "「默认」预设不可重命名。")
            return
        new_name = self._ask_name("重命名预设", f"将「{name}」重命名为：", name)
        if not new_name:
            return
        if cp.rename_profile(name, new_name):
            self._refresh_profiles()
            self._log(f"已重命名「{name}」→「{new_name}」。")
        else:
            QMessageBox.warning(self, "重命名失败", "名称无效或已存在。")

    def _on_profile_delete(self) -> None:
        from .. import config_presets as cp

        name = self._selected_profile()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个预设。")
            return
        if name == cp.DEFAULT_PROFILE:
            QMessageBox.information(self, "提示", "「默认」预设不可删除。")
            return
        if QMessageBox.question(self, "删除预设", f"确定删除预设「{name}」？") != QMessageBox.StandardButton.Yes:
            return
        cp.delete_profile(name)
        self._refresh_profiles()
        self._log(f"已删除预设「{name}」。")

    def _on_profile_activate(self) -> None:
        from .. import config_presets as cp

        name = self._selected_profile()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个预设。")
            return
        current_active = cp.get_active_name()
        if self._has_pending_changes():
            if QMessageBox.question(
                self, "切换预设",
                f"当前高级页有未保存的修改。\n是否先保存到当前预设「{current_active}」再切换？\n"
                "（选“No”将丢弃当前修改）",
            ) == QMessageBox.StandardButton.Yes:
                self._save_current_to_profile(current_active)
            else:
                self._log(f"丢弃当前修改，切换到「{name}」。")
        if cp.set_active(name):
            self._refresh_profiles()
            self._rebuild_adv_form_from_profile(name)
            self._log(f"已切换到预设「{name}」，生成将使用该配置。")
            Toast.show(self, f"已切换到预设「{name}」", kind="success")
        else:
            Toast.show(self, "切换预设失败", kind="error")
            QMessageBox.warning(self, "切换失败", "无法激活该预设。")

    def _on_profile_save(self) -> None:
        name = self._selected_profile() or "默认"
        self._save_current_to_profile(name)
        self._refresh_profiles()
        self._log(f"当前配置已保存到预设「{name}」。")

    def _save_current_to_profile(self, name: str) -> None:
        from .. import config_presets as cp

        gen, anchors = self._collect_profile_content()
        cp.save_profile(name, gen, anchors)

    def _has_pending_changes(self) -> bool:
        from .. import config_presets as cp

        active = cp.get_active_name()
        profile = cp.get_profile(active) or {}
        gen, anchors = self._collect_profile_content()
        return gen != (profile.get("gen") or {}) or anchors != (profile.get("anchors") or {})

    def _rebuild_adv_form_from_profile(self, name: str) -> None:
        from .. import config_presets as cp
        from ..config_merge import merge_with_defaults

        profile = cp.get_profile(name) or {}
        gen_over = profile.get("gen") or {}
        anchors_over = profile.get("anchors") or {}
        merged_gen = merge_with_defaults(self._gen_defaults, gen_over)
        self._build_adv_form(merged_gen, anchors_over)
        self._invalidate_engine_cache()

    def _on_profile_export(self) -> None:
        from .. import config_presets as cp

        name = self._selected_profile()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个预设。")
            return
        payload = cp.export_profile(name)
        if payload is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出预设", f"{name}.yaml", "YAML 配置 (*.yaml);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            import yaml

            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
            self._log(f"已导出预设「{name}」到 {path}")
            QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _on_profile_import(self) -> None:
        from .. import config_presets as cp

        path, _ = QFileDialog.getOpenFileName(
            self, "导入预设", "", "YAML 配置 (*.yaml *.yml);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            import yaml

            with open(path, "r", encoding="utf-8") as f:
                payload = yaml.safe_load(f) or {}
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "导入失败", f"无法读取文件：{exc}")
            return
        if not cp.validate_profile_payload(payload):
            QMessageBox.critical(self, "导入失败", "文件不是有效的预设导出（缺少 gen/anchors 字段）。")
            return
        default_name = str(payload.get("profile_name") or "导入的预设")
        new_name = self._ask_name("导入预设", "导入为预设名：", default_name)
        if not new_name:
            return
        ok, result = cp.import_profile(payload, new_name)
        if ok:
            self._refresh_profiles()
            self._log(f"已导入预设「{result}」。")
        else:
            QMessageBox.critical(self, "导入失败", result)

    def _on_expand_all(self) -> None:
        for c in getattr(self, "_adv_collapsibles", []):
            if not c.is_open():
                c._toggle()

    def _on_collapse_all(self) -> None:
        for c in getattr(self, "_adv_collapsibles", []):
            if c.is_open():
                c._toggle()

    # ------------------------------------------------------------------
    # 日志页
    # ------------------------------------------------------------------
    def _build_log_tab(self) -> None:
        f = self.tab_log
        lay = QVBoxLayout(f)
        lay.setContentsMargins(8, 8, 8, 8)
        ltitle = QLabel("运行日志")
        ltitle.setObjectName("sectionTitle")
        lay.addWidget(ltitle)
        self.txt_log = QPlainTextEdit(f)
        self.txt_log.setReadOnly(True)
        lay.addWidget(self.txt_log, 1)
        row = QHBoxLayout()
        btn_open = QPushButton("打开输出文件夹", f)
        btn_open.clicked.connect(self._open_output_folder)
        row.addWidget(btn_open)
        self.lbl_output_path = QLabel("")
        row.addWidget(self.lbl_output_path)
        row.addStretch(1)
        lay.addLayout(row)
        self._update_output_path_label()

    def _update_output_path_label(self) -> None:
        out = self.edit_output_dir.text() if hasattr(self, "edit_output_dir") else app_output_dir()
        self.lbl_output_path.setText(out)

    def _open_output_folder(self) -> None:
        out = self.edit_output_dir.text()
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
            self.edit_api_base.setText(s["api_base"])
        if s.get("model"):
            self.cb_model.setCurrentText(s["model"])
        if "temperature" in s:
            self.sp_temperature.setValue(float(s["temperature"]))
        if "timeout" in s:
            self.sp_timeout.setValue(int(s["timeout"]))
        if s.get("reasoning"):
            self.cb_reasoning.setCurrentText(s["reasoning"])
        if s.get("output_dir"):
            self.edit_output_dir.setText(s["output_dir"])
        if s.get("output_name"):
            self.edit_output_name.setText(s["output_name"])
        if s.get("max_rating") in RATING_LABELS:
            self.cb_rating.setCurrentText(RATING_LABELS[s["max_rating"]])
        if s.get("theme_hint") is not None:
            self.edit_theme.setText(s["theme_hint"])
        if s.get("forced_tags") is not None:
            self.edit_forced.setText(s["forced_tags"])
        if s.get("forbidden_tags") is not None:
            self.edit_forbidden.setText(s["forbidden_tags"])
        if s.get("remember_key"):
            self.cb_remember_key.setChecked(True)
            if s.get("api_key"):
                self.edit_api_key.setText(s["api_key"])

    def _persist_settings(self) -> None:
        s = {
            "api_base": self.edit_api_base.text(),
            "model": self.cb_model.currentText(),
            "temperature": self.sp_temperature.value(),
            "timeout": self.sp_timeout.value(),
            "reasoning": self.cb_reasoning.currentText(),
            "output_dir": self.edit_output_dir.text(),
            "output_name": self.edit_output_name.text(),
            "max_rating": RATING_VALUES.get(self.cb_rating.currentText(), "r15"),
            "theme_hint": self.edit_theme.text(),
            "forced_tags": self.edit_forced.text(),
            "forbidden_tags": self.edit_forbidden.text(),
            "remember_key": bool(self.cb_remember_key.isChecked()),
        }
        if self.cb_remember_key.isChecked() and self.edit_api_key.text():
            s["api_key"] = self.edit_api_key.text()
        _save_settings(s)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _sync_seed_ui(self) -> None:
        fixed = self.rb_seed_fixed.isChecked()
        self.sp_seed.setEnabled(fixed)

    def _on_rating_change(self) -> None:
        rating = RATING_VALUES.get(self.cb_rating.currentText(), "r15")
        if self._running:
            self._log("生成进行中，评级保持不变。")
            current = self._resources.get("max_rating", "r15") if self._resources else "r15"
            self.cb_rating.setCurrentText(RATING_LABELS.get(current, RATING_LABELS["r15"]))
            return
        if rating in ("r18", "r18g") and not self._r18_confirmed:
            ok = QMessageBox.warning(
                self, "成人内容确认",
                f"你选择了【{rating}】档位。\n\n"
                "该档位会生成成人向（NSFW）内容。\n"
                "生成器已内置硬排除规则（性行为、猎奇血腥、兽化、男性角色等），\n"
                "但输出仍可能包含裸露等内容，请确保你已满 18 岁且合法使用。\n\n"
                "是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ok != QMessageBox.StandardButton.Yes:
                self.cb_rating.setCurrentText(RATING_LABELS["r15"])
                return
            self._r18_confirmed = True
        self._log(f"内容分级已切换为 {rating}")
        if self._resources is not None and self._resources.get("max_rating") != rating:
            self._resources = None
            self._ensure_resources()

    def _collect_config(self) -> GenConfig:
        rating = RATING_VALUES.get(self.cb_rating.currentText(), "r15")
        seed = None
        if self.rb_seed_fixed.isChecked():
            seed = int(self.sp_seed.value())
        return GenConfig(
            max_rating=rating,
            count=max(int(self.sp_count.value()), 1),
            min_tags=50,
            max_tags=75,
            theme_hint=self.edit_theme.text().strip(),
            extra_requirements=self.txt_extra.toPlainText().strip(),
            forced_tags=self.edit_forced.text().strip(),
            forbidden_tags=self.edit_forbidden.text().strip(),
            seed=seed,
            workers=4,
            temperature=float(self.sp_temperature.value()),
            max_tokens=1000,
            timeout=float(self.sp_timeout.value()),
            max_parse_retries=2,
            reasoning_effort=self.cb_reasoning.currentText() or None,
            output_dir=self.edit_output_dir.text().strip() or app_output_dir(),
            output_name=self.edit_output_name.text().strip() or "random_prompts",
            api_key=self.edit_api_key.text().strip() or None,
            api_base=self.edit_api_base.text().strip() or None,
            model=self.cb_model.currentText().strip() or None,
            creative_anchors_enabled=bool(self.cb_anchors.isChecked()),
            proxies=None,
        )

    def _apply_switch_overrides(self, cfg: GenConfig) -> GenConfig:
        gen_cfg = self._resources["gen_cfg"]
        gen_cfg["creative_anchors"] = {
            **gen_cfg.get("creative_anchors", {}),
            "enabled": bool(self.cb_anchors.isChecked()),
        }
        gen_cfg["multi_character"] = {
            **gen_cfg.get("multi_character", {}),
            "enabled": bool(self.cb_multi.isChecked()),
        }
        return cfg

    # ------------------------------------------------------------------
    # 高级页操作
    # ------------------------------------------------------------------
    def _on_save_config(self) -> None:
        from .. import config_presets as cp
        from ..config_merge import save_user_config

        gen, anchors = self._collect_profile_content()
        user_part = dict(gen)
        if anchors:
            user_part["creative_anchors_override"] = anchors
        ok = save_user_config(user_part)
        if ok:
            active = cp.get_active_name()
            cp.save_profile(active, gen, anchors)
            self.lbl_cfg_status.setText("已保存 ✓")
            self._log(f"高级设置已保存到预设「{active}」（下次生成生效）。")
            self._invalidate_engine_cache()
            self._refresh_profiles()
            self._flash_button(self.btn_save_cfg, "✓ 已保存")
            Toast.show(self, f"配置已保存到预设「{active}」", kind="success")
        else:
            self.lbl_cfg_status.setText("保存失败")
            Toast.show(self, "保存失败", kind="error")
            QMessageBox.critical(self, "保存失败", "无法写入用户配置文件。")

    def _diff_user(self, collected: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
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
        from ..gui_engine import _cache

        _cache.pop("gen_cfg", None)
        for k in list(_cache.keys()):
            if k.startswith("r_"):
                _cache.pop(k, None)
        self._log("配置缓存已重置，下次生成将使用新设置。")

    def _on_reset_config(self) -> None:
        from ..config_merge import clear_user_config

        if QMessageBox.question(
            self, "恢复默认",
            "将删除全部自定义设置并恢复默认配置。\n（API Key 不受影响）\n确定继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        clear_user_config()
        self.lbl_cfg_status.setText("已恢复默认 ✓")
        self._log("已删除用户配置，恢复默认。")
        self._rebuild_adv_form()

    def _rebuild_adv_form(self) -> None:
        self._build_adv_form(self._gen_defaults, {})

    def _collect_profile_content(self) -> tuple[dict[str, Any], dict[str, Any]]:
        collected = self.adv_builder.get_dict()
        anchor_top_keys = set(getattr(self, "_anchor_top_keys", []))
        gen_collected: dict[str, Any] = {}
        anchor_collected: dict[str, Any] = {}
        for key, value in collected.items():
            if key in anchor_top_keys:
                anchor_collected[key] = value
            else:
                gen_collected[key] = value
        gen_user = self._diff_user(gen_collected, self._gen_defaults)
        anchors_user: dict[str, Any] = {}
        if anchor_collected:
            try:
                import yaml as _yaml

                with config.CREATIVE_ANCHORS_FILE.open("r", encoding="utf-8") as af:
                    default_anchors = _yaml.safe_load(af) or {}
                if anchor_collected != default_anchors:
                    anchors_user = anchor_collected
            except (OSError, ValueError):
                anchors_user = anchor_collected
        return gen_user, anchors_user

    # ------------------------------------------------------------------
    # 预览 / 生成
    # ------------------------------------------------------------------
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
            Toast.show(self, "预览失败", kind="error")
            QMessageBox.critical(self, "预览失败", str(exc))
            return
        self._show_preview_window(res)
        Toast.show(self, "预览样本已生成", kind="success")

    def _show_preview_window(self, res: dict[str, Any]) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"预览样本 (seed={res['seed']})")
        dlg.resize(760, 620)
        lay = QVBoxLayout(dlg)
        info = QLabel(
            f"Seed: {res['seed']}    分级: {res['safety']}    多角色: {'是' if res['is_multi'] else '否'}\n"
            f"角色: {res['character_tag'] or '（无）'}"
        )
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addWidget(QLabel("抽样标签："))
        txt_sampled = QPlainTextEdit(dlg)
        txt_sampled.setPlainText(res["sampled_text"])
        txt_sampled.setReadOnly(True)
        txt_sampled.setMaximumHeight(120)
        lay.addWidget(txt_sampled)
        lay.addWidget(QLabel("渲染后的用户提示词（将发送给 API）："))
        txt_prompt = QPlainTextEdit(dlg)
        txt_prompt.setPlainText(res["user_prompt"])
        txt_prompt.setReadOnly(True)
        lay.addWidget(txt_prompt, 1)
        btn_copy = QPushButton("复制全文", dlg)
        btn_copy.clicked.connect(lambda: self._copy_to_clipboard(res["user_prompt"]))
        lay.addWidget(btn_copy, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _ensure_resources(self) -> bool:
        rating = RATING_VALUES.get(self.cb_rating.currentText(), "r15")
        if self._resources is not None:
            if self._resources.get("max_rating") == rating:
                return True
            self._log(f"检测到评级切换为 {rating}，重新预过滤知识库…")
            self._resources = None
        if self._resource_error:
            QMessageBox.critical(self, "加载失败", self._resource_error)
            return False
        if self._load_thread is not None and self._load_thread.is_alive():
            self._log("资源仍在加载中，请稍候…")
            return False
        self.lbl_status.setText("正在加载知识库资源（首次约需 10~30 秒）…")
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
        if not self.edit_api_key.text().strip():
            QMessageBox.warning(self, "缺少 API Key", "请先在「API 设置」页填写你的 API Key。")
            self._log("未填写 API Key，已取消生成。")
            return
        if cfg.seed is None:
            cfg.seed = random.randint(0, 2**32 - 1)
        self._gen_config = cfg
        self._persist_settings()
        self._log(f"开始生成 {cfg.count} 条（{cfg.max_rating}）…")
        if not self._ensure_resources():
            self._log("等待资源加载完成…")
            self._pending_start = True
            return
        self._launch_generation(cfg)

    def _launch_generation(self, cfg: GenConfig) -> None:
        if self._running:
            return
        self._running = True
        self._cancel_event.clear()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setValue(0)
        self.lbl_progress.setText("0%")
        self.tree.clear()
        self._result_rows = []
        self.lbl_status.setText("正在生成…")
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
            self.btn_cancel.setEnabled(False)

    def _on_test_api(self) -> None:
        key = self.edit_api_key.text().strip()
        if not key:
            QMessageBox.warning(self, "缺少 API Key", "请先填写 API Key。")
            return
        self.btn_test.setEnabled(False)
        self.lbl_status.setText("正在测试连接…")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self) -> None:
        try:
            from .. import client as c

            model = self.cb_model.currentText().strip() or None
            base = self.edit_api_base.text().strip() or None
            resp = c.call_deepseek(
                system_prompt="ping",
                user_prompt="Reply with exactly: pong",
                api_key=self.edit_api_key.text().strip(),
                api_base=base,
                model=model,
                temperature=0,
                max_tokens=8,
                timeout=min(float(self.sp_timeout.value()), 60),
            )
            msg = (resp.get("choices") or [{}])[0].get("message", {})
            content = (msg.get("content") or "").strip()
            self._queue.put(("test_result", content or "(空响应)"))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("test_error", str(exc)))

    # ------------------------------------------------------------------
    # 结果展示
    # ------------------------------------------------------------------
    def _add_result_row(self, record: dict[str, Any]) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        version_1 = record.get("version_1", "")
        tag_count = len([t for t in version_1.split(", ") if t.strip()])
        preview_txt = (version_1[:120] + "…") if len(version_1) > 120 else version_1
        item = QListWidgetItem(
            f"[seed={record.get('seed', '')}] [{record.get('max_rating', '')}] "
            f"[{tag_count} tags] {preview_txt}"
        )
        self.tree.addItem(item)
        self._result_rows.append({"version_1": version_1, "record": record})

    def _on_row_double(self, item: Any) -> None:
        idx = self.tree.row(item)
        if idx >= len(self._result_rows):
            return
        row = self._result_rows[idx]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"提示词全文 (seed={row['record'].get('seed', '')})")
        dlg.resize(780, 520)
        lay = QVBoxLayout(dlg)
        txt = QPlainTextEdit(dlg)
        txt.setPlainText(row["version_1"])
        txt.setReadOnly(True)
        lay.addWidget(txt, 1)
        btn = QPushButton("复制", dlg)
        btn.clicked.connect(lambda: self._copy_to_clipboard(row["version_1"]))
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def _copy_to_clipboard(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self._log("已复制到剪贴板。")
        Toast.show(self, "已复制到剪贴板 ✓", kind="success")

    # ------------------------------------------------------------------
    # 队列轮询（Qt 信号桥）
    # ------------------------------------------------------------------
    def _start_poll(self) -> Any:
        from PySide6.QtCore import QTimer

        timer = QTimer(self)
        timer.timeout.connect(self._poll_queue)
        timer.start(120)
        return timer

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                self._bridge.message.emit(msg)
        except queue.Empty:
            pass

    @Slot(tuple)
    def _on_queue_message(self, msg: tuple) -> None:
        kind = msg[0]
        if kind == "log":
            self._log(msg[1])
        elif kind == "progress":
            self._on_progress(msg[1])
        elif kind == "resources":
            self._resources = msg[1]
            self._resource_error = None
            self.lbl_status.setText("资源加载完成。")
            self._log("知识库资源加载完成。")
            if self._pending_start:
                self._pending_start = False
                cfg = self._gen_config
                want_rating = RATING_VALUES.get(self.cb_rating.currentText(), "r15")
                if cfg is not None and cfg.max_rating == want_rating:
                    self._launch_generation(cfg)
                elif cfg is not None:
                    self._log("评级已变化，重新加载资源…")
                    self._ensure_resources()
        elif kind == "resource_error":
            self._resource_error = msg[1]
            self.lbl_status.setText("资源加载失败。")
            self._log(f"资源加载失败：{msg[1]}")
        elif kind == "batch_done":
            self._on_batch_done(msg[1])
        elif kind == "gen_error":
            self._running = False
            self._reset_buttons()
            self.lbl_status.setText("生成失败。")
            self._log(f"生成失败：{msg[1]}")
            QMessageBox.critical(self, "生成失败", str(msg[1]))
        elif kind == "test_result":
            self.btn_test.setEnabled(True)
            self.lbl_status.setText("连接正常。")
            self._log(f"API 连接测试成功，响应：{msg[1]!r}")
            QMessageBox.information(self, "测试成功", f"API 连接正常。\n模型响应：{msg[1]!r}")
        elif kind == "test_error":
            self.btn_test.setEnabled(True)
            self.lbl_status.setText("连接失败。")
            self._log(f"API 连接测试失败：{msg[1]}")
            QMessageBox.critical(self, "测试失败", str(msg[1]))

    def _on_progress(self, ev: ProgressEvent) -> None:
        if ev.total > 0:
            pct = int(100 * ev.done / ev.total)
            self.progress.setValue(pct)
            self.lbl_progress.setText(f"{ev.done}/{ev.total}")
            self.lbl_status.setText(f"生成中… {ev.done}/{ev.total} 完成，失败 {ev.failed}")

    def _on_batch_done(self, result: Any) -> None:
        self._running = False
        self._reset_buttons()
        self.lbl_status.setText("生成完成。" if not result.canceled else "已停止。")
        for err in result.errors[:20]:
            self._log(f"失败：{err}")
        self._log(
            f"完成：成功 {result.ok} 条，失败 {result.failed} 条"
            + ("（用户停止）" if result.canceled else "")
        )
        self._log(f"JSONL: {result.output_jsonl}")
        self._log(f"TXT:   {result.output_txt}")
        self.lbl_progress.setText(f"{result.ok}/{result.ok + result.failed}")
        if result.ok > 0:
            self.lbl_status.setText(f"完成：{result.ok} 条。")
            QMessageBox.information(
                self, "生成完成",
                f"成功生成 {result.ok} 条，失败 {result.failed} 条。\n\n"
                f"JSONL：{result.output_jsonl}\nTXT：{result.output_txt}",
            )

    def _reset_buttons(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.txt_log.appendPlainText(f"[{ts}] {msg}")

    # ------------------------------------------------------------------
    # 主题 / 关闭
    # ------------------------------------------------------------------
    def _on_theme_change(self, index: int) -> None:
        self._apply_theme(index)
        s = _load_settings()
        s["theme"] = index
        _save_settings(s)
        self._log(f"外观已切换为 {THEME_OPTIONS[index]}。")
        Toast.show(self, f"外观已切换为 {THEME_OPTIONS[index]}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._running:
            self._cancel_event.set()
        super().closeEvent(event)


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
