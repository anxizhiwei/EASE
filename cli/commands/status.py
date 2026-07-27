"""ease status — 系统状态。"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path


class CmdStatus:
    """ease status — 查看 EASE 系统状态。

    用法:
        ease status
        ease status --full
    """

    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.full = False

    def run(self) -> None:
        self._parse_args()
        self._show_status()

    def _parse_args(self) -> None:
        for arg in self.args:
            if arg in ("-f", "--full"):
                self.full = True
            else:
                print(f"未知选项: {arg}")
                print("用法: ease status [--full]")

    def _show_status(self) -> None:
        from cli.banner import SYMBOL

        esae_home = Path.home() / ".hermes" / "esae"

        print(f"  {SYMBOL}  系统状态")
        print()

        # ── 版本信息 ──
        try:
            from cli import __version__
            print(f"  📦 版本:      v{__version__}")
        except ImportError:
            print(f"  📦 版本:      v0.2.0")

        # ── 守护进程状态 ──
        pid_file = Path("/tmp/esae_daemon.pid")
        state_file = Path("/tmp/esae_daemon_state")
        heartbeat_file = Path("/tmp/esae_heartbeat")

        daemon_running = False
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                daemon_running = self._pid_alive(pid)
                print(f"  ⚙️  守护进程:  PID={pid}  {'🟢 运行中' if daemon_running else '🔴 已停止'}")
            except (ValueError, OSError):
                print(f"  ⚙️  守护进程:  (PID 文件损坏)")
        else:
            print(f"  ⚙️  守护进程:  未启动")

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
                print(f"  💓 心跳:      tick={tick_count}  success={success_count}  failed={failed_count}")
                print(f"  🏷️  状态:      {daemon_state}")
                if last_tick != "?":
                    try:
                        sec_ago = int(time.time() - float(last_tick))
                        print(f"  ⏱️  最后 tick:  {sec_ago}s 前")
                    except (ValueError, OSError):
                        pass
            except OSError:
                print(f"  💓 心跳:      (读取失败)")

        if heartbeat_file.exists() and self.full:
            try:
                hb = heartbeat_file.read_text().strip()
                print(f"  📄 心跳文件:  {hb}")
            except OSError:
                pass

        # ── 系统信息 ──
        print(f"  🏠 根目录:    {esae_home}")
        logs_dir = esae_home / "logs"
        genomes_dir = esae_home / "genomes"
        results_dir = esae_home / "results"

        logs_count = len(list(logs_dir.glob("*"))) if logs_dir.exists() else 0
        genomes_count = len(list(genomes_dir.glob("*"))) if genomes_dir.exists() else 0
        results_count = len(list(results_dir.glob("*/*"))) if results_dir.exists() else 0

        print(f"  📝 日志文件:   {logs_count}")
        print(f"  🧬 Genome 数: {genomes_count}")
        print(f"  📊 结果文件:   {results_count}")

        # ── Python / 环境 ──
        print()
        print(f"  🐍 Python:     {sys.version.split()[0]}")
        print(f"  🖥️  PID:       {os.getpid()}")

        if self.full:
            print()
            print(f"  ── 完整信息 ──")
            print(f"  CWD:  {os.getcwd()}")
            print(f"  USER: {os.environ.get('USER', '?')}")
            print(f"  HOME: {os.environ.get('HOME', '?')}")

        print()

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
