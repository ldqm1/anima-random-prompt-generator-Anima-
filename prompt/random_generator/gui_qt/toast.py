"""轻量 Toast 提示（复制成功等操作反馈）。

在父窗口右下角显示一个小气泡，短暂停留后自动淡出消失。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QLabel, QWidget


class Toast:
    """右下角 Toast 提示。

    用法：
        Toast.show(parent, "已复制到剪贴板")
        Toast.show(parent, "保存成功 ✓", kind="success")
    """

    _instances: list["Toast"] = []

    def __init__(self, parent: QWidget, text: str, kind: str = "info", duration: int = 1600) -> None:
        super().__init__()
        self._label = QLabel(text, parent)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(self._style(kind))
        self._label.adjustSize()
        self._label.setMinimumWidth(140)
        self._label.setMaximumWidth(parent.width() - 40)

        # 定位：父窗口右下角
        pw, ph = parent.width(), parent.height()
        tw, th = self._label.width(), self._label.height()
        x = pw - tw - 24
        y = ph - th - 40
        self._label.move(max(x, 8), max(y, 8))
        self._label.raise_()
        self._label.show()

        # 透明度动画（淡入淡出）
        self._anim = QPropertyAnimation(self._label, b"windowOpacity", parent)
        self._anim.setDuration(250)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

        # 停留后淡出并销毁
        self._fade_out = QTimer(parent)
        self._fade_out.setSingleShot(True)
        self._fade_out.timeout.connect(self._fade)
        self._fade_out.start(duration)

    def _fade(self) -> None:
        self._anim.setDuration(300)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._label.deleteLater)
        self._anim.start()

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
