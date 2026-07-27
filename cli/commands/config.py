"""ease config — 配置管理。

用法:
    ease config show              查看当前配置
    ease config set <key> <value>  设置配置项
    ease config path               显示配置文件路径
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# ── 默认配置 ─────────────────────────────────────────────────
DEFAULT_CONFIG: dict[str, object] = {
    "generations": 50,
    "verbose": True,
    "color": True,
    "log_level": "INFO",
}

CONFIG_FILE = Path.home() / ".hermes" / "esae" / "config.json"


def _ensure_config() -> dict[str, object]:
    """读取配置，如果文件不存在则创建默认配置。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            if not isinstance(data, dict):
                raise ValueError("配置必须是 JSON 对象")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️  配置文件损坏 ({e})，使用默认配置")
            return dict(DEFAULT_CONFIG)
    else:
        _write_config(dict(DEFAULT_CONFIG))
        return dict(DEFAULT_CONFIG)


def _write_config(data: dict[str, object]) -> None:
    """安全写入配置文件。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(CONFIG_FILE)


# ── 子命令 ──────────────────────────────────────────────────

def cmd_show() -> None:
    """ease config show — 显示配置。"""
    cfg = _ensure_config()
    print(f"  📝 EASE 配置 ({CONFIG_FILE})")
    print()
    for key, value in cfg.items():
        print(f"    {key:<14} = {value}")
    print()


def cmd_set(key: str, value: str) -> None:
    """ease config set <key> <value> — 设置配置项。"""
    cfg = _ensure_config()

    # 类型推断
    typed_value: object = value
    if value.lower() in ("true", "false"):
        typed_value = value.lower() == "true"
    else:
        try:
            if "." in value:
                typed_value = float(value)
            else:
                typed_value = int(value)
        except ValueError:
            typed_value = value  # keep as string

    cfg[key] = typed_value
    _write_config(cfg)
    print(f"  ✅ 已设置: {key} = {typed_value}")
    print()


def cmd_path() -> None:
    """ease config path — 显示配置文件路径。"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    exists = "存在" if CONFIG_FILE.exists() else "不存在"
    print(f"  📂 配置文件: {CONFIG_FILE} ({exists})")


def add_parser(subparsers) -> None:
    """向 argparse 注册 config 子命令。"""
    p = subparsers.add_parser("config", help="配置管理（查看/设置/路径）")
    p.add_argument("action", nargs="?", choices=["show", "set", "path"], default="show",
                    help="操作: show=查看, set=设置, path=路径")
    p.add_argument("key", nargs="?", default=None, help="配置键名")
    p.add_argument("value", nargs="?", default=None, help="配置值")


def run(args) -> None:
    """执行 config 子命令。"""
    action = args.action
    if action == "show":
        cmd_show()
    elif action == "set":
        if args.key is None or args.value is None:
            print("用法: ease config set <key> <value>")
            sys.exit(1)
        cmd_set(args.key, args.value)
    elif action == "path":
        cmd_path()
    else:
        print(f"未知 config 操作: {action}")
        sys.exit(1)
