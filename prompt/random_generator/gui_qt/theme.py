"""PySide6 主题（QSS）：深色 / 浅色。

用 Qt 样式表实现全局配色，切换主题 = 换 QSS。
"""
from __future__ import annotations

# 通用片段：圆角卡片 / 按钮 / 输入框 / Tab 等
_CARD = """
QFrame#card {
    background: %(card_bg)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
QFrame#cardTitle {
    background: transparent;
    border: none;
    font-size: 15px;
    font-weight: bold;
    color: %(accent)s;
    padding: 2px 0;
}
"""

DARK_QSS = """
/* ---- 深色主题 ---- */
QWidget {
    background-color: #23252a;
    color: #e8e8e8;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #23252a;
}
/* ---- Tab 栏 ---- */
QTabWidget::pane {
    border: none;
    background: #2b2e34;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #9aa0a6;
    padding: 9px 20px;
    border: none;
    margin: 2px 1px;
    border-radius: 6px;
    min-width: 70px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #2c7da0;
    color: #ffffff;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #3a3f47;
    color: #e8e8e8;
}
/* ---- 按钮 ---- */
QPushButton {
    background: #3a3f47;
    border: 1px solid #4a505a;
    border-radius: 7px;
    padding: 7px 16px;
    color: #e8e8e8;
    font-size: 13px;
}
QPushButton:hover {
    background: #454b55;
    border-color: #2c7da0;
}
QPushButton:pressed {
    background: #2c7da0;
    color: #fff;
}
QPushButton:disabled {
    background: #2e3136;
    color: #6a6f76;
    border-color: #3a3f45;
}
QPushButton#primary {
    background: #2c7da0;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#primary:hover { background: #3589ad; }
QPushButton#success {
    background: #2e7d32;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#success:hover { background: #388e3c; }
QPushButton#danger {
    background: #c62828;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#danger:hover { background: #d32f2f; }
/* ---- 输入控件 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget {
    background: #2e3137;
    border: 1px solid #454b55;
    border-radius: 6px;
    padding: 5px 9px;
    color: #e8e8e8;
    selection-background-color: #2c7da0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus {
    border-color: #2c7da0;
    background: #31353c;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {
    border-color: #5a6270;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 6px;
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #9aa0a6;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #2e3137;
    color: #e8e8e8;
    border: 1px solid #454b55;
    border-radius: 6px;
    selection-background-color: #2c7da0;
    selection-color: #fff;
    padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #3a3f47;
    border: none;
    width: 18px;
    border-radius: 3px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #2c7da0;
}
/* ---- 单选/复选 ---- */
QCheckBox, QRadioButton {
    color: #e8e8e8;
    spacing: 7px;
    background: transparent;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #8a919c;
    border-radius: 4px;
    background: #2e3137;
}
QCheckBox::indicator:checked {
    background: #2c7da0;
    border-color: #2c7da0;
}
QCheckBox::indicator:hover {
    border-color: #2c7da0;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #8a919c;
    border-radius: 9px;
    background: #2e3137;
}
QRadioButton::indicator:checked {
    border: 5px solid #2c7da0;
    background: #2c7da0;
}
QRadioButton::indicator:hover {
    border-color: #2c7da0;
}
/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #4a505a;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: #2c7da0; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #4a505a;
    border-radius: 5px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: #2c7da0; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
/* ---- 列表 ---- */
QListWidget::item {
    padding: 7px 10px;
    border-radius: 5px;
    margin: 1px 2px;
}
QListWidget::item:hover {
    background: #3a3f47;
}
QListWidget::item:selected {
    background: #2c7da0;
    color: #fff;
    border-radius: 5px;
}
/* ---- 分组框/标签 ---- */
QGroupBox {
    border: 1px solid #454b55;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #2c7da0;
}
QLabel#sectionTitle {
    font-size: 15px;
    font-weight: bold;
    color: #2c7da0;
    padding: 4px 0;
}
QLabel#groupTitle {
    font-size: 13px;
    font-weight: bold;
    color: #8a919c;
    padding: 3px 0;
    margin-top: 6px;
    border-bottom: 1px solid #3a3f47;
}
QLabel#hint {
    color: #8a919c;
    font-size: 12px;
}
/* ---- 进度条 ---- */
QProgressBar {
    background: #2e3137;
    border: 1px solid #454b55;
    border-radius: 6px;
    text-align: center;
    color: #e8e8e8;
    height: 20px;
    font-size: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2c7da0, stop:1 #52b7e0);
    border-radius: 5px;
}
/* ---- 代码框 ---- */
QPlainTextEdit#codeBox {
    background: #1c1e22;
    color: #d8dee9;
    border: 1px solid #3a3f47;
    border-radius: 8px;
    padding: 10px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}
/* ---- Tooltip ---- */
QToolTip {
    background-color: #3a3f47;
    color: #e8e8e8;
    border: 1px solid #2c7da0;
    border-radius: 5px;
    padding: 6px 9px;
    font-size: 12px;
}
/* ---- 分割条 ---- */
QSplitter::handle { background: #3a3f47; }
QSplitter::handle:hover { background: #2c7da0; }
"""

LIGHT_QSS = """
/* ---- 浅色主题 ---- */
QWidget {
    background-color: #f4f6f9;
    color: #2c3238;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #f4f6f9;
}
/* ---- Tab 栏 ---- */
QTabWidget::pane {
    border: none;
    background: #ffffff;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #7a828a;
    padding: 9px 20px;
    border: none;
    margin: 2px 1px;
    border-radius: 6px;
    min-width: 70px;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #007bff;
    color: #ffffff;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #e6ebf1;
    color: #2c3238;
}
/* ---- 按钮 ---- */
QPushButton {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 7px;
    padding: 7px 16px;
    color: #2c3238;
    font-size: 13px;
}
QPushButton:hover {
    background: #f0f4f8;
    border-color: #007bff;
}
QPushButton:pressed {
    background: #007bff;
    color: #fff;
}
QPushButton:disabled {
    background: #f1f3f5;
    color: #adb5bd;
    border-color: #e0e4e8;
}
QPushButton#primary {
    background: #007bff;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#primary:hover { background: #3587d6; }
QPushButton#success {
    background: #28a745;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#success:hover { background: #34ce57; }
QPushButton#danger {
    background: #dc3545;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#danger:hover { background: #e05260; }
/* ---- 输入控件 ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget {
    background: #ffffff;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    padding: 5px 9px;
    color: #2c3238;
    selection-background-color: #007bff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus {
    border-color: #007bff;
    background: #ffffff;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {
    border-color: #a8b3bf;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 6px;
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #7a828a;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #2c3238;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    selection-background-color: #007bff;
    selection-color: #fff;
    padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: #f0f4f8;
    border: none;
    width: 18px;
    border-radius: 3px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background: #007bff;
}
/* ---- 单选/复选 ---- */
QCheckBox, QRadioButton {
    color: #2c3238;
    spacing: 7px;
    background: transparent;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
    border: 1px solid #a8b3bf;
    border-radius: 4px;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #007bff;
    border-color: #007bff;
}
QCheckBox::indicator:hover {
    border-color: #007bff;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid #a8b3bf;
    border-radius: 9px;
    background: #ffffff;
}
QRadioButton::indicator:checked {
    border: 5px solid #007bff;
    background: #007bff;
}
QRadioButton::indicator:hover {
    border-color: #007bff;
}
/* ---- 滚动条 ---- */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c4ccd4;
    border-radius: 5px;
    min-height: 32px;
}
QScrollBar::handle:vertical:hover { background: #007bff; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c4ccd4;
    border-radius: 5px;
    min-width: 32px;
}
QScrollBar::handle:horizontal:hover { background: #007bff; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
/* ---- 列表 ---- */
QListWidget::item {
    padding: 7px 10px;
    border-radius: 5px;
    margin: 1px 2px;
}
QListWidget::item:hover {
    background: #f0f4f8;
}
QListWidget::item:selected {
    background: #007bff;
    color: #fff;
    border-radius: 5px;
}
/* ---- 分组框/标签 ---- */
QGroupBox {
    border: 1px solid #d0d7de;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #007bff;
}
QLabel#sectionTitle {
    font-size: 15px;
    font-weight: bold;
    color: #007bff;
    padding: 4px 0;
}
QLabel#groupTitle {
    font-size: 13px;
    font-weight: bold;
    color: #7a828a;
    padding: 3px 0;
    margin-top: 6px;
    border-bottom: 1px solid #e0e4e8;
}
QLabel#hint {
    color: #7a828a;
    font-size: 12px;
}
/* ---- 进度条 ---- */
QProgressBar {
    background: #e6ebf1;
    border: 1px solid #d0d7de;
    border-radius: 6px;
    text-align: center;
    color: #2c3238;
    height: 20px;
    font-size: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #007bff, stop:1 #52b7e0);
    border-radius: 5px;
}
/* ---- 代码框 ---- */
QPlainTextEdit#codeBox {
    background: #f8fafc;
    color: #24292e;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    padding: 10px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}
/* ---- Tooltip ---- */
QToolTip {
    background-color: #ffffff;
    color: #2c3238;
    border: 1px solid #007bff;
    border-radius: 5px;
    padding: 6px 9px;
    font-size: 12px;
}
/* ---- 分割条 ---- */
QSplitter::handle { background: #d0d7de; }
QSplitter::handle:hover { background: #007bff; }
"""

THEME_QSS = {
    "light": LIGHT_QSS,
    "dark": DARK_QSS,
}
