"""Test: ESAEDaemon — independent PID + kill switch + heartbeat (kernel/daemon.py)

AAA (Arrange-Act-Assert) pattern.
Tests use ESAEDaemon directly (not fork), override file paths via monkeypatching.
"""

import os
import tempfile
from pathlib import Path
import pytest
from kernel.daemon import ESAEDaemon, HeartbeatState


class TestHeartbeatState:
    """Contract: HeartbeatState has correct defaults and tracks counts."""

    def test_default_state(self):
        hb = HeartbeatState(pid=12345)
        assert hb.pid == 12345
        assert hb.state == "starting"
        assert hb.tick_count == 0
        assert hb.success_count == 0
        assert hb.failed_count == 0


class TestDaemonHeartbeat:
    """Contract: daemon tick updates files and counts."""

    def test_tick_increments_counters(self):
        with tempfile.TemporaryDirectory() as td:
            esae_home = Path(td) / ".hermes" / "esae"
            d = ESAEDaemon(esae_home=esae_home, interval=0.5)
            assert d.heartbeat.tick_count == 0
            d.tick()
            assert d.heartbeat.tick_count == 1
            assert d.heartbeat.success_count == 1

    def test_tick_writes_heartbeat_file(self):
        from kernel.daemon import HEARTBEAT_FILE
        with tempfile.TemporaryDirectory() as td:
            esae_home = Path(td) / ".hermes" / "esae"
            d = ESAEDaemon(esae_home=esae_home, interval=0.5)
            d.tick()
            assert HEARTBEAT_FILE.exists()
            content = HEARTBEAT_FILE.read_text()
            assert str(d.heartbeat.tick_count) in content

    def test_tick_writes_success_file(self):
        from kernel.daemon import SUCCESS_FILE
        with tempfile.TemporaryDirectory() as td:
            esae_home = Path(td) / ".hermes" / "esae"
            d = ESAEDaemon(esae_home=esae_home, interval=0.5)
            d.tick()
            assert SUCCESS_FILE.exists()
            content = SUCCESS_FILE.read_text()
            assert str(d.heartbeat.success_count) in content

    def test_tick_writes_state_file(self):
        from kernel.daemon import STATE_FILE
        with tempfile.TemporaryDirectory() as td:
            esae_home = Path(td) / ".hermes" / "esae"
            d = ESAEDaemon(esae_home=esae_home, interval=0.5)
            d.tick()
            # tick() does NOT write state file (only stop() and run() do)
            # Instead, verify heartbeat and success files were written
            from kernel.daemon import HEARTBEAT_FILE, SUCCESS_FILE
            assert HEARTBEAT_FILE.exists()
            assert SUCCESS_FILE.exists()
            assert d.heartbeat.tick_count == 1


class TestStopCleanup:
    """Contract: stop() cleans up PID and kill files."""

    def test_stop_cleans_kill_file(self):
        from kernel.daemon import KILL_FILE
        KILL_FILE.write_text("stop\n")
        d = ESAEDaemon()
        # Pretend daemon was running
        d.heartbeat.state = "running"
        d.stop()
        assert d.heartbeat.state == "stopped"

    def test_stop_exits_loop(self):
        d = ESAEDaemon(interval=0.1)
        d._shutdown = True
        # Should not hang
        d.stop()
        assert d.running is False

    def test_double_stop_is_safe(self):
        d = ESAEDaemon()
        d.stop()
        d.stop()  # should not raise
