"""Test: Tracing — Span, TraceStore, NoopSpan, instrument decorator (tracing/core.py)

AAA (Arrange-Act-Assert) pattern.
"""

import time
import tempfile
from pathlib import Path
import pytest
from tracing.core import (
    Span, TraceStore, NoopSpan, tracer, enable, disable,
    current_span, instrument, VALID_SPAN_TYPES,
)


class TestSpanCreation:
    """Contract: Span has required fields and validates span_type."""

    def test_default_span_type_is_tool(self):
        sp = Span("test")
        assert sp.type == "tool"

    def test_invalid_span_type_raises(self):
        with pytest.raises(ValueError, match="span_type"):
            Span("test", span_type="invalid_type")

    def test_all_valid_types_accepted(self):
        for st in VALID_SPAN_TYPES:
            sp = Span("test", span_type=st)
            assert sp.type == st

    def test_span_has_id(self):
        sp = Span("test")
        assert len(sp.span_id) == 16

    def test_span_default_status_is_ok(self):
        sp = Span("test")
        assert sp.status == "ok"


class TestSpanContextManager:
    """Contract: context manager sets current_span and records timing."""

    def test_context_manager_records_end_time(self):
        with Span("test") as sp:
            pass
        assert sp.end_time is not None
        assert sp.end_time >= sp.start_time

    def test_context_manager_sets_current_span(self):
        with Span("test") as sp:
            assert current_span() is sp
        assert current_span() is None

    def test_nested_spans_have_parent_child_relation(self):
        with Span("parent") as parent:
            with Span("child") as child:
                assert child.parent_id == parent.span_id
        assert len(parent.children) == 1
        assert parent.children[0] is child


class TestSpanSerialization:
    """Contract: to_dict returns JSON-serializable structure."""

    def test_to_dict_has_required_fields(self):
        with Span("test") as sp:
            pass
        d = sp.to_dict()
        for key in ("schemaVersion", "traceId", "spanId", "name",
                     "span_type", "startTime", "endTime", "status", "duration_ms"):
            assert key in d

    def test_to_dict_reflects_status(self):
        with Span("test") as sp:
            sp.set_status("error", "something broke")
        d = sp.to_dict()
        assert d["status"]["code"] == "ERROR"
        assert "something broke" in d["status"]["message"]


class TestTraceStore:
    """Contract: TraceStore persists spans to JSONL with dedup."""

    def test_emit_and_recent(self):
        with tempfile.TemporaryDirectory() as td:
            store = TraceStore(log_dir=Path(td))
            with Span("test", store=store) as sp:
                pass
            recent = store.recent(5)
            assert len(recent) >= 1
            assert recent[0]["name"] == "test"

    def test_dedup_by_sha1(self):
        with tempfile.TemporaryDirectory() as td:
            store = TraceStore(log_dir=Path(td))
            sp = Span("dedup_test")
            sp.end_time = time.time()
            store.emit(sp)
            store.emit(sp)  # identical span → should be deduped
            assert len(store.recent(10)) == 1


class TestNoopSpan:
    """Contract: NoopSpan is a no-op placeholder with no side effects."""

    def test_noop_span_enter_exit(self):
        sp = NoopSpan()
        with sp:
            pass
        # No error

    def test_noop_span_set_status(self):
        sp = NoopSpan()
        sp.set_status("error", "msg")  # No-op, no raise

    def test_noop_span_to_dict(self):
        sp = NoopSpan()
        assert sp.to_dict() == {}


class TestInstrumentDecorator:
    """Contract: instrument decorator wraps function with span."""

    def test_instrument_returns_result(self):
        @instrument("my_func", span_type="tool")
        def add(a, b):
            return a + b
        assert add(1, 2) == 3

    def test_instrument_captures_errors(self):
        @instrument("broken", span_type="tool")
        def broken():
            raise ValueError("boom")
        with pytest.raises(ValueError):
            broken()
