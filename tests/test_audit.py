"""Test: AuditLog — append-only JSONL audit (kernel/audit.py)

AAA (Arrange-Act-Assert) pattern.
"""

import json
import os
import tempfile
from pathlib import Path
import pytest
from kernel.audit import AuditLog, AuditError


class TestAuditLog:
    """Contract: write succeeds, read returns what was written."""

    def test_write_and_read_back(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            entry = audit.log("evolve", "ok", target="fsm", detail="mutate_1")
            assert entry["action"] == "evolve"
            assert entry["result"] == "ok"

            recent = audit.recent(5)
            assert len(recent) == 1
            assert recent[0]["action"] == "evolve"

    def test_recent_returns_last_n(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            for i in range(10):
                audit.log("evolve", "ok", target=str(i))
            recent = audit.recent(3)
            assert len(recent) == 3
            assert recent[-1]["target"] == "7"  # last 3: 7, 8, 9

    def test_recent_on_empty_log(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "empty.jsonl")
            assert audit.recent(10) == []

    def test_all_required_fields_present(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            entry = audit.log("test", "pass", target="x", detail="y")
            for key in ("timestamp", "action", "result", "target", "detail", "pid"):
                assert key in entry

    def test_append_only_preserves_previous(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            audit.log("first", "ok")
            audit.log("second", "ok")
            r = audit.recent(10)
            assert len(r) == 2
            # recent returns newest-first (insert(0) pattern)
            assert r[0]["action"] == "second"
            assert r[1]["action"] == "first"


class TestAuditLogIO:
    """Contract: write log creates directory if needed."""

    def test_write_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "subdir" / "audit.jsonl"
            audit = AuditLog(path=path)
            entry = audit.log("evolve", "ok")
            assert entry["action"] == "evolve"
            assert path.exists()

    def test_recent_on_corrupted_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "corrupt.jsonl"
            path.write_text("{bad json}\n{\"action\": \"good\"}\n", encoding="utf-8")
            audit = AuditLog(path=path)
            from kernel.audit import AuditError
            with pytest.raises(AuditError):
                audit.recent(5)
