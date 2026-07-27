"""ease character — 人物状态管理。"""
from __future__ import annotations
import sys


class CmdCharacter:
    """ease character — 人物状态管理。

    用法:
        ease character <name> [--hp N] [--mp N] [--level N]
        ease character <name> [--damage N | --heal N]
        ease character list
        ease character show <name>
    """

    def __init__(self, args: list[str]) -> None:
        self.args = args

    def run(self) -> None:
        if not self.args:
            print("用法: ease character <name> [options]")
            print("      ease character list")
            print("      ease character show <name>")
            print()
            print("选项:")
            print("  --hp N      设置/更新 HP")
            print("  --mp N      设置/更新 MP")
            print("  --level N   设置/更新 等级")
            print("  --damage N  造成伤害")
            print("  --heal N    治疗")
            return

        # 尝试加载 daemon
        daemon = self._get_daemon()
        if daemon is None:
            return

        cmd = self.args[0]

        if cmd == "list":
            self._cmd_list(daemon)
        elif cmd == "show" and len(self.args) > 1:
            self._cmd_show(daemon, self.args[1])
        else:
            self._cmd_manage(daemon, self.args)

    def _get_daemon(self):
        """获取 ESAEDaemon 实例。"""
        try:
            from kernel.daemon import ESAEDaemon
            return ESAEDaemon()
        except ImportError:
            print("错误: 无法加载 daemon (kernel.daemon)")
            print("请确保在 EASE 项目根目录运行。")
            return None

    def _cmd_list(self, daemon) -> None:
        """列出所有角色。"""
        if hasattr(daemon, "list_characters"):
            names = daemon.list_characters()
            if names:
                print(f"角色列表 ({len(names)}):")
                for name in names:
                    print(f"  • {name}")
            else:
                print("(没有角色)")
        else:
            print("(list_characters 功能尚未进化完成)")

    def _cmd_show(self, daemon, name: str) -> None:
        """显示单个角色。"""
        if hasattr(daemon, "render_character"):
            output = daemon.render_character(name)
            print(output)
        else:
            # 备用显示
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
                print(f"(render_character / get_character 功能尚未进化完成)")

    def _cmd_manage(self, daemon, args: list[str]) -> None:
        """管理角色（创建/更新/施加事件）。"""
        name = args[0]
        kwargs = {}
        i = 1
        has_update = False
        while i < len(args):
            arg = args[i]
            if arg == "--hp" and i + 1 < len(args):
                try:
                    kwargs["hp"] = int(args[i + 1])
                    has_update = True
                    i += 2
                except ValueError:
                    print(f"无效的 HP 值: {args[i+1]}")
                    return
            elif arg == "--mp" and i + 1 < len(args):
                try:
                    kwargs["mp"] = int(args[i + 1])
                    has_update = True
                    i += 2
                except ValueError:
                    print(f"无效的 MP 值: {args[i+1]}")
                    return
            elif arg == "--level" and i + 1 < len(args):
                try:
                    kwargs["level"] = int(args[i + 1])
                    has_update = True
                    i += 2
                except ValueError:
                    print(f"无效的 level 值: {args[i+1]}")
                    return
            elif arg == "--damage" and i + 1 < len(args):
                try:
                    if hasattr(daemon, "apply_to_character"):
                        daemon.apply_to_character(name, "damage", int(args[i + 1]))
                        print(f"✅ {name} 受到 {args[i+1]} 点伤害")
                    else:
                        print("(apply_to_character 功能尚未进化完成)")
                    i += 2
                    return
                except ValueError:
                    print(f"无效的 damage 值: {args[i+1]}")
                    return
            elif arg == "--heal" and i + 1 < len(args):
                try:
                    if hasattr(daemon, "apply_to_character"):
                        daemon.apply_to_character(name, "heal", int(args[i + 1]))
                        print(f"✅ {name} 获得 {args[i+1]} 点治疗")
                    else:
                        print("(apply_to_character 功能尚未进化完成)")
                    i += 2
                    return
                except ValueError:
                    print(f"无效的 heal 值: {args[i+1]}")
                    return
            else:
                print(f"未知选项: {arg}")
                return

        if has_update and hasattr(daemon, "add_character"):
            daemon.add_character(name, **kwargs)
            keys = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            print(f"✅ 角色 '{name}' 已更新 ({keys})")
        elif has_update:
            print("(add_character 功能尚未进化完成)")
        else:
            # 纯查询
            if hasattr(daemon, "get_character"):
                state = daemon.get_character(name)
                if state:
                    print(f"[{name}]  HP={state.get('hp','?')}  MP={state.get('mp','?')}  Level={state.get('level','?')}")
                else:
                    print(f"角色 '{name}' 不存在。使用 --hp/--mp/--level 创建。")
            else:
                print(f"用法: ease character {name} [--hp N] [--mp N] [--level N]")
