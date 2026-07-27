"""Test: AuditLog — coverage bump for exception paths."""

import json
import os
import tempfile
from pathlib import Path
import pytest
from kernel.audit import AuditLog, AuditError


class TestAuditExceptionPaths:
    """Coverage for _write and recent exception paths."""

    def test_write_oserror_raises_audit_error(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            def bad_flock(*a, **kw):
                raise OSError("lock failed")
            import fcntl
            monkeypatch.setattr(fcntl, "flock", bad_flock)
            with pytest.raises(AuditError):
                audit.log("evolve", "ok")

    def test_write_value_error_raises_audit_error(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            import fcntl
            def bad_fcntl(*a, **kw):
                raise TypeError("bad argument type")
            monkeypatch.setattr(fcntl, "flock", bad_fcntl)
            with pytest.raises(AuditError):
                audit.log("evolve", "ok")
