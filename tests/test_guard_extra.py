"""Test: Guard — coverage bump for exception paths."""

import json
import os
import tempfile
from pathlib import Path
import pytest
from kernel.guard import SafetyGuard, GuardError


class TestGuardExceptionPaths:
    """Coverage for _save_proposal and stage_mutation OSError."""

    def test_stage_mutation_oserror_raises(self, monkeypatch):
        def bad_write(*a, **kw):
            raise OSError("disk full")
        monkeypatch.setattr("builtins.open", bad_write)
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            with pytest.raises(GuardError, match="写入提案文件失败"):
                guard.stage_mutation("m1", "old", "safe")

    def test_approve_mutation_json_decode_error(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("m1", "old", "safe()")
            # Corrupt the proposal file
            prop_path = guard.pending_dir / f"{pid}.json"
            prop_path.write_text("{corrupted json", encoding="utf-8")
            ok, msg = guard.approve_mutation(pid)
            assert ok is False
            assert "读取提案失败" in msg or "JSON" in msg

    def test_approve_mutation_file_not_found(self):
        guard = SafetyGuard()
        ok, msg = guard.approve_mutation("nonexistent")
        assert ok is False
        assert "不存在" in msg

    def test_approve_mutation_secondary_scan_rejects(self):
        """Contract: if code changed between stage and approve, re-check."""
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            # Stage safe code, then manually modify the file to contain dangerous code
            pid = guard.stage_mutation("m1", "old", "safe()")
            prop_path = guard.pending_dir / f"{pid}.json"
            proposal = json.loads(prop_path.read_text(encoding="utf-8"))
            proposal["new_code"] = "exec('dangerous')"
            prop_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
            ok, msg = guard.approve_mutation(pid)
            assert ok is False

    def test_reject_mutation_nonexistent(self):
        guard = SafetyGuard()
        ok = guard.reject_mutation("nonexistent", reason="test")
        assert ok is False

    def test_reject_mutation_corrupted_file(self):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("m1", "old", "safe()")
            prop_path = guard.pending_dir / f"{pid}.json"
            prop_path.write_text("{corrupt", encoding="utf-8")
            ok = guard.reject_mutation(pid)
            assert ok is False

    def test_save_proposal_oserror(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            guard = SafetyGuard(pending_dir=Path(td))
            pid = guard.stage_mutation("m1", "old", "safe()")
            def bad_open(*a, **kw):
                raise OSError("permission denied")
            monkeypatch.setattr("builtins.open", bad_open)
            with pytest.raises(GuardError):
                guard._save_proposal(Path(td) / "test.json", {"status": "pending"})

    def test_is_safe_path_realpath(self):
        """Contract: is_safe_path resolves symlinks before checking."""
        ok, msg = SafetyGuard.is_safe_path("/tmp/safe_path_test")
        assert ok is True
