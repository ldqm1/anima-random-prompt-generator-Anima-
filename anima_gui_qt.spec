# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：Anima 随机提示词生成器 PySide6 版（单文件 exe）。

用法：python build_exe_qt.py
"""
import os

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = os.path.abspath(SPECPATH)  # noqa: F821

# PySide6 动态库（Qt6Core/Gui/Widgets 等）。平台插件由 PyInstaller 的
# hook-PySide6 自动收集，无需手动 collect_all。
pyside6_binaries = collect_dynamic_libs("PySide6")

datas = [
    (os.path.join(ROOT, "知识库"), "知识库"),
    (os.path.join(ROOT, "source", "animadex_index.csv"), "source"),
    (os.path.join(ROOT, "source", "artists.csv"), "source"),
    (os.path.join(ROOT, "prompt", "random_generator", "system_prompt.md"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "system_prompt_plain.md"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "user_prompt.jinja"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "generation_config.yaml"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "creative_anchors.yaml"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "curated_tags.yaml"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "character_pool.json"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "character_pool_series_index.json"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "r18_euphemisms.yaml"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "r18_topics.yaml"), "prompt/random_generator"),
    (os.path.join(ROOT, "prompt", "random_generator", "semantic_exclude.yaml"), "prompt/random_generator"),
    # 配置文档（HTML + 截图）
    (os.path.join(ROOT, "docs"), "docs"),
]

binaries = pyside6_binaries

a = Analysis(
    [os.path.join(ROOT, "anima_gui_qt.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "prompt.random_generator.gui_qt",
        "prompt.random_generator.gui_qt.app",
        "prompt.random_generator.gui_qt.forms",
        "prompt.random_generator.gui_qt.theme",
        "prompt.random_generator.gui_qt.tooltip",
        "prompt.random_generator.gui_qt.toast",
        "prompt.random_generator.gui_engine",
        "prompt.random_generator.config_merge",
        "prompt.random_generator.config_presets",
        "prompt.random_generator.yaml_comments",
        "prompt.random_generator.cli",
        "PySide6",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas", "numpy", "openpyxl", "matplotlib", "IPython", "jupyter",
        "notebook", "prompt_toolkit",
        "PySide6.QtWebEngine", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtLocation",
        "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtSvg",
        "PySide6.QtTest", "PySide6.QtWebSockets", "PySide6.QtXml",
        "PySide6.QtHelp", "PySide6.QtDesigner", "PySide6.QtUiTools",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AnimaPromptGenerator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
