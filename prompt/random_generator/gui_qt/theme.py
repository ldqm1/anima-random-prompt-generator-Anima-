"""PySide6 主题（QSS）：深色 / 浅色。

用 Qt 样式表实现全局配色，切换主题 = 换 QSS。
"""
from __future__ import annotations

DARK_QSS = """
/* ---- 深色主题 ---- */
QWidget {
    background-color: #2b2b2b;
    color: #e8e8e8;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #2b2b2b;
}
QTabWidget::pane {
    border: 1px solid #3c3c3c;
    background: #2b2b2b;
}
QTabBar::tab {
    background: #3c3c3c;
    color: #c8c8c8;
    padding: 8px 18px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
    min-width: 60px;
}
QTabBar::tab:selected {
    background: #2c7da0;
    color: #ffffff;
}
QTabBar::tab:hover:!selected {
    background: #4a4a4a;
}
QPushButton {
    background: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 6px 14px;
    color: #e8e8e8;
}
QPushButton:hover {
    background: #4a4a4a;
    border-color: #2c7da0;
}
QPushButton:pressed {
    background: #2c7da0;
}
QPushButton:disabled {
    background: #333;
    color: #777;
}
QPushButton#primary {
    background: #2c7da0;
    border: none;
    color: #fff;
    font-weight: bold;
}
QPushButton#primary:hover { background: #3587ad; }
QPushButton#success {
    background: #2e7d32;
    border: none;
    color: #fff;
}
QPushButton#success:hover { background: #388e3c; }
QPushButton#danger {
    background: #c62828;
    border: none;
    color: #fff;
}
QPushButton#danger:hover { background: #d32f2f; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: #3c3f41;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e8e8e8;
    selection-background-color: #2c7da0;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {
    border-color: #2c7da0;
}
QComboBox QAbstractItemView {
    background: #3c3c3c;
    color: #e8e8e8;
    selection-background-color: #2c7da0;
}
QCheckBox, QRadioButton {
    color: #e8e8e8;
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #888;
    border-radius: 3px;
    background: #3c3f41;
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
    border: 2px solid #888;
    border-radius: 9px;
    background: #3c3f41;
}
QRadioButton::indicator:checked {
    border: 5px solid #2c7da0;
    background: #2c7da0;
}
QRadioButton::indicator:hover {
    border-color: #2c7da0;
}
QScrollBar:vertical {
    background: #2b2b2b;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #555;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #2c7da0; }
QScrollBar:horizontal {
    background: #2b2b2b;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #555;
    border-radius: 6px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QListWidget, QTreeWidget, QTableView {
    background: #3c3f41;
    border: 1px solid #555;
    border-radius: 4px;
    color: #e8e8e8;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #2c7da0;
    color: #fff;
}
QToolTip {
    background-color: #ffffe0;
    color: #000000;
    border: 1px solid #aaa;
    padding: 6px;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #555;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #2c7da0;
}
QProgressBar {
    background: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    text-align: center;
    color: #e8e8e8;
    height: 18px;
}
QProgressBar::chunk {
    background: #2c7da0;
    border-radius: 3px;
}
QSplitter::handle { background: #3c3c3c; }
"""

LIGHT_QSS = """
/* ---- 浅色主题 ---- */
QWidget {
    background-color: #f8f9fa;
    color: #212529;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #f8f9fa;
}
QTabWidget::pane {
    border: 1px solid #dee2e6;
    background: #ffffff;
}
QTabBar::tab {
    background: #e9ecef;
    color: #495057;
    padding: 8px 18px;
    border: 1px solid #dee2e6;
    border-bottom: none;
    min-width: 60px;
}
QTabBar::tab:selected {
    background: #007bff;
    color: #ffffff;
}
QTabBar::tab:hover:!selected {
    background: #dee2e6;
}
QPushButton {
    background: #e9ecef;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 6px 14px;
    color: #212529;
}
QPushButton:hover {
    background: #dee2e6;
    border-color: #007bff;
}
QPushButton:pressed {
    background: #007bff;
    color: #fff;
}
QPushButton:disabled {
    background: #f1f3f5;
    color: #adb5bd;
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
}
QPushButton#success:hover { background: #34ce57; }
QPushButton#danger {
    background: #dc3545;
    border: none;
    color: #fff;
}
QPushButton#danger:hover { background: #e05260; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 4px 8px;
    color: #212529;
    selection-background-color: #007bff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {
    border-color: #007bff;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    color: #212529;
    selection-background-color: #007bff;
}
QCheckBox, QRadioButton {
    color: #212529;
    spacing: 6px;
    background: transparent;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #adb5bd;
    border-radius: 3px;
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
    border: 2px solid #adb5bd;
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
QScrollBar:vertical {
    background: #f8f9fa;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #adb5bd;
    border-radius: 6px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #007bff; }
QScrollBar:horizontal {
    background: #f8f9fa;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #adb5bd;
    border-radius: 6px;
    min-width: 30px;
}
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QListWidget, QTreeWidget, QTableView {
    background: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 4px;
    color: #212529;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #007bff;
    color: #fff;
}
QToolTip {
    background-color: #ffffe0;
    color: #000000;
    border: 1px solid #aaa;
    padding: 6px;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #dee2e6;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #007bff;
}
QProgressBar {
    background: #e9ecef;
    border: 1px solid #ced4da;
    border-radius: 4px;
    text-align: center;
    color: #495057;
    height: 18px;
}
QProgressBar::chunk {
    background: #007bff;
    border-radius: 3px;
}
QSplitter::handle { background: #dee2e6; }
"""

THEME_QSS = {
    "light": LIGHT_QSS,
    "dark": DARK_QSS,
}
