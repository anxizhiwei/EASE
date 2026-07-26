#!/usr/bin/env python3
"""ESAE 独立看守进程 — 独立PID + kill switch + 双文件心跳。

参考：Hermes cron 双文件心跳模式（heartbeat + last_success）。
纯 stdlib 实现，零第三方依赖。

用法：
    python3 daemon.py start      # 后台启动守护进程
    python3 daemon.py stop       # 优雅停止守护进程
    python3 daemon.py status     # 查看守护进程状态
    python3 daemon.py run        # 前台运行（调试用）
"""

import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
PID_FILE = Path("/tmp/esae_daemon.pid")
HEARTBEAT_FILE = Path("/tmp/esae_heartbeat")
SUCCESS_FILE = Path("/tmp/esae_success")
KILL_FILE = Path("/tmp/esae_kill")
STATE_FILE = Path("/tmp/esae_daemon_state")


# ──────────────────────────────────────────────
# 心跳状态
# ──────────────────────────────────────────────
@dataclass
class HeartbeatState:
    """双文件心跳状态。

    - heartbeat: 每次 tick 更新（任何 tick）
    - last_success: 成功 tick 才更新（区分「活着但失败」和「全死」）
    """
    pid: int
    tick_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    last_tick_time: float = 0.0
    last_success_time: float = 0.0
    state: str = "starting"  # starting / running / degraded / stopped


# ──────────────────────────────────────────────
# ESAE 守护进程
# ──────────────────────────────────────────────
class ESAEDaemon:
    """ESAE 独立看守进程。

    参考：
    - Hermes cron 双文件心跳模式
    - Resilience4j 健康检测

    属性:
        esae_home: ESAE 根目录 (~/.hermes/esae/)
        interval: 心跳间隔（秒）
        running: 进程是否运行中
    """

    def __init__(self, esae_home: Optional[Path] = None, interval: float = 5.0):
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"
        self.interval = interval
        self.running = False
        self._shutdown = False
        self.heartbeat = HeartbeatState(pid=os.getpid())

        # 确保目录存在
        (self.esae_home / "logs").mkdir(parents=True, exist_ok=True)
        (self.esae_home / "genomes").mkdir(parents=True, exist_ok=True)

        # 注册信号处理
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    # ─── 主循环 ───────────────────────────────

    def run(self) -> None:
        """主循环：check_kill_switch → tick → sleep。"""
        self.running = True
        self.heartbeat.state = "running"
        self._log("daemon started (pid=%d, interval=%.1fs)", os.getpid(), self.interval)
        self._write_state()

        while not self._shutdown:
            try:
                # 1. 检查哨兵文件
                if self.check_kill_switch():
                    self._log("kill switch detected, shutting down")
                    break

                # 2. 执行单次心跳
                self.tick()

                # 3. 休眠
                for _ in range(max(1, int(self.interval / 0.5))):
                    if self._shutdown:
                        break
                    time.sleep(0.5)

            except KeyboardInterrupt:
                self._log("keyboard interrupt received")
                break
            except Exception as exc:
                self._log("unexpected error in main loop: %s", exc)
                self.heartbeat.failed_count += 1
                if self.heartbeat.failed_count >= 5:
                    self.heartbeat.state = "degraded"
                    self._write_state()
                time.sleep(1.0)

        self.stop()

    # ─── 心跳 ─────────────────────────────────

    def tick(self) -> None:
        """单次心跳：更新双文件 + 检查健康。

        总是更新 /tmp/esae_heartbeat。
        仅在成功时更新 /tmp/esae_success。
        """
        now = time.time()
        self.heartbeat.tick_count += 1
        self.heartbeat.last_tick_time = now

        # 写心跳文件（每次 tick 都写）
        self._write_heartbeat_files(now)

        # 标记成功
        self.heartbeat.success_count += 1
        self.heartbeat.last_success_time = now
        self._write_success_file(now)

        # 每 10 次 tick 写一次日志
        if self.heartbeat.tick_count % 10 == 0:
            self._log(
                "heartbeat #%d: success=%d failed=%d state=%s",
                self.heartbeat.tick_count,
                self.heartbeat.success_count,
                self.heartbeat.failed_count,
                self.heartbeat.state,
            )

    # ─── 停止 ─────────────────────────────────

    def stop(self) -> None:
        """优雅退出：写状态文件 + 清理 PID + 清理哨兵。"""
        if self.heartbeat.state == "stopped":
            return

        self.running = False
        self.heartbeat.state = "stopped"
        self._log("daemon stopping gracefully")

        # 写终止状态
        self._write_state()

        # 清理 PID 文件
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                if pid == os.getpid():
                    PID_FILE.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass

        # 清理哨兵文件（避免下次误杀）
        KILL_FILE.unlink(missing_ok=True)

        self._log("daemon stopped (ticks=%d, successes=%d, failures=%d)",
                   self.heartbeat.tick_count,
                   self.heartbeat.success_count,
                   self.heartbeat.failed_count)

    # ─── 双文件心跳 ───────────────────────────

    def _write_heartbeat_files(self, now: float) -> None:
        """更新心跳文件 /tmp/esae_heartbeat。

        格式：<unix_timestamp> <pid> <tick_count>
        """
        try:
            content = f"{now:.3f} {os.getpid()} {self.heartbeat.tick_count}\n"
            HEARTBEAT_FILE.write_text(content)
        except OSError as exc:
            self._log("failed to write heartbeat file: %s", exc)

    def _write_success_file(self, now: float) -> None:
        """更新成功文件 /tmp/esae_success。

        格式：<unix_timestamp> <pid> <success_count>
        """
        try:
            content = f"{now:.3f} {os.getpid()} {self.heartbeat.success_count}\n"
            SUCCESS_FILE.write_text(content)
        except OSError as exc:
            self._log("failed to write success file: %s", exc)

    def _write_state(self) -> None:
        """将当前状态写入 /tmp/esae_daemon_state。"""
        try:
            pid = os.getpid()
            hb = self.heartbeat
            content = (
                f"pid={pid}\n"
                f"state={hb.state}\n"
                f"tick_count={hb.tick_count}\n"
                f"success_count={hb.success_count}\n"
                f"failed_count={hb.failed_count}\n"
                f"last_tick_time={hb.last_tick_time:.3f}\n"
                f"last_success_time={hb.last_success_time:.3f}\n"
                f"running={int(self.running)}\n"
            )
            STATE_FILE.write_text(content)
        except OSError as exc:
            self._log("failed to write state file: %s", exc)

    # ─── 哨兵检查 ─────────────────────────────

    def check_kill_switch(self) -> bool:
        """检查 /tmp/esae_kill 哨兵文件。

        如果文件内容以 'stop' 开头则返回 True。
        如果文件存在（任何内容）也返回 True（防御性）。
        """
        if not KILL_FILE.exists():
            return False
        try:
            content = KILL_FILE.read_text().strip().lower()
            if content.startswith("stop"):
                return True
            # 只要文件存在即为 kill 信号
            self._log("kill file present (content=%r), treating as stop signal", content)
            return True
        except OSError:
            return False

    # ─── 信号处理 ─────────────────────────────

    def _handle_signal(self, signum: int, _frame) -> None:
        """SIGTERM/SIGINT 信号处理器。"""
        sig_name = signal.Signals(signum).name
        self._log("received signal %s (%d), initiating graceful shutdown", sig_name, signum)
        self._shutdown = True

    # ─── 日志 ─────────────────────────────────

    def _log(self, fmt: str, *args) -> None:
        """日志：写 stdout + 日志文件。"""
        msg = fmt % args if args else fmt
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [esae-daemon] {msg}"

        # stdout
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass

        # 日志文件
        log_path = self.esae_home / "logs" / "daemon.log"
        try:
            with open(log_path, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────
def cmd_start() -> int:
    """后台启动守护进程（fork 模式）。"""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if _is_pid_alive(pid):
                print(f"daemon already running (pid={pid})")
                return 0
        except (ValueError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 清除旧的哨兵文件
    KILL_FILE.unlink(missing_ok=True)

    pid = os.fork()
    if pid > 0:
        # 父进程：等待中间子进程退出（第二次 fork 已完成）
        os.waitpid(pid, 0)
        # 此时孙进程已写入 PID 文件
        try:
            actual_pid = int(PID_FILE.read_text().strip())
            print(f"daemon started (pid={actual_pid})")
        except (ValueError, OSError):
            print("daemon started")
        return 0

    # 第一次 fork 的子进程：脱离终端
    os.setsid()
    # 第二次 fork 确保完全脱离控制终端
    pid2 = os.fork()
    if pid2 > 0:
        # 中间子进程：退出，让孙进程成为真正的孤儿
        os._exit(0)

    # 孙进程（真正的守护进程）
    grand_pid = os.getpid()
    # 立即写 PID 文件
    PID_FILE.write_text(str(grand_pid))

    # 重定向标准文件描述符到 /dev/null（避免 print 崩溃）
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        try:
            os.dup2(devnull, fd)
        except OSError:
            pass
    if devnull > 2:
        os.close(devnull)

    daemon = ESAEDaemon()
    daemon.run()
    os._exit(0)


def cmd_stop() -> int:
    """优雅停止守护进程。"""
    if not PID_FILE.exists():
        print("daemon not running")
        return 1

    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError) as exc:
        print(f"failed to read PID file: {exc}")
        return 1

    if not _is_pid_alive(pid):
        print(f"daemon not running (stale pid={pid})")
        PID_FILE.unlink(missing_ok=True)
        return 1

    # 先写哨兵文件，确保 kill switch 路径也生效
    try:
        KILL_FILE.write_text("stop\n")
    except OSError:
        pass

    # 发送 SIGTERM 优雅终止
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"stop signal sent to pid={pid}")
    except OSError as exc:
        print(f"failed to send signal: {exc}")
        return 1

    # 等待进程退出
    for _ in range(20):
        if not _is_pid_alive(pid):
            print("daemon stopped")
            PID_FILE.unlink(missing_ok=True)
            return 0
        time.sleep(0.25)

    # 超时后强制 kill
    print("daemon did not stop gracefully, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return 0


def cmd_status() -> int:
    """查看守护进程状态。"""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            alive = _is_pid_alive(pid)
            print(f"pid={pid}  running={alive}")
        except (ValueError, OSError) as exc:
            print(f"pid file error: {exc}")
    else:
        print("pid=(none)  running=False")

    # 读取状态文件
    if STATE_FILE.exists():
        try:
            for line in STATE_FILE.read_text().strip().splitlines():
                print(f"  {line}")
        except OSError as exc:
            print(f"  state file error: {exc}")
    else:
        print("  state=(none)")

    # 读取心跳文件
    if HEARTBEAT_FILE.exists():
        try:
            hb = HEARTBEAT_FILE.read_text().strip()
            print(f"  heartbeat={hb}")
        except OSError:
            print("  heartbeat=(unreadable)")
    else:
        print("  heartbeat=(none)")

    if SUCCESS_FILE.exists():
        try:
            sc = SUCCESS_FILE.read_text().strip()
            print(f"  last_success={sc}")
        except OSError:
            print("  last_success=(unreadable)")
    else:
        print("  last_success=(none)")

    # 检查哨兵文件
    kill_present = KILL_FILE.exists()
    print(f"  kill_switch={'PRESENT' if kill_present else 'absent'}")

    return 0


def cmd_run() -> int:
    """前台运行守护进程（调试用）。"""
    # 清除旧的哨兵文件
    KILL_FILE.unlink(missing_ok=True)
    daemon = ESAEDaemon()
    daemon.run()
    return 0


def _is_pid_alive(pid: int) -> bool:
    """检查 PID 是否存活。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> int:
    """CLI 入口。"""
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 1

    command = sys.argv[1]
    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "run": cmd_run,
    }

    fn = commands.get(command)
    if fn is None:
        print(f"unknown command: {command}")
        print(f"usage: {sys.argv[0]} {{start|stop|status|run}}")
        return 1

    return fn()


if __name__ == "__main__":
    sys.exit(main())
