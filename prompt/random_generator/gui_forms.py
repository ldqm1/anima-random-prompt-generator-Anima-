"""通用 YAML 配置表单生成器（可视化编辑 generation_config.yaml / creative_anchors.yaml）。

设计目标：所有配置项按数据类型生成对应控件，逐层展开：
- ``int`` → Spinbox
- ``float`` → Spinbox（步长 0.1）
- ``bool`` → Checkbutton
- ``str``（短）→ Entry；多行（含 \\n 或文本块）→ Text
- ``list[标量]`` → 可增删的字符串列表编辑器
- ``list[dict]`` → 可增删的对象列表（每个对象展开为子表单）
- ``dict`` → 递归子表单
- ``None`` → 视为可选字符串（Entry，空=null）

每行带：
- 键名 + 类型徽标；
- tooltip（悬停显示 yaml 注释中的帮助文本，经 ttkbootstrap ToolTip）；
- 折叠（dict 分类默认折叠/展开由调用方指定）。

保存时从控件收集回 dict，与默认配置 diff 后只写用户覆盖部分。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

import ttkbootstrap as tb
from tkinter.constants import X, Y, BOTH, LEFT, RIGHT, TOP, BOTTOM, W, E, N, S  # noqa: F401

# tkinter 无 FILL 常量；pack(fill=...) 用字符串，这里统一定义
FILL = "fill"  # noqa: F401

try:
    from ttkbootstrap.tooltip import ToolTip  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    ToolTip = None  # type: ignore[assignment]


class SimpleToolTip:
    """自实现的悬浮提示（ttkbootstrap 2.2.2 无 tooltip 模块时的替代）。

    鼠标悬停 400ms 后显示一个置顶 Toplevel 气泡，移开或点击后消失。
    """

    def __init__(self, widget: tk.Widget, text: str, wraplength: int = 400) -> None:
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event: Any = None) -> None:
        if self.tip is not None:
            return
        self._schedule()

    def _schedule(self) -> None:
        if self._after_id is not None:
            return
        try:
            self._after_id = self.widget.after(400, self._show)
        except (tk.TclError, RuntimeError):
            self._after_id = None

    def _on_leave(self, _event: Any = None) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except (tk.TclError, RuntimeError):
                pass
            self._after_id = None
        self._hide()

    def _show(self) -> None:
        self._after_id = None
        if self.tip is not None:
            return
        try:
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_attributes("-topmost", True)
            label = tk.Label(
                self.tip,
                text=self.text,
                justify="left",
                background="#ffffe0",
                foreground="#000000",
                relief="solid",
                borderwidth=1,
                font=("Microsoft YaHei UI", 9),
                wraplength=self.wraplength,
                padx=8,
                pady=6,
            )
            label.pack()
            x, y = self._tip_position()
            self.tip.wm_geometry(f"+{x}+{y}")
        except (tk.TclError, RuntimeError):
            self.tip = None

    def _tip_position(self) -> tuple[int, int]:
        try:
            wx = self.widget.winfo_rootx()
            wy = self.widget.winfo_rooty()
            wh = self.widget.winfo_height()
            tw = self.tip.winfo_reqwidth() if self.tip else 200
            th = self.tip.winfo_reqheight() if self.tip else 80
            sw = self.widget.winfo_screenwidth()
            x = wx + 12
            if x + tw > sw:
                x = max(0, wx - tw - 12)
            y = wy + wh + 6
            return x, y
        except (tk.TclError, RuntimeError):
            return 0, 0

    def _hide(self) -> None:
        if self.tip is not None:
            try:
                self.tip.destroy()
            except (tk.TclError, RuntimeError):
                pass
            self.tip = None

from . import yaml_comments

# 布尔值显示
_TRUE = "是"
_FALSE = "否"


def _tooltip(widget: tk.Widget, text: str) -> None:
    """给控件绑定悬浮帮助。优先用 ttkbootstrap 自带，缺失时用自实现气泡。"""
    if not text:
        return
    if ToolTip is not None:
        try:
            ToolTip(widget, text=text, wraplength=380)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        SimpleToolTip(widget, text)
    except Exception:  # noqa: BLE001
        pass


class FormRow:
    """一行控件：标签 + 输入控件。"""

    def __init__(self, parent: tk.Widget, label: str, control: tk.Widget, help_text: str = "") -> None:
        self.label = label
        self.control = control
        self.frame = tb.Frame(parent)
        lbl = tb.Label(self.frame, text=label, width=22, anchor="w", bootstyle="secondary")
        lbl.pack(side=LEFT, padx=(0, 6))
        control.pack(side=LEFT, fill=X, expand=True)
        if help_text:
            _tooltip(lbl, help_text)
            _tooltip(control, help_text)

    def pack(self, **kwargs: Any) -> None:
        self.frame.pack(fill=X, pady=2, **kwargs)


class CollapsibleSection:
    """可折叠的分类区块（默认折叠状态由 collapsible=True + default_open 决定）。

    支持**懒加载**：default_open=False 时内容不立即构建（build_callback 延迟到
    首次展开才执行），显著减少初始控件数量与布局/滚动开销。
    """

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        content: tk.Widget | None = None,
        default_open: bool = True,
        help_text: str = "",
        build_callback: Callable[[tk.Widget], None] | None = None,
    ) -> None:
        self.content = content
        self.default_open = default_open
        self.open = default_open
        self.build_callback = build_callback
        self.built = content is not None or build_callback is None
        self.header = tb.Frame(parent)
        self.header.pack(fill=X, pady=(4, 0))
        self.btn = tb.Button(
            self.header,
            text="▾ " + title if default_open else "▸ " + title,
            bootstyle="secondary-link",
            command=self._toggle,
        )
        self.btn.pack(side=LEFT)
        if help_text:
            _tooltip(self.btn, help_text)
        if default_open and content is not None:
            self._ensure_content()
        elif content is not None:
            content.pack_forget()

    def _ensure_content(self) -> None:
        """确保内容已构建并显示。"""
        if not self.built and self.build_callback is not None:
            # 懒加载：构建内容 frame
            self.content = tb.Frame(self.header.master)
            try:
                self.build_callback(self.content)
                self.content.pack(fill=X, padx=(12, 0), pady=(2, 2))
                self.built = True
            except Exception:  # noqa: BLE001
                self.content = None
                self.built = False
        elif self.content is not None:
            self.content.pack(fill=X, padx=(12, 0), pady=(2, 2))

    def _toggle(self) -> None:
        self.open = not self.open
        self.btn.configure(text=("▾ " if self.open else "▸ ") + self.btn.cget("text")[2:])
        if self.open:
            self._ensure_content()
        elif self.content is not None:
            self.content.pack_forget()


class FormField:
    """单个字段的控件状态，用于保存时取值。"""

    def __init__(self, kind: str, var: Any = None, widget: tk.Widget | None = None, getter: Callable[[], Any] | None = None, setter: Callable[[Any], None] | None = None) -> None:
        self.kind = kind
        self.var = var
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
        if self.var is not None:
            return self.var.get()
        return None

    def set(self, value: Any) -> None:
        if self.setter is not None:
            self.setter(value)
        elif self.var is not None:
            try:
                self.var.set(value)
            except (tk.TclError, ValueError):
                pass


class ListEditor:
    """可增删的标量/对象列表编辑器。

    - 标量列表：每行一个 Entry；
    - 对象列表：每行一个"对象子表单"（含删除按钮），可"添加新项"。
    """

    def __init__(self, parent: tk.Widget, item_schema: str, item_factory: Callable[[], Any], field_cfg: dict[str, Any] | None = None) -> None:
        self.parent = parent
        self.item_schema = item_schema
        self.item_factory = item_factory
        self.field_cfg = field_cfg or {}
        self.rows: list[Any] = []
        self.frame = tb.Frame(parent)
        self.list_box = tb.Frame(self.frame)
        self.list_box.pack(fill=X)
        self.add_btn = tb.Button(self.frame, text="+ 添加", bootstyle="success-outline", command=self._add_row)
        self.add_btn.pack(anchor="w", pady=(2, 0))

    def _add_row(self) -> None:
        row = self._make_row(None)
        self.rows.append(row)
        self._reflow()

    def _make_row(self, value: Any) -> Any:
        if self.item_schema == "scalar":
            return self._make_scalar_row(value)
        return self._make_object_row(value)

    def _make_scalar_row(self, value: Any) -> Any:
        fr = tb.Frame(self.list_box)
        var = tk.StringVar(value="" if value is None else str(value))
        ent = ttk.Entry(fr, textvariable=var)
        ent.pack(side=LEFT, fill=X, expand=True)
        del_btn = tb.Button(fr, text="✕", bootstyle="danger-outline", width=3,
                            command=lambda: self._remove_row(fr))
        del_btn.pack(side=LEFT, padx=(4, 0))
        fr.pack(fill=X, pady=1)
        return {"frame": fr, "var": var, "widget": ent}

    def _make_object_row(self, value: Any) -> Any:
        fr = tb.Frame(self.list_box)
        fr.pack(fill=X, pady=2, padx=(0, 0))
        # 头部：序号 + 删除
        head = tb.Frame(fr)
        head.pack(fill=X)
        idx = len(self.rows) + 1
        tb.Label(head, text=f"条目 {idx}", bootstyle="info").pack(side=LEFT)
        tb.Button(head, text="✕ 删除", bootstyle="danger-outline", width=8,
                  command=lambda: self._remove_row(fr)).pack(side=RIGHT)
        # 子表单
        sub = tb.Frame(fr)
        sub.pack(fill=X, padx=(8, 0))
        fields: dict[str, FormField] = {}
        default = self.item_factory() if value is None else value
        if isinstance(default, dict):
            for k, v in default.items():
                help_text = self.field_cfg.get(k) or yaml_comments.semantic_help(k, v)
                field = self._build_field(sub, k, v, f"{k}", help_text)
                fields[k] = field
        fr.sub = sub  # type: ignore[attr-defined]
        return {"frame": fr, "fields": fields, "obj": dict(default) if isinstance(default, dict) else default}

    def _remove_row(self, frame: tk.Widget) -> None:
        frame.destroy()
        self.rows = [r for r in self.rows if r.get("frame") is not frame]
        self._reflow()

    def _reflow(self) -> None:
        for i, row in enumerate(self.rows):
            if "fields" in row:
                # 更新头部序号
                pass

    def get(self) -> list[Any]:
        out: list[Any] = []
        for row in self.rows:
            if "fields" in row:
                obj = {}
                for k, field in row["fields"].items():
                    obj[k] = field.get()
                out.append(obj)
            else:
                val = row["var"].get().strip()
                if val:
                    out.append(self._parse_scalar(val))
        return out

    def _parse_scalar(self, s: str) -> Any:
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                if s in ("true", "True", "yes"):
                    return True
                if s in ("false", "False", "no"):
                    return False
                return s

    def set(self, values: list[Any]) -> None:
        for r in self.rows:
            r["frame"].destroy()
        self.rows = []
        for v in values:
            row = self._make_row(v)
            self.rows.append(row)
        self._reflow()

    def _build_field(self, parent: tk.Widget, key: str, value: Any, label: str, help_text: str) -> FormField:
        """在 parent 上构建单字段控件，返回 FormField。"""
        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            cb = tb.Checkbutton(parent, text=label, variable=var, bootstyle="round-toggle")
            cb.pack(anchor="w", pady=1)
            if help_text:
                _tooltip(cb, help_text)
            return FormField("bool", var=var)
        if isinstance(value, int) and not isinstance(value, bool):
            var = tk.IntVar(value=value)
            fr = tb.Frame(parent)
            tb.Label(fr, text=label, width=20, anchor="w", bootstyle="secondary").pack(side=LEFT)
            sp = ttk.Spinbox(fr, from_=-1000000, to=1000000, textvariable=var, width=10)
            sp.pack(side=LEFT)
            fr.pack(fill=X, pady=1)
            if help_text:
                _tooltip(sp, help_text)
            return FormField("int", var=var)
        if isinstance(value, float):
            var = tk.DoubleVar(value=value)
            fr = tb.Frame(parent)
            tb.Label(fr, text=label, width=20, anchor="w", bootstyle="secondary").pack(side=LEFT)
            sp = ttk.Spinbox(fr, from_=-1000000.0, to=1000000.0, increment=0.1, textvariable=var, width=10)
            sp.pack(side=LEFT)
            fr.pack(fill=X, pady=1)
            if help_text:
                _tooltip(sp, help_text)
            return FormField("float", var=var)
        if isinstance(value, str):
            if "\n" in value or len(value) > 40:
                fr = tb.Frame(parent)
                tb.Label(fr, text=label, width=20, anchor="nw", bootstyle="secondary").pack(side=LEFT, anchor="n")
                txt = tk.Text(fr, width=40, height=3)
                txt.insert("1.0", value)
                txt.pack(side=LEFT, fill=X, expand=True)
                fr.pack(fill=X, pady=1)
                if help_text:
                    _tooltip(txt, help_text)
                return FormField("text", widget=txt,
                                 getter=lambda: txt.get("1.0", "end").strip("\n"),
                                 setter=lambda v: (txt.delete("1.0", "end"), txt.insert("1.0", v)))
            var = tk.StringVar(value=value)
            fr = tb.Frame(parent)
            tb.Label(fr, text=label, width=20, anchor="w", bootstyle="secondary").pack(side=LEFT)
            ent = ttk.Entry(fr, textvariable=var)
            ent.pack(side=LEFT, fill=X, expand=True)
            fr.pack(fill=X, pady=1)
            if help_text:
                _tooltip(ent, help_text)
            return FormField("str", var=var)
        if isinstance(value, list):
            item_factory: Callable[[], Any]
            if value and isinstance(value[0], dict):
                item_factory = lambda: dict(value[0])
                schema = "object"
            else:
                item_factory = lambda: ""
                schema = "scalar"
            le = ListEditor(parent, schema, item_factory)
            le.frame.pack(fill=X, pady=1)
            le.set(list(value))
            return FormField("list", getter=le.get, setter=le.set)
        # None / 其他
        var = tk.StringVar(value="" if value is None else str(value))
        fr = tb.Frame(parent)
        tb.Label(fr, text=label, width=20, anchor="w", bootstyle="secondary").pack(side=LEFT)
        ent = ttk.Entry(fr, textvariable=var)
        ent.pack(side=LEFT, fill=X, expand=True)
        fr.pack(fill=X, pady=1)
        if help_text:
            _tooltip(ent, help_text)
        return FormField("none", var=var)


# 已知枚举字段：路径（点分）→ 可选值列表
ENUM_FIELDS: dict[str, list[str]] = {
    "deepseek.reasoning_effort": ["none", "low", "medium", "high"],
    "r18_topic_control.topics.mode": ["fixed", "probabilistic", "weighted"],
}


class ConfigFormBuilder:
    """递归构建整个配置表单。"""

    def __init__(self, root: tk.Widget, help_map: dict[str, dict[str, str]], collapsed_paths: set[str] | None = None) -> None:
        self.root = root
        self.help_map = help_map
        # 默认折叠的路径（点分），如 r18_topic_control / extra_requirements_pool
        self.collapsed_paths = collapsed_paths or set()
        self.fields: dict[str, FormField] = {}
        # 本 builder 创建的所有折叠区块（供上层"全部展开/折叠"）
        self.collapsibles: list["CollapsibleSection"] = []

    def _help(self, dotted: str, value: Any = None) -> str:
        """返回帮助文本：优先 yaml 注释，其次语义化兜底，最后空串。"""
        entry = self.help_map.get(dotted)
        if entry:
            return entry.get("help") or entry.get("inline") or ""
        return yaml_comments.semantic_help(dotted, value)

    def _enum_for(self, dotted: str, key: str) -> list[str] | None:
        """按点分路径匹配枚举字段；支持 topics 下动态主题键的前缀匹配。"""
        if dotted in ENUM_FIELDS:
            return ENUM_FIELDS[dotted]
        # r18_topic_control.topics.<任意主题>.mode
        if dotted.endswith(".mode") and ".topics." in dotted:
            return ENUM_FIELDS.get("r18_topic_control.topics.mode")
        return None

    def build_dict(self, data: dict[str, Any], prefix: str = "", parent: tk.Widget | None = None) -> None:
        """递归展开 dict，并把所有叶子字段登记到 self.fields（点分路径）。"""
        target = parent or self.root
        for key, value in data.items():
            dotted = f"{prefix}.{key}" if prefix else key
            # 空 dict / 空 list 也登记（否则保存时该键丢失）
            if isinstance(value, dict) and not value:
                self.fields[dotted] = FormField("empty_dict")
            elif isinstance(value, list) and not value:
                self.fields[dotted] = FormField("empty_list")
            self._build_value(target, key, value, dotted)

    def _build_value(self, parent: tk.Widget, key: str, value: Any, dotted: str) -> None:
        help_text = self._help(dotted, value)
        if isinstance(value, dict):
            default_open = dotted not in self.collapsed_paths
            if default_open:
                # 默认展开：立即构建
                section_frame = tb.Frame(parent)
                inner = tb.Frame(section_frame)
                self.build_dict(value, dotted, inner)
                section = CollapsibleSection(
                    parent, self._display_key(key), inner,
                    default_open=True, help_text=help_text,
                )
            else:
                # 默认折叠：懒加载（展开时才构建子控件）
                def _lazy_build(container: tk.Widget, _d=dotted, _v=value) -> None:
                    self.build_dict(_v, _d, container)

                section = CollapsibleSection(
                    parent, self._display_key(key), None,
                    default_open=False, help_text=help_text,
                    build_callback=_lazy_build,
                )
            self.collapsibles.append(section)
            return
        fr = tb.Frame(parent)
        fr.pack(fill=X, pady=1)
        field = self._leaf_field(fr, key, value, dotted, help_text)
        self.fields[dotted] = field

    def _leaf_field(self, parent: tk.Widget, key: str, value: Any, dotted: str, help_text: str) -> FormField:
        """构建叶子字段（int/float/bool/str/list/None）。"""
        label = self._display_key(key)
        enum_values = self._enum_for(dotted, key)
        if isinstance(value, bool):
            var = tk.BooleanVar(value=value)
            cb = tb.Checkbutton(parent, text=label, variable=var, bootstyle="round-toggle")
            cb.pack(anchor="w")
            if help_text:
                _tooltip(cb, help_text)
            return FormField("bool", var=var)
        if isinstance(value, int) and not isinstance(value, bool):
            var = tk.IntVar(value=value)
            tb.Label(parent, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
            sp = ttk.Spinbox(parent, from_=-1000000, to=1000000, textvariable=var, width=12)
            sp.pack(side=LEFT, padx=(4, 0))
            if help_text:
                _tooltip(sp, help_text)
            return FormField("int", var=var)
        if isinstance(value, float):
            var = tk.DoubleVar(value=value)
            tb.Label(parent, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
            sp = ttk.Spinbox(parent, from_=-1000000.0, to=1000000.0, increment=0.1, textvariable=var, width=12)
            sp.pack(side=LEFT, padx=(4, 0))
            if help_text:
                _tooltip(sp, help_text)
            return FormField("float", var=var)
        if isinstance(value, str):
            if enum_values:
                var = tk.StringVar(value=value)
                tb.Label(parent, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
                cb = tb.Combobox(parent, textvariable=var, values=enum_values, state="readonly", width=12)
                cb.pack(side=LEFT, padx=(4, 0))
                if help_text:
                    _tooltip(cb, help_text)
                return FormField("enum", var=var)
            if "\n" in value or len(value) > 40:
                tb.Label(parent, text=label, width=24, anchor="nw", bootstyle="secondary").pack(side=LEFT, anchor="n")
                txt = tk.Text(parent, width=46, height=3)
                txt.insert("1.0", value)
                txt.pack(side=LEFT, fill=X, expand=True)
                if help_text:
                    _tooltip(txt, help_text)
                return FormField("text", widget=txt,
                                 getter=lambda: txt.get("1.0", "end").strip("\n"),
                                 setter=lambda v: (txt.delete("1.0", "end"), txt.insert("1.0", v)))
            var = tk.StringVar(value=value)
            tb.Label(parent, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
            ent = ttk.Entry(parent, textvariable=var)
            ent.pack(side=LEFT, fill=X, expand=True, padx=(4, 0))
            if help_text:
                _tooltip(ent, help_text)
            return FormField("str", var=var)
        if isinstance(value, list):
            label_fr = tb.Frame(parent)
            label_fr.pack(fill=X)
            tb.Label(label_fr, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
            if help_text:
                _tooltip(label_fr, help_text)
            if value and isinstance(value[0], dict):
                le = ListEditor(parent, "object", lambda: {k: v for k, v in value[0].items()})
            else:
                le = ListEditor(parent, "scalar", lambda: "")
            le.frame.pack(fill=X, padx=(24, 0))
            le.set(list(value))
            return FormField("list", getter=le.get, setter=le.set)
        # None
        var = tk.StringVar(value="")
        tb.Label(parent, text=label, width=24, anchor="w", bootstyle="secondary").pack(side=LEFT)
        ent = ttk.Entry(parent, textvariable=var)
        ent.pack(side=LEFT, fill=X, expand=True, padx=(4, 0))
        if help_text:
            _tooltip(ent, help_text)
        return FormField("none", var=var)

    def get_dict(self) -> dict[str, Any]:
        """从控件收集回 dict（结构按默认展开路径 + 空 dict/list 保留）。"""
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
            # 空字符串按 None 处理（yaml null 字段渲染成空输入）
            if value == "" and field.kind in ("none", "str"):
                value = None
            _set_path(result, parts, value)
        return result

    @staticmethod
    def _display_key(key: str) -> str:
        # 保留英文键（yaml 键就是英文）；中文类别名原样
        return key
