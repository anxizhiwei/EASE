"""ease status — 系统状态。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from cli.banner import SYMBOL
from cli.formatter import box, key_value


def add_parser(subparsers) -> None:
    """向 argparse 注册 status 子命令。"""
    p = subparsers.add_parser("status", help="查看 EASE 系统状态")
    p.add_argument("-f", "--full", action="store_true",
                    help="显示完整信息")


def run(args) -> None:
    """执行 status 子命令。"""
    full = args.full

    esae_home = Path.home() / ".hermes" / "esae"

    # ── 版本信息 ──
    try:
        from cli import __version__
        version = f"v{__version__}"
    except ImportError:
        version = "v0.2.0"

    print(box(" 系统状态 ",
        f"{SYMBOL}  版本:      {version}",
    ))
    print()

    print(key_value("📦 版本:", version))

    # ── 守护进程状态 ──
    pid_file = Path("/tmp/esae_daemon.pid")
    state_file = Path("/tmp/esae_daemon_state")
    heartbeat_file = Path("/tmp/esae_heartbeat")

    daemon_running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            daemon_running = _pid_alive(pid)
            status = f"PID={pid}  {'🟢 运行中' if daemon_running else '🔴 已停止'}"
            print(key_value("⚙️  守护进程:", status))
        except (ValueError, OSError):
            print(key_value("⚙️  守护进程:", "(PID 文件损坏)"))
    else:
        print(key_value("⚙️  守护进程:", "未启动"))

    # ── 双文件心跳状态 ──
    if state_file.exists():
        try:
            lines = state_file.read_text().strip().splitlines()
            state_info = {}
            for line in lines:
                if "=" in line:
                    k, v = line.split("=", 1)
                    state_info[k.strip()] = v.strip()
            tick_count = state_info.get("tick_count", "?")
            success_count = state_info.get("success_count", "?")
            failed_count = state_info.get("failed_count", "?")
            daemon_state = state_info.get("state", "?")
            last_tick = state_info.get("last_tick_time", "?")
            print(key_value("💓 心跳:", f"tick={tick_count}  success={success_count}  failed={failed_count}"))
            print(key_value("🏷️  状态:", daemon_state))
            if last_tick != "?":
                try:
                    sec_ago = int(time.time() - float(last_tick))
                    print(key_value("⏱️  最后 tick:", f"{sec_ago}s 前"))
                except (ValueError, OSError):
                    pass
        except OSError:
            print(key_value("💓 心跳:", "(读取失败)"))

    if heartbeat_file.exists() and full:
        try:
            hb = heartbeat_file.read_text().strip()
            print(key_value("📄 心跳文件:", hb))
        except OSError:
            pass

    # ── 系统信息 ──
    print(key_value("🏠 根目录:", str(esae_home)))
    logs_dir = esae_home / "logs"
    genomes_dir = esae_home / "genomes"
    results_dir = esae_home / "results"

    logs_count = len(list(logs_dir.glob("*"))) if logs_dir.exists() else 0
    genomes_count = len(list(genomes_dir.glob("*"))) if genomes_dir.exists() else 0
    results_count = len(list(results_dir.glob("*/*"))) if results_dir.exists() else 0

    print(key_value("📝 日志文件:", str(logs_count)))
    print(key_value("🧬 Genome 数:", str(genomes_count)))
    print(key_value("📊 结果文件:", str(results_count)))

    # ── Python / 环境 ──
    print()
    print(key_value("🐍 Python:", sys.version.split()[0]))
    print(key_value("🖥️  PID:", str(os.getpid())))

    if full:
        print()
        print("  ── 完整信息 ──")
        print(key_value("CWD:", os.getcwd()))
        print(key_value("USER:", os.environ.get("USER", "?")))
        print(key_value("HOME:", os.environ.get("HOME", "?")))

    print()


def _pid_alive(pid: int) -> bool:
    """检查 PID 是否存活。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
