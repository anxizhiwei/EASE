"""EASE — Emergent-Stitching Architecture for Evolution
终端应用入口。
"""
import sys, os

from .banner import BANNER
from .commands.evolve import CmdEvolve
from .commands.character import CmdCharacter
from .commands.status import CmdStatus

__version__ = "0.2.0"


def main():
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    
    if not args or args[0] in ("-h", "--help", "help"):
        _show_help()
        return
    
    if args[0] in ("-v", "--version", "version"):
        print(f"EASE v{__version__}")
        return
    
    cmd, *rest = args
    
    if cmd == "evolve":
        CmdEvolve(rest).run()
    elif cmd == "character":
        CmdCharacter(rest).run()
    elif cmd == "status":
        CmdStatus(rest).run()
    elif cmd == "ui":
        _show_ui()
    elif cmd == "shell":
        _repl()
    else:
        print(f"未知命令: {cmd}")
        _show_help()


def _show_help():
    print(BANNER)
    print()
    print("  用法: ease <命令> [选项]")
    print()
    print("  命令:")
    print("    evolve        运行进化"
          "\n    character     人物状态管理"
          "\n    ui            显示界面"
          "\n    status        系统状态"
          "\n    shell         交互式终端"
          "\n    version       显示版本"
          "\n    help          显示帮助")
    print()


def _show_ui():
    """显示角色界面（调用 daemon.py 的 render 方法）。"""
    from kernel.daemon import ESAEDaemon
    d = ESAEDaemon()
    print(d.render_all_characters())


def _repl():
    """交互式终端。"""
    import readline
    print(BANNER)
    print(f"  EASE v{__version__} 交互式终端 — 输入 help 查看命令\n")
    while True:
        try:
            line = input("ease> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not line:
            continue
        if line == "exit" or line == "quit":
            break
        if line == "help":
            _show_help()
            continue
        # 当作命令重新调用
        sys.argv = ["ease"] + line.split()
        main()
