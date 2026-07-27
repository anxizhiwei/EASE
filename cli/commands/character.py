"""ease character — 人物状态管理。"""
from __future__ import annotations

import sys
from argparse import _SubParsersAction


def add_parser(subparsers: _SubParsersAction) -> None:
    """向 argparse 注册 character 子命令树。"""
    p = subparsers.add_parser("character", help="人物状态管理（创建/查看/列表）")

    # 嵌套子命令: character {create,update,show,list,delete}
    subs = p.add_subparsers(dest="char_action", help="人物操作")
    subs.required = False

    # create
    pc = subs.add_parser("create", help="创建新角色")
    pc.add_argument("name", help="角色名称")
    pc.add_argument("--hp", type=int, default=100, help="HP（默认: 100）")
    pc.add_argument("--mp", type=int, default=50, help="MP（默认: 50）")
    pc.add_argument("--level", type=int, default=1, help="等级（默认: 1）")

    # update
    pu = subs.add_parser("update", help="更新角色属性")
    pu.add_argument("name", help="角色名称")
    pu.add_argument("--hp", type=int, default=None, help="设置 HP")
    pu.add_argument("--mp", type=int, default=None, help="设置 MP")
    pu.add_argument("--level", type=int, default=None, help="设置等级")

    # show
    ps = subs.add_parser("show", help="查看角色详情")
    ps.add_argument("name", help="角色名称")

    # list
    subs.add_parser("list", help="列出所有角色")

    # delete
    pd = subs.add_parser("delete", help="删除角色")
    pd.add_argument("name", help="角色名称")


def run(args) -> None:
    """执行 character 子命令。"""
    daemon = _get_daemon()
    if daemon is None:
        return

    action = args.char_action

    if action == "list":
        _cmd_list(daemon)
    elif action == "show":
        _cmd_show(daemon, args.name)
    elif action == "create":
        _cmd_create(daemon, args.name, hp=args.hp, mp=args.mp, level=args.level)
    elif action == "update":
        _cmd_update(daemon, args.name, hp=args.hp, mp=args.mp, level=args.level)
    elif action == "delete":
        _cmd_delete(daemon, args.name)
    else:
        # 无子命令 → 显示用法
        print("用法: ease character {create,update,show,list,delete} [...]")
        print("      ease character create <name> [--hp N] [--mp N] [--level N]")
        print("      ease character update <name> [--hp N] [--mp N] [--level N]")
        print("      ease character show <name>")
        print("      ease character list")
        print("      ease character delete <name>")


def _get_daemon():
    """获取 ESAEDaemon 实例。"""
    try:
        from kernel.daemon import ESAEDaemon
        return ESAEDaemon()
    except ImportError:
        print("错误: 无法加载 daemon (kernel.daemon)")
        print("请确保在 EASE 项目根目录运行。")
        return None


def _ensure_daemon_capability(daemon, cap: str) -> bool:
    """确认 daemon 有某功能，否则打印提示。"""
    if hasattr(daemon, cap):
        return True
    print(f"({cap} 功能尚未进化完成)")
    return False


def _cmd_list(daemon) -> None:
    """列出所有角色。"""
    if not _ensure_daemon_capability(daemon, "list_characters"):
        return
    names = daemon.list_characters()
    if names:
        print(f"角色列表 ({len(names)}):")
        for name in names:
            print(f"  • {name}")
    else:
        print("(没有角色)")


def _cmd_show(daemon, name: str) -> None:
    """显示单个角色。"""
    if hasattr(daemon, "render_character"):
        output = daemon.render_character(name)
        print(output)
        return

    if hasattr(daemon, "get_character"):
        state = daemon.get_character(name)
        if state:
            hp = state.get("hp", "?")
            mp = state.get("mp", "?")
            level = state.get("level", "?")
            print(f"  [{name}]  HP={hp}  MP={mp}  Lv.{level}")
        else:
            print(f"角色 '{name}' 不存在。")
    else:
        print("(render_character / get_character 功能尚未进化完成)")


def _cmd_create(daemon, name: str, **kwargs) -> None:
    """创建新角色。"""
    if not _ensure_daemon_capability(daemon, "add_character"):
        return
    daemon.add_character(name, **kwargs)
    keys = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    print(f"✅ 角色 '{name}' 已创建 ({keys})")


def _cmd_update(daemon, name: str, **kwargs) -> None:
    """更新角色属性。"""
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    if not filtered:
        print("没有指定要更新的属性。使用 --hp / --mp / --level")
        return

    if not _ensure_daemon_capability(daemon, "add_character"):
        return
    daemon.add_character(name, **filtered)
    keys = ", ".join(f"{k}={v}" for k, v in filtered.items())
    print(f"✅ 角色 '{name}' 已更新 ({keys})")


def _cmd_delete(daemon, name: str) -> None:
    """删除角色。"""
    if not _ensure_daemon_capability(daemon, "delete_character"):
        return
    daemon.delete_character(name)
    print(f"✅ 角色 '{name}' 已删除")
