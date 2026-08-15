#!/usr/bin/env python3
"""项目根目录快捷入口：透传参数调用 prompt.random_generator.cli"""
import sys

from prompt.random_generator.cli import main

if __name__ == "__main__":
    argv = sys.argv[1:]
    # 当前 CLI 只有 generate 一个子命令，根目录快捷入口允许省略它。
    if not argv or argv[0].startswith("-"):
        argv = ["generate", *argv]
    sys.exit(main(argv))
