"""Test: esae_safety.py — kill switch, audit log, coordinate/key safety checks.

AAA (Arrange-Act-Assert) pattern.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from esae_safety import (
    KILL_SWITCH,
    check_kill_switch, write_kill_switch, clear_kill_switch,
    log_action, log_safety, should_continue,
    check_coord, check_keys,
)


class TestKillSwitch:
    """Contract: kill switch file controls should_continue."""

    def setup_method(self):
        clear_kill_switch()

    def test_kill_switch_absent_by_default(self):
        assert check_kill_switch() is False

    def test_kill_switch_present_after_write(self):
        write_kill_switch("test")
        assert KILL_SWITCH.exists()
        assert check_kill_switch() is True
        clear_kill_switch()

    def test_clear_kill_switch_removes_file(self):
        write_kill_switch("test")
        clear_kill_switch()
        assert check_kill_switch() is False

    def test_should_continue_false_when_kill_switch(self):
        write_kill_switch("stop")
        assert should_continue() is False
        clear_kill_switch()

    def test_clear_is_idempotent(self):
        clear_kill_switch()
        clear_kill_switch()


class TestAuditLog:
    """Contract: log_action writes to the correct file."""

    def test_log_action_returns_dict(self):
        from esae_safety import AUDIT_LOG
        try:
            entry = log_action("test_action", "ok", target="system")
            assert isinstance(entry, dict)
            assert entry.get("action") == "test_action"
            assert entry.get("result") == "ok"
        finally:
            if AUDIT_LOG.exists():
                AUDIT_LOG.unlink()

    def test_log_action_has_required_fields(self):
        from esae_safety import AUDIT_LOG
        try:
            entry = log_action("evolve", "fail")
            for key in ("timestamp", "action", "result", "pid"):
                assert key in entry
        finally:
            if AUDIT_LOG.exists():
                AUDIT_LOG.unlink()


class TestSafetyLog:
    """Contract: log_safety creates safety event entries."""

    def test_log_safety_writes(self):
        from esae_safety import SAFETY_LOG
        try:
            log_safety("test_event", {"key": "value"})
            assert SAFETY_LOG.exists()
            content = SAFETY_LOG.read_text(encoding="utf-8")
            assert "test_event" in content
        finally:
            if SAFETY_LOG.exists():
                SAFETY_LOG.unlink()


class TestCoordinateCheck:
    """Contract: screen sensitive zones are detected."""

    def test_center_screen_is_safe(self):
        ok, _ = check_coord(1920, 1200, 960, 600)
        assert ok is True

    def test_top_left_is_blocked(self):
        ok, msg = check_coord(1920, 1200, 10, 10)
        assert ok is False
        assert "screen_top_left" in msg

    def test_bottom_left_is_blocked(self):
        ok, msg = check_coord(1920, 1200, 50, 1170)
        assert ok is False
        assert "screen_bottom_left" in msg

    def test_taskbar_is_blocked(self):
        ok, msg = check_coord(1920, 1200, 960, 1140)
        assert ok is False
        assert "taskbar" in msg

    def test_system_tray_is_blocked(self):
        ok, msg = check_coord(1920, 1200, 1800, 10)
        assert ok is False
        assert "system_tray" in msg


class TestKeyCheck:
    """Contract: dangerous key combinations are blocked."""

    def test_ctrl_alt_del_blocked(self):
        ok, _ = check_keys("ctrl+alt+del")
        assert ok is False

    def test_win_r_blocked(self):
        ok, _ = check_keys("win+r")
        assert ok is False

    def test_normal_keys_allowed(self):
        ok, _ = check_keys("ctrl+c")
        assert ok is True


class TestCLI:
    """Contract: CLI commands work correctly."""

    def test_cli_status(self):
        clear_kill_switch()
        from esae_safety import log_action
        # Just verify status via the module-level check
        assert check_kill_switch() is False

    def test_cli_stop(self):
        clear_kill_switch()
        from esae_safety import write_kill_switch as stop_fn
        stop_fn("cli_stop")
        assert KILL_SWITCH.exists()
        clear_kill_switch()

    def test_cli_start(self):
        write_kill_switch("old")
        from esae_safety import clear_kill_switch as start_fn
        start_fn()
        assert check_kill_switch() is False
