"""配置预设（Profile）管理：多套配置的保存 / 切换 / 导入 / 导出。

概念：
- 一个**预设** = 一整套生成配置（generation_config 的用户覆盖 + 创意锚点覆盖）。
- 预设存储在用户目录 ``%APPDATA%/AnimaPromptGenerator/profiles.json``，
  ``{"profiles": {"<名>": {"gen": {...}, "anchors": {...}}}, "active": "<名>"}``。
- **内置默认预设**（"默认"）不可删除：其配置为空，表示完全使用打包默认值。
- 切换预设时：把当前高级页表单收集结果保存到当前预设，再加载目标预设。
- 激活预设会写入 ``user_config.yaml``（引擎读取的合并源），保持与 CLI 一致。

与旧版兼容：若存在旧 ``user_config.yaml`` 但无 profiles.json，迁移为
"默认" 预设的非空版本。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config_merge import (
    clear_user_config,
    load_user_config,
    merge_with_defaults,
    save_user_config,
    user_config_path,
)

# 内置默认预设名
DEFAULT_PROFILE = "默认"


def profiles_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "AnimaPromptGenerator" / "profiles.json"


def _empty_profile() -> dict[str, Any]:
    return {"gen": {}, "anchors": {}}


def load_profiles() -> dict[str, Any]:
    """读取全部预设；不存在时初始化为只含「默认」空预设。"""
    path = profiles_path()
    data: dict[str, Any] = {"profiles": {}, "active": DEFAULT_PROFILE}
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                if isinstance(loaded.get("profiles"), dict):
                    data["profiles"] = loaded["profiles"]
                if isinstance(loaded.get("active"), str) and loaded["active"]:
                    data["active"] = loaded["active"]
        except (OSError, ValueError):
            pass
    # 保证默认预设存在
    if DEFAULT_PROFILE not in data["profiles"]:
        data["profiles"][DEFAULT_PROFILE] = _empty_profile()
    # 迁移旧 user_config.yaml（无 profiles 时）
    if not path.exists():
        old = load_user_config()
        if old:
            gen = {k: v for k, v in old.items() if k != "creative_anchors_override"}
            anchors = old.get("creative_anchors_override") or {}
            if gen or anchors:
                data["profiles"][DEFAULT_PROFILE] = {"gen": gen, "anchors": anchors}
                # 迁移后保留 user_config.yaml 作为激活态（不重复写入）
                data["active"] = DEFAULT_PROFILE
                _write_profiles(data)
    if data["active"] not in data["profiles"]:
        data["active"] = DEFAULT_PROFILE
    return data


def _write_profiles(data: dict[str, Any]) -> bool:
    path = profiles_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def list_profile_names() -> list[str]:
    data = load_profiles()
    return list(data["profiles"].keys())


def get_active_name() -> str:
    return load_profiles()["active"]


def get_profile(name: str) -> dict[str, Any] | None:
    data = load_profiles()
    return data["profiles"].get(name)


def create_profile(
    name: str,
    gen: dict[str, Any] | None = None,
    anchors: dict[str, Any] | None = None,
) -> bool:
    """新建预设（名称去空格；已存在返回 False）。"""
    name = name.strip()
    if not name:
        return False
    data = load_profiles()
    if name in data["profiles"]:
        return False
    data["profiles"][name] = {
        "gen": gen or {},
        "anchors": anchors or {},
    }
    return _write_profiles(data)


def rename_profile(old: str, new: str) -> bool:
    new = new.strip()
    if not new or old == DEFAULT_PROFILE:
        return False
    data = load_profiles()
    if old not in data["profiles"] or new in data["profiles"]:
        return False
    data["profiles"][new] = data["profiles"].pop(old)
    if data["active"] == old:
        data["active"] = new
    return _write_profiles(data)


def delete_profile(name: str) -> bool:
    if name == DEFAULT_PROFILE:
        return False  # 默认不可删
    data = load_profiles()
    if name not in data["profiles"]:
        return False
    del data["profiles"][name]
    if data["active"] == name:
        data["active"] = DEFAULT_PROFILE
    return _write_profiles(data)


def save_profile(name: str, gen: dict[str, Any], anchors: dict[str, Any]) -> bool:
    """保存（覆盖）预设内容。"""
    data = load_profiles()
    if name not in data["profiles"]:
        data["profiles"][name] = _empty_profile()
    data["profiles"][name]["gen"] = gen
    data["profiles"][name]["anchors"] = anchors
    return _write_profiles(data)


def set_active(name: str) -> bool:
    """切换激活预设，并把其配置写入 user_config.yaml（引擎读取源）。"""
    data = load_profiles()
    if name not in data["profiles"]:
        return False
    data["active"] = name
    if not _write_profiles(data):
        return False
    profile = data["profiles"][name]
    # 写入 user_config.yaml：gen 覆盖 + anchors 覆盖
    user_cfg: dict[str, Any] = dict(profile.get("gen") or {})
    anchors = profile.get("anchors") or {}
    if anchors:
        user_cfg["creative_anchors_override"] = anchors
    return save_user_config(user_cfg)


def export_profile(name: str) -> dict[str, Any] | None:
    """导出预设为可分享的 dict（含元信息）。"""
    data = load_profiles()
    if name not in data["profiles"]:
        return None
    profile = data["profiles"][name]
    return {
        "profile_name": name,
        "version": 1,
        "gen": profile.get("gen") or {},
        "anchors": profile.get("anchors") or {},
    }


def import_profile(payload: dict[str, Any], new_name: str | None = None) -> tuple[bool, str]:
    """从导出 dict 导入为新预设。返回 (成功, 消息/预设名)。"""
    if not isinstance(payload, dict):
        return False, "文件格式无效"
    gen = payload.get("gen")
    anchors = payload.get("anchors")
    if not isinstance(gen, dict) or not isinstance(anchors, dict):
        return False, "文件缺少 gen / anchors 字段"
    name = (new_name or str(payload.get("profile_name") or "")).strip()
    if not name:
        return False, "预设名称为空"
    # 重名自动加后缀
    data = load_profiles()
    base = name
    i = 2
    while name in data["profiles"]:
        name = f"{base} ({i})"
        i += 1
    data["profiles"][name] = {"gen": gen, "anchors": anchors}
    if not _write_profiles(data):
        return False, "写入失败"
    return True, name


def validate_profile_payload(payload: Any) -> bool:
    """校验导入的 dict 是否为合法预设（用于导入前预检）。"""
    return isinstance(payload, dict) and isinstance(payload.get("gen"), dict) and isinstance(payload.get("anchors"), dict)
