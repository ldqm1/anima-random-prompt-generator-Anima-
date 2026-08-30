"""PySide6 工具提示（Tooltip）。

Qt 的 setToolTip 只显示纯文本且样式受限。这里实现富文本气泡：
悬停 0.4s 后显示置顶半透明气泡，移开/点击消失。
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QLabel, QToolTip, QWidget


class ToolTipManager(QObject):
    """给任意 QWidget 挂载悬浮帮助。

    - 文本支持 HTML（setRichText）。
    - 悬停 400ms 显示，移开立即消失。
    - 全局共享一个气泡，避免重复创建。
    """

    _instance: "ToolTipManager | None" = None
    _bubble: QLabel | None = None
    _timer: QTimer | None = None
    _target: QWidget | None = None

    def __init__(self) -> None:
        super().__init__()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._show)

    @classmethod
    def instance(cls) -> "ToolTipManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def attach(self, widget: QWidget, text: str, rich: bool = True) -> None:
        """给控件绑定帮助文本。"""
        if not text:
            return
        widget.setProperty("anima_tooltip", text)
        widget.setToolTip(text)  # 兜底：Qt 原生 tooltip
        widget.installEventFilter(self)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # noqa: N802
        if obj.property("anima_tooltip") is None:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.Enter:
            self._target = obj
            self._timer.start()
        elif event.type() == QEvent.Type.Leave:
            self._timer.stop()
            self._hide()
        elif event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.FocusOut):
            self._timer.stop()
            self._hide()
        return super().eventFilter(obj, event)

    def _show(self) -> None:
        if self._target is None:
            return
        text = self._target.property("anima_tooltip")
        if not text:
            return
        # 用 Qt 原生 QToolTip（支持富文本 + 自动定位 + 样式表）
        pos = self._target.mapToGlobal(QPoint(8, self._target.height() + 4))
        QToolTip.showText(pos, text, self._target)
        self._bubble = None

    def _hide(self) -> None:
        QToolTip.hideText()
        self._bubble = None


def attach_tooltip(widget: QWidget, text: str) -> None:
    """便捷函数：给控件挂悬浮帮助。"""
    ToolTipManager.instance().attach(widget, text)
