#!/usr/bin/env python3
"""一键打包 Anima 随机提示词生成器为单文件 exe。

用法：
    python build_exe.py            # 打包（默认 release 构建）
    python build_exe.py --clean    # 打包前清理 build/dist 缓存

产物：dist/AnimaPromptGenerator.exe（单文件，双击即用）
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "anima_gui.spec"


def _ensure_deps() -> None:
    """确保 PyInstaller 与 ttkbootstrap 已安装（仅打包机需要，exe 用户无需）。"""
    try:
        import PyInstaller  # noqa: F401
        import ttkbootstrap  # noqa: F401
    except ImportError:
        print("安装打包依赖（pyinstaller / ttkbootstrap）…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "ttkbootstrap"]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 Anima GUI 为单文件 exe")
    parser.add_argument("--clean", action="store_true", help="打包前清理 build/ 与 dist/")
    args = parser.parse_args()

    _ensure_deps()

    if args.clean:
        for d in ("build", "dist"):
            p = ROOT / d
            if p.exists():
                shutil.rmtree(p)
                print(f"已清理 {d}/")

    print(f"打包：{SPEC.name}")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)]
    subprocess.check_call(cmd, cwd=str(ROOT))

    exe = ROOT / "dist" / "AnimaPromptGenerator.exe"
    if not exe.exists():
        print("错误：未找到产物 dist/AnimaPromptGenerator.exe", file=sys.stderr)
        return 1
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\n打包完成：{exe}")
    print(f"大小：{size_mb:.1f} MB")
    print("交付：把该 exe 复制给用户即可（无需安装 Python）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
