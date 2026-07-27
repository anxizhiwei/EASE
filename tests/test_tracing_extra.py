"""Test: Tracing — coverage bump for edge cases."""

import tempfile
from pathlib import Path
import pytest
from tracing.core import (
    Span, TraceStore, NoopSpan, tracer, enable, disable,
    instrument, current_span,
)


class TestTracingEdgeCases:
    """Coverage for edge-case lines."""

    def test_disable_makes_spans_noop(self):
        enable()
        disable()
        with Span("should_not_record") as sp:
            pass
        assert current_span() is None
        enable()

    def test_tracestore_emit_disabled(self):
        disable()
        with tempfile.TemporaryDirectory() as td:
            store = TraceStore(log_dir=Path(td))
            with Span("test", store=store) as sp:
                pass
            store.emit(sp)  # disabled → no-op
            assert store.recent(10) == []
        enable()

    def test_tracestore_io_error_does_not_crash(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            store = TraceStore(log_dir=Path(td))
            def bad_open(*a, **kw):
                raise OSError("permission denied")
            monkeypatch.setattr("builtins.open", bad_open)
            with Span("test", store=store) as sp:
                pass
            # emit should not crash
            store.emit(sp)

    def test_tracestore_recent_empty(self):
        with tempfile.TemporaryDirectory() as td:
            store = TraceStore(log_dir=Path(td))
            assert store.recent(10) == []

    def test_tracestore_recent_corrupted_lines(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            from datetime import date
            today = date.today().isoformat()
            log_path = Path(td) / f"spans-{today}.jsonl"
            log_path.write_text(
                '{"schemaVersion":"v1","name":"good"}\n'
                '{corrupted\n',
                encoding="utf-8",
            )
            store = TraceStore(log_dir=Path(td))
            recent = store.recent(10)
            # Valid line parsed, corrupted skipped
            assert len(recent) == 1
            assert recent[0]["name"] == "good"

    def test_instrument_disabled_noop(self):
        disable()
        @instrument("test", span_type="tool")
        def add(a, b):
            return a + b
        assert add(1, 2) == 3
        enable()

    def test_span_trace_id_root(self):
        with Span("root") as sp:
            tid = sp._trace_id()
            assert tid.startswith("trace-")
            assert sp.span_id in tid

    def test_span_set_status_with_error(self):
        with Span("test") as sp:
            sp.set_status("error", "something went wrong")
        assert sp.status == "error"
        assert sp.error == "something went wrong"

    def test_span_no_end_time(self):
        sp = Span("test")
        d = sp.to_dict()
        assert d["endTime"] is None
        assert d["duration_ms"] is None

    def test_noop_span_no_children(self):
        sp = NoopSpan()
        assert sp.children == []
