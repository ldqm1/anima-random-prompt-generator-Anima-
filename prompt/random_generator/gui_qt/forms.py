"""PySide6 动态配置表单（Qt 版 ConfigFormBuilder）。

与 tkinter 版 gui_forms.py 功能等价：
- 按数据类型渲染控件：int→QSpinBox、float→QDoubleSpinBox、bool→QCheckBox、
  短文本→QLineEdit、长文本→QPlainTextEdit、枚举→QComboBox、
  标量列表/对象列表→可增删编辑器、嵌套 dict→可折叠分组；
- 折叠分组支持懒加载（展开时才构建子控件）；
- 全部控件挂悬浮帮助（yaml 注释 / 语义兜底）；
- 收集回 dict（含空 dict/list 保留）。
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import yaml_comments
from .tooltip import attach_tooltip

# 已知枚举字段：路径（点分）→ 可选值列表
ENUM_FIELDS: dict[str, list[str]] = {
    "deepseek.reasoning_effort": ["none", "low", "medium", "high"],
    "r18_topic_control.topics.mode": ["fixed", "probabilistic", "weighted"],
}


class FormField:
    """单个字段的控件状态，用于保存时取值。"""

    def __init__(
        self,
        kind: str,
        widget: QWidget | None = None,
        getter: Callable[[], Any] | None = None,
        setter: Callable[[Any], None] | None = None,
    ) -> None:
        self.kind = kind
        self.widget = widget
        self.getter = getter
        self.setter = setter

    def get(self) -> Any:
        if self.kind == "empty_dict":
            return {}
        if self.kind == "empty_list":
            return []
        if self.getter is not None:
            return self.getter()
        return None

    def set(self, value: Any) -> None:
        if self.setter is not None:
            self.setter(value)


class CollapsibleSection(QFrame):
    """可折叠分组（支持懒加载）。"""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        default_open: bool = True,
        help_text: str = "",
        build_callback: Callable[[QWidget], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("collapsibleSection")
        self._open = default_open
        self._built = build_callback is None
        self._build_callback = build_callback
        self._content: QWidget | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(2)

        # 标题行
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        self._btn = QToolButton(self)
        self._btn.setText(("▾ " if default_open else "▸ ") + title)
        self._btn.setCheckable(False)
        self._btn.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; font-size: 13px;"
            " padding: 2px 4px; text-align: left; }"
            "QToolButton:hover { color: #2c7da0; }"
        )
        self._btn.clicked.connect(self._toggle)
        head.addWidget(self._btn, 1)
        if help_text:
            attach_tooltip(self._btn, help_text)
        self._layout.addLayout(head)

    def _toggle(self) -> None:
        self._open = not self._open
        self._btn.setText(("▾ " if self._open else "▸ ") + self._btn.text()[2:])
        if self._open:
            self._ensure_content()
        elif self._content is not None:
            self._content.hide()

    def _ensure_content(self) -> None:
        if self._built:
            if self._content is not None:
                self._content.show()
            return
        if self._build_callback is not None:
            self._content = QWidget(self)
            self._layout.addWidget(self._content)
            self._build_callback(self._content)
            self._built = True

    def is_open(self) -> bool:
        return self._open


class ListEditor(QWidget):
    """可增删的标量/对象列表编辑器。"""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget,
        item_factory: Callable[[], Any],
        item_schema: str,
        field_cfg: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._item_factory = item_factory
        self._item_schema = item_schema
        self._field_cfg = field_cfg or {}
        self._rows: list[tuple[QWidget, dict[str, FormField] | Any]] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._items_box = QWidget(self)
        self._items_layout = QVBoxLayout(self._items_box)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(2)
        self._layout.addWidget(self._items_box)
        add_btn = QPushButton("+ 添加", self)
        add_btn.setObjectName("success")
        add_btn.clicked.connect(self._add_row)
        self._layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

    def _add_row(self, _checked: bool = False) -> None:
        row_widget = self._make_row(None)
        self._rows.append(row_widget)
        self._items_layout.addWidget(row_widget[0])
        self.changed.emit()

    def _remove_row(self, row_widget: QWidget) -> None:
        for i, (w, _) in enumerate(self._rows):
            if w is row_widget:
                self._rows.pop(i)
                w.deleteLater()
                break
        self.changed.emit()

    def _make_row(self, value: Any) -> tuple[QWidget, dict[str, FormField] | Any]:
        if self._item_schema == "scalar":
            row = QWidget(self._items_box)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(row)
            edit.setText("" if value is None else str(value))
            lay.addWidget(edit, 1)
            del_btn = QPushButton("✕", row)
            del_btn.setFixedWidth(28)
            del_btn.clicked.connect(lambda: self._remove_row(row))
            lay.addWidget(del_btn)
            fields: dict[str, FormField] = {}
            fields["_scalar"] = FormField(
                "str", widget=edit,
                getter=lambda: edit.text().strip(),
                setter=lambda v: edit.setText(str(v)),
            )
            return row, fields
        # 对象行
        default = self._item_factory() if value is None else value
        row = QWidget(self._items_box)
        lay = QVBoxLayout(row)
        lay.setContentsMargins(8, 2, 0, 2)
        lay.setSpacing(1)
        head = QHBoxLayout()
        idx = len(self._rows) + 1
        lbl = QLabel(f"条目 {idx}", row)
        lbl.setStyleSheet("color: #2c7da0; font-weight: bold;")
        head.addWidget(lbl)
        head.addStretch(1)
        del_btn = QPushButton("✕ 删除", row)
        del_btn.setFixedWidth(70)
        del_btn.clicked.connect(lambda: self._remove_row(row))
        head.addWidget(del_btn)
        lay.addLayout(head)
        fields = {}
        if isinstance(default, dict):
            for k, v in default.items():
                help_text = self._field_cfg.get(k) or yaml_comments.semantic_help(k, v)
                field = build_leaf_field(row, k, v, help_text)
                fields[k] = field
        return row, fields

    def set(self, values: list[Any]) -> None:
        for w, _ in self._rows:
            w.deleteLater()
        self._rows = []
        for v in values:
            row = self._make_row(v)
            self._rows.append(row)
            self._items_layout.addWidget(row[0])
        self.changed.emit()

    def get(self) -> list[Any]:
        out: list[Any] = []
        for _, fields in self._rows:
            if "_scalar" in fields:
                val = fields["_scalar"].get()
                if val:
                    out.append(parse_scalar(val))
            else:
                obj = {}
                for k, field in fields.items():
                    obj[k] = field.get()
                out.append(obj)
        return out


def parse_scalar(s: str) -> Any:
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            if s.lower() in ("true", "yes"):
                return True
            if s.lower() in ("false", "no"):
                return False
            return s


def _make_label(parent: QWidget, label: str, help_text: str = "", min_w: int = 100) -> QLabel:
    """自适应宽度的标签：文本宽 + 余量，长键名自动省略并加 tooltip 显示全名。"""
    from PySide6.QtGui import QFontMetrics

    lbl = QLabel(label, parent)
    fm = QFontMetrics(lbl.font())
    text_w = fm.horizontalAdvance(label)
    width = max(min_w, min(text_w + 10, 280))
    lbl.setMinimumWidth(width)
    lbl.setMaximumWidth(320)
    if text_w + 10 > 280:
        # 长标签：省略 + tooltip 全名
        fm_elide = QFontMetrics(lbl.font())
        elided = fm_elide.elidedText(label, Qt.TextElideMode.ElideMiddle, 280)
        lbl.setText(elided)
        attach_tooltip(lbl, f"{label}\n\n{help_text}" if help_text else label)
    elif help_text:
        attach_tooltip(lbl, help_text)
    return lbl


def build_leaf_field(
    parent: QWidget, label: str, value: Any, help_text: str, dotted: str = ""
) -> FormField:
    """构建单个叶子字段控件（int/float/bool/str/enum/list/None）。"""
    enum_values = _enum_for(dotted, label)

    def _row_widget() -> QWidget:
        row = QWidget(parent)
        row._layout = QHBoxLayout(row)  # type: ignore[attr-defined]
        row._layout.setContentsMargins(0, 1, 0, 1)  # type: ignore[attr-defined]
        return row

    if isinstance(value, bool):
        cb = QCheckBox(label, parent)
        cb.setChecked(value)
        if help_text:
            attach_tooltip(cb, help_text)
        return FormField("bool", widget=cb, getter=cb.isChecked, setter=cb.setChecked)

    if isinstance(value, int) and not isinstance(value, bool):
        row = _row_widget()
        lbl = _make_label(row, label, help_text)
        sp = QSpinBox(row)
        sp.setRange(-1000000, 1000000)
        sp.setValue(value)
        row._layout.addWidget(lbl)  # type: ignore[attr-defined]
        row._layout.addWidget(sp)  # type: ignore[attr-defined]
        row._layout.addStretch(1)  # type: ignore[attr-defined]
        row._layout.parentWidget = row  # type: ignore[attr-defined]
        if help_text:
            attach_tooltip(sp, help_text)
        return FormField("int", widget=row, getter=sp.value, setter=sp.setValue)

    if isinstance(value, float):
        row = _row_widget()
        lbl = _make_label(row, label, help_text)
        sp = QDoubleSpinBox(row)
        sp.setRange(-1000000.0, 1000000.0)
        sp.setSingleStep(0.1)
        sp.setDecimals(3)
        sp.setValue(value)
        row._layout.addWidget(lbl)  # type: ignore[attr-defined]
        row._layout.addWidget(sp)  # type: ignore[attr-defined]
        row._layout.addStretch(1)  # type: ignore[attr-defined]
        if help_text:
            attach_tooltip(lbl, help_text)
            attach_tooltip(sp, help_text)
        return FormField("float", widget=row, getter=sp.value, setter=sp.setValue)

    if isinstance(value, str):
        if enum_values:
            row = _row_widget()
            lbl = _make_label(row, label, help_text)
            cb = QComboBox(row)
            cb.addItems(enum_values)
            if value in enum_values:
                cb.setCurrentText(value)
            else:
                cb.setEditable(True)
                cb.setCurrentText(value)
            row._layout.addWidget(lbl)  # type: ignore[attr-defined]
            row._layout.addWidget(cb)  # type: ignore[attr-defined]
            row._layout.addStretch(1)  # type: ignore[attr-defined]
            if help_text:
                attach_tooltip(lbl, help_text)
                attach_tooltip(cb, help_text)
            return FormField(
                "enum", widget=row,
                getter=cb.currentText, setter=cb.setCurrentText,
            )
        if "\n" in value or len(value) > 40:
            row = _row_widget()
            lbl = _make_label(row, label, help_text)
            txt = QPlainTextEdit(row)
            txt.setPlainText(value)
            txt.setMaximumHeight(80)
            row._layout.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignTop)  # type: ignore[attr-defined]
            row._layout.addWidget(txt, 1)  # type: ignore[attr-defined]
            if help_text:
                attach_tooltip(lbl, help_text)
                attach_tooltip(txt, help_text)
            return FormField(
                "text", widget=row,
                getter=lambda: txt.toPlainText().rstrip("\n"),
                setter=lambda v: txt.setPlainText(str(v)),
            )
        row = _row_widget()
        lbl = _make_label(row, label, help_text)
        edit = QLineEdit(row)
        edit.setText(value)
        row._layout.addWidget(lbl)  # type: ignore[attr-defined]
        row._layout.addWidget(edit, 1)  # type: ignore[attr-defined]
        if help_text:
            attach_tooltip(edit, help_text)
        return FormField(
            "str", widget=row,
            getter=edit.text, setter=edit.setText,
        )

    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            item_factory = lambda: {k: v for k, v in value[0].items()}
            schema = "object"
        else:
            item_factory = lambda: ""
            schema = "scalar"
        le = ListEditor(parent, item_factory, schema)
        le.set(list(value))
        if help_text:
            attach_tooltip(le, help_text)
        return FormField("list", widget=le, getter=le.get, setter=le.set)

    # None / 其他 → 可选字符串
    row = _row_widget()
    lbl = _make_label(row, label, help_text)
    edit = QLineEdit(row)
    edit.setPlaceholderText("（空 = null）")
    row._layout.addWidget(lbl)  # type: ignore[attr-defined]
    row._layout.addWidget(edit, 1)  # type: ignore[attr-defined]
    if help_text:
        attach_tooltip(lbl, help_text)
        attach_tooltip(edit, help_text)
    return FormField(
        "none", widget=row,
        getter=lambda: edit.text().strip() or None,
        setter=lambda v: edit.setText("" if v is None else str(v)),
    )


def _enum_for(dotted: str, key: str) -> list[str] | None:
    if dotted in ENUM_FIELDS:
        return ENUM_FIELDS[dotted]
    if dotted.endswith(".mode") and ".topics." in dotted:
        return ENUM_FIELDS.get("r18_topic_control.topics.mode")
    return None


class ConfigFormBuilder:
    """递归构建整个配置表单（Qt 版）。"""

    def __init__(
        self,
        root: QWidget,
        help_map: dict[str, dict[str, str]],
        collapsed_paths: set[str] | None = None,
    ) -> None:
        self.root = root
        self.help_map = help_map
        self.collapsed_paths = collapsed_paths or set()
        self.fields: dict[str, FormField] = {}
        self.collapsibles: list[CollapsibleSection] = []

    def _help(self, dotted: str, value: Any = None) -> str:
        entry = self.help_map.get(dotted)
        if entry:
            return entry.get("help") or entry.get("inline") or ""
        return yaml_comments.semantic_help(dotted, value)

    def build_dict(self, data: dict[str, Any], prefix: str = "", parent: QWidget | None = None) -> None:
        target = parent or self.root
        for key, value in data.items():
            dotted = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and not value:
                self.fields[dotted] = FormField("empty_dict")
            elif isinstance(value, list) and not value:
                self.fields[dotted] = FormField("empty_list")
            self._build_value(target, key, value, dotted)

    def _build_value(self, parent: QWidget, key: str, value: Any, dotted: str) -> None:
        help_text = self._help(dotted, value)
        if isinstance(value, dict):
            default_open = dotted not in self.collapsed_paths
            if default_open:
                content = QWidget(parent)
                content_layout = QVBoxLayout(content)
                content_layout.setContentsMargins(16, 0, 0, 0)
                self.build_dict(value, dotted, content)
                section = CollapsibleSection(parent, key, default_open=True, help_text=help_text)
                section._content = content
                section._built = True
                section._layout.addWidget(content)
            else:
                def _lazy(container: QWidget, _d=dotted, _v=value) -> None:
                    inner = QVBoxLayout(container)
                    inner.setContentsMargins(16, 0, 0, 0)
                    self.build_dict(_v, _d, container)

                section = CollapsibleSection(parent, key, default_open=False, help_text=help_text, build_callback=_lazy)
            # 把 section 放进父布局
            if parent.layout() is not None:
                parent.layout().addWidget(section)
            self.collapsibles.append(section)
            return
        field = build_leaf_field(parent, key, value, help_text, dotted)
        if parent.layout() is not None:
            parent.layout().addWidget(field.widget)
        self.fields[dotted] = field

    def get_dict(self) -> dict[str, Any]:
        """从控件收集回 dict。"""
        result: dict[str, Any] = {}

        def _set_path(d: dict[str, Any], path: list[str], value: Any) -> None:
            node = d
            for part in path[:-1]:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            node[path[-1]] = value

        for dotted, field in self.fields.items():
            parts = dotted.split(".")
            value = field.get()
            if value == "" and field.kind in ("none", "str"):
                value = None
            _set_path(result, parts, value)
        return result
