"""轻量 Toast 提示（复制成功等操作反馈）。

在父窗口右下角显示一个小气泡，短暂停留后自动消失。

注意：QWidget 的 ``windowOpacity`` 只对顶层窗口生效，对子控件无效，
因此这里用 QTimer 到时后直接隐藏 + 销毁（不做透明度动画，保证可靠消失）。
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget


class Toast:
    """右下角 Toast 提示。

    用法：
        Toast.show(parent, "已复制到剪贴板")
        Toast.show(parent, "保存成功 ✓", kind="success")
    """

    _current: "Toast | None" = None

    def __init__(self, parent: QWidget, text: str, kind: str = "info", duration: int = 1600) -> None:
        # 新气泡替换旧气泡（避免右下角堆叠）
        if Toast._current is not None:
            try:
                Toast._current._dismiss()
            except Exception:  # noqa: BLE001
                pass
        Toast._current = self

        self._parent = parent
        self._label = QLabel(text, parent)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(self._style(kind))
        self._label.adjustSize()
        self._label.setMinimumWidth(140)
        self._label.setMaximumWidth(max(parent.width() - 40, 140))

        # 定位：父窗口右下角
        pw, ph = parent.width(), parent.height()
        tw, th = self._label.width(), self._label.height()
        x = pw - tw - 24
        y = ph - th - 40
        self._label.move(max(x, 8), max(y, 8))
        self._label.raise_()
        self._label.show()

        # 到时后隐藏并销毁（可靠消失）
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(duration)

    def _dismiss(self) -> None:
        if Toast._current is self:
            Toast._current = None
        try:
            self._label.hide()
            self._label.deleteLater()
        except RuntimeError:  # 控件已销毁
            pass

    @staticmethod
    def _style(kind: str) -> str:
        if kind == "success":
            bg, border = "#2e7d32", "#43a047"
        elif kind == "error":
            bg, border = "#c62828", "#e53935"
        else:
            bg, border = "#2c3e50", "#34495e"
        return (
            f"background-color: {bg}; color: #ffffff; border: 1px solid {border};"
            "border-radius: 8px; padding: 9px 16px; font-size: 13px; font-weight: bold;"
        )

    @staticmethod
    def show(parent: QWidget, text: str, kind: str = "info", duration: int = 1600) -> None:
        """在父窗口右下角显示 Toast。"""
        if parent is None or not parent.isVisible():
            return
        Toast(parent, text, kind=kind, duration=duration)
