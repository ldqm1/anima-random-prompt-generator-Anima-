#!/usr/bin/env python3
"""一键打包 Anima 随机提示词生成器（PySide6 版）为单文件 exe。

用法：
    python build_exe_qt.py            # 打包（默认 release 构建）
    python build_exe_qt.py --clean    # 清理 build/dist 后打包

产物：dist/AnimaPromptGenerator.exe（PySide6 版，体积较大）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "anima_gui_qt.spec"


def _ensure_deps() -> None:
    try:
        import PyInstaller  # noqa: F401
        import PySide6  # noqa: F401
    except ImportError:
        print("安装打包依赖（pyinstaller / PySide6）…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "PySide6"]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 Anima GUI（PySide6）为单文件 exe")
    parser.add_argument("--clean", action="store_true", help="打包前清理 build/ 与 dist/")
    args = parser.parse_args()

    _ensure_deps()

    if args.clean:
        for d in ("build", "dist"):
            p = ROOT / d
            if p.exists():
                shutil.rmtree(p)
                print(f"已清理 {d}/")

    print(f"打包：{SPEC.name}（PySide6 版）")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)]
    subprocess.check_call(cmd, cwd=str(ROOT))

    exe = ROOT / "dist" / "AnimaPromptGenerator.exe"
    if not exe.exists():
        print("错误：未找到产物 dist/AnimaPromptGenerator.exe", file=sys.stderr)
        return 1
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\n打包完成：{exe}")
    print(f"大小：{size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
