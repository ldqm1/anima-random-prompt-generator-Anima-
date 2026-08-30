"""配置深合并与用户配置持久化。

- ``deep_merge``：递归合并「默认配置」与「用户配置」。dict 按键递归合并；
  list 与标量直接替换（list 无法按键合并，用户改的是整表）。
- ``load_user_config`` / ``save_user_config``：用户配置存放于用户目录
  ``%APPDATA%/AnimaPromptGenerator/user_config.yaml``（exe 打包版默认 yaml 只读，
  所有 GUI 修改都写入用户目录，启动时覆盖默认值）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def user_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "AnimaPromptGenerator" / "user_config.yaml"


def deep_merge(base: Any, override: Any) -> Any:
    """递归合并两棵 YAML 结构。

    - dict：按键合并（override 的键覆盖/递归合并 base 的键）；
    - 其他（list / 标量 / None）：override 直接替换 base。
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = (
                deep_merge(merged[key], value) if key in merged else value
            )
        return merged
    return override


def load_user_config() -> dict[str, Any]:
    """读取用户配置；不存在或解析失败返回空 dict。"""
    path = user_config_path()
    if not path.exists():
        return {}
    try:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_user_config(cfg: dict[str, Any]) -> bool:
    """保存用户配置到用户目录；失败返回 False。"""
    path = user_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        return True
    except (OSError, ValueError):
        return False


def clear_user_config() -> bool:
    """删除用户配置文件（恢复默认）。"""
    path = user_config_path()
    try:
        if path.exists():
            path.unlink()
        return True
    except OSError:
        return False


def merge_with_defaults(default: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    """默认配置 + 用户配置 → 生效配置。"""
    return deep_merge(default, user)
