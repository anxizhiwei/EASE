#!/usr/bin/env python3
"""ESAE 安全基础设施 — kill switch + 审计日志

独立于 Hermes 运行，纯 stdlib。
安全三原则：
1. 任何操作前必须有审计记录
2. 任何时候 kill switch 信号可终止
3. 任何危险操作必须被拦截并记录
"""
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

ESAE_HOME = Path.home() / ".hermes" / "esae"
KILL_SWITCH = Path("/tmp/esae_stop")
AUDIT_LOG = ESAE_HOME / "logs" / "audit.jsonl"
SAFETY_LOG = ESAE_HOME / "logs" / "safety.jsonl"


def check_kill_switch() -> bool:
    """检查哨兵文件。存在 → 应停止。"""
    return KILL_SWITCH.exists()


def write_kill_switch(reason: str = "user_request") -> None:
    """写入哨兵文件以停止 ESAE。"""
    KILL_SWITCH.write_text(reason)
    log_safety("kill_switch_written", {"reason": reason})


def clear_kill_switch() -> None:
    """清除哨兵文件以允许 ESAE 启动。"""
    if KILL_SWITCH.exists():
        KILL_SWITCH.unlink()


def log_action(action: str, result: str, target: str = "",
               detail: str = "") -> None:
    """记录操作审计日志。"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "result": result,
        "target": target,
        "detail": detail,
        "pid": os.getpid(),
    }
    ESAE_HOME.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def log_safety(event: str, context: dict | None = None) -> None:
    """记录安全事件。"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "event": event,
        "context": context or {},
        "pid": os.getpid(),
    }
    ESAE_HOME.mkdir(parents=True, exist_ok=True)
    with open(SAFETY_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 信号处理 ───────────────────────────────────────

_running = True

def _handle_sigterm(signum, frame):
    global _running
    _running = False
    log_safety("sigterm_received", {"signal": signum})

signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


def should_continue() -> bool:
    """主循环应继续吗？"""
    if not _running:
        return False
    if check_kill_switch():
        log_safety("kill_switch_detected", {})
        return False
    return True


# ── 危险区域定义 ──────────────────────────────────

# 屏幕上的敏感区域（归一化坐标 0.0~1.0）
SENSITIVE_ZONES = [
    {"name": "screen_top_left",     "x": 0,  "y": 0,  "w": 0.05, "h": 0.05},
    {"name": "screen_bottom_left",  "x": 0,  "y": 0.95,"w": 0.1,  "h": 0.05},
    {"name": "taskbar",             "x": 0,  "y": 0.93,"w": 1.0,  "h": 0.07},
    {"name": "system_tray",         "x": 0.85,"y": 0,  "w": 0.15, "h": 0.05},
]

# 黑名单按键组合
BLACKLIST_KEYS = [
    "ctrl+alt+del", "win+r", "alt+f4", "super_l", "super_r",
    "ctrl+shift+esc", "alt+tab",
]


def check_coord(screen_w: int, screen_h: int, x: int, y: int) -> tuple[bool, str]:
    """检查坐标是否在敏感区域。"""
    nx, ny = x / screen_w, y / screen_h
    for zone in SENSITIVE_ZONES:
        if (zone["x"] <= nx <= zone["x"] + zone["w"] and
            zone["y"] <= ny <= zone["y"] + zone["h"]):
            return False, f"坐标({x},{y})在敏感区域: {zone['name']}"
    return True, "允许"


def check_keys(keys: str) -> tuple[bool, str]:
    """检查按键组合是否在黑名单。"""
    for bk in BLACKLIST_KEYS:
        if keys.lower() == bk:
            return False, f"按键黑名单: {bk}"
    return True, "允许"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        write_kill_switch("cli_stop")
        print("✅ Kill switch written. ESAE will stop on next cycle.")
    elif len(sys.argv) > 1 and sys.argv[1] == "start":
        clear_kill_switch()
        print("✅ Kill switch cleared. ESAE can start.")
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        print(f"Kill switch: {'⚠️ ACTIVE' if check_kill_switch() else '✅ clear'}")
        print(f"Audit log:   {AUDIT_LOG} ({AUDIT_LOG.stat().st_size//1024 if AUDIT_LOG.exists() else 0}KB)")
        print(f"Sessions:    running={_running}")
    else:
        print("用法: python3 esae_safety.py {start|stop|status}")
