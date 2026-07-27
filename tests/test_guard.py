"""Test: SafetyGuard — sensitive zone detection + code scan (kernel/guard.py)

AAA (Arrange-Act-Assert) pattern.
"""

import tempfile
from pathlib import Path
import pytest
from kernel.audit import ESAEError
from kernel.guard import SafetyGuard, GuardError


class TestCoordinateCheck:
    """Contract: screen corners and system areas are blocked."""

    def test_center_screen_is_safe(self):
        guard = SafetyGuard()
        ok, msg = guard.check_coord(1920, 1200, 960, 600)
        assert ok is True

    def test_top_left_corner_is_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_coord(1920, 1200, 10, 10)
        assert ok is False
        assert "screen_top_left" in msg

    def test_bottom_left_is_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_coord(1920, 1200, 50, 1170)
        assert ok is False
        assert "screen_bottom_left" in msg

    def test_taskbar_zone_is_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_coord(1920, 1200, 960, 1140)
        assert ok is False
        assert "taskbar" in msg

    def test_system_tray_is_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_coord(1920, 1200, 1700, 10)
        assert ok is False
        assert "system_tray" in msg


class TestKeyCheck:
    """Contract: dangerous key combinations are blocked."""

    def test_ctrl_alt_del_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_keys("ctrl+alt+del")
        assert ok is False

    def test_win_r_blocked(self):
        guard = SafetyGuard()
        ok, msg = guard.check_keys("win+r")
        assert ok is False

    def test_normal_keys_allowed(self):
        guard = SafetyGuard()
        ok, msg = guard.check_keys("ctrl+c")
        assert ok is True

    def test_case_insensitive(self):
        guard = SafetyGuard()
        ok, _ = guard.check_keys("CTRL+ALT+DEL")
        assert ok is False


class TestCodeCheck:
    """Contract: dangerous code patterns are denied."""

    def test_exec_is_denied(self):
        guard = SafetyGuard()
        ok, msg = guard.check_code("exec('print(1)')")
        assert ok is False
        assert "exec" in msg

    def test_eval_is_denied(self):
        guard = SafetyGuard()
        ok, msg = guard.check_code("eval('1+1')")
        assert ok is False
        assert "eval" in msg

    def test_os_system_is_denied(self):
        guard = SafetyGuard()
        ok, msg = guard.check_code("os.system('ls')")
        assert ok is False
        assert "os.system" in msg

    def test_safe_code_passes(self):
        guard = SafetyGuard()
        ok, msg = guard.check_code("x = 1 + 1\nprint(x)")
        assert ok is True
        assert msg == ""

    def test_sensitive_path_is_denied(self):
        guard = SafetyGuard()
        ok, msg = guard.check_code("path = '/etc/passwd'")
        assert ok is False
        assert "/etc/" in msg


class TestMutationStaging:
    """Contract: mutations go through two-phase staging + approval."""

    def test_stage_valid_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("mutate_1", "old", "new")
            assert len(pid) > 0  # UUID returned

    def test_stage_dangerous_mutation_raises(self):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            with pytest.raises(GuardError, match="exec"):
                guard.stage_mutation("bad", "old", "exec('rm -rf /')")

    def test_approve_valid_proposal(self):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("mutate_1", "old", "print('hello')")
            ok, summary = guard.approve_mutation(pid)
            assert ok is True

    def test_approve_nonexistent_proposal(self):
        guard = SafetyGuard()
        ok, msg = guard.approve_mutation("nonexistent-uuid")
        assert ok is False

    def test_reject_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("mutate_1", "old", "new_code")
            ok = guard.reject_mutation(pid, reason="manual")
            assert ok is True

    def test_double_approve_fails(self):
        """Contract: already-approved proposal cannot be approved again."""
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("mutate_1", "old", "safe()")
            guard.approve_mutation(pid)
            ok, msg = guard.approve_mutation(pid)
            assert ok is False
            assert "pending" in msg


class TestParamCheck:
    """Contract: NaN, INF, out-of-bounds values are rejected."""

    def test_nan_rejected(self):
        guard = SafetyGuard()
        ok, msg = guard.check_param(float("nan"))
        assert ok is False

    def test_inf_rejected(self):
        guard = SafetyGuard()
        ok, msg = guard.check_param(float("inf"))
        assert ok is False

    def test_below_min_rejected(self):
        guard = SafetyGuard()
        ok, msg = guard.check_param(-1, min_val=0)
        assert ok is False

    def test_above_max_rejected(self):
        guard = SafetyGuard()
        ok, msg = guard.check_param(101, max_val=100)
        assert ok is False

    def test_valid_param_passes(self):
        guard = SafetyGuard()
        ok, msg = guard.check_param(50, min_val=0, max_val=100)
        assert ok is True


class TestPathCheck:
    """Contract: sensitive paths are detected."""

    def test_etc_path_is_unsafe(self):
        ok, msg = SafetyGuard.is_safe_path("/etc/passwd")
        assert ok is False

    def test_home_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            ok, msg = SafetyGuard.is_safe_path(td)
            assert ok is True


class TestUserDeny:
    """Contract: user-defined deny patterns extend but don't replace defaults."""

    def test_add_user_deny(self):
        guard = SafetyGuard()
        ok = guard.add_user_deny("dangerous_func")
        assert ok is True

    def test_user_deny_blocks_code(self):
        guard = SafetyGuard()
        guard.add_user_deny("dangerous_func")
        ok, msg = guard.check_code("dangerous_func()")
        assert ok is False

    def test_duplicate_user_deny_returns_false(self):
        guard = SafetyGuard()
        guard.add_user_deny("my_pattern")
        ok = guard.add_user_deny("my_pattern")
        assert ok is False
