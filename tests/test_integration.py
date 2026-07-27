"""Integration test: EASE Phase 0 — all modules working together.

Tests the "combine" aspect: FSM + CircuitBreaker + Audit + Guard.
"""

import json
import tempfile
from pathlib import Path
import pytest
from kernel.fsm import FSM, FSMState
from kernel.circuit import CircuitBreaker
from kernel.audit import AuditLog
from kernel.guard import SafetyGuard


class TestFSMAndCircuitBreaker:
    """Contract: CircuitBreaker wraps FSM, state changes are consistent."""

    def test_circuit_breaker_state_matches_fsm(self):
        cb = CircuitBreaker(window_size=5, min_samples=2, failure_threshold=0.5)
        assert cb.state == FSMState.CLOSED
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == FSMState.OPEN
        # CircuitBreaker.state delegates to FSM.state
        assert cb._fsm.state == FSMState.OPEN


class TestAuditAndGuard:
    """Contract: Guard operations are auditable (write then read)."""

    def test_guard_action_can_be_audited(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            guard = SafetyGuard(pending_dir=Path(td))

            # Perform guard action
            ok, msg = guard.check_coord(1920, 1200, 960, 600)
            audit.log("coord_check", "pass" if ok else "block",
                      target=f"960,600", detail=msg)

            # Read audit
            recent = audit.recent(5)
            assert len(recent) == 1
            assert recent[0]["action"] == "coord_check"
            assert recent[0]["result"] == "pass"


class TestCircuitBreakerAndAudit:
    """Contract: CircuitBreaker state transitions can be audited."""

    def test_circuit_transition_audit_trail(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            cb = CircuitBreaker(window_size=5, min_samples=2, failure_threshold=0.5)

            # Cause OPEN
            for _ in range(3):
                cb.record_failure()
                audit.log("circuit", "record_failure",
                          target=cb.state.value,
                          detail=f"failure_rate={cb.metrics()['failure_rate']:.2f}")

            # Verify audit trail
            recent = audit.recent(10)
            failure_events = [e for e in recent if e["action"] == "circuit"]
            assert len(failure_events) >= 3
            # Last event should be in OPEN state
            assert any(e["target"] == "open" for e in failure_events)


class TestFullPhase0Pipeline:
    """Contract: FSM → Circuit → Guard → Audit pipeline works end-to-end."""

    def test_evolve_cycle_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            audit = AuditLog(path=Path(td) / "audit.jsonl")
            guard = SafetyGuard(pending_dir=Path(td))
            cb = CircuitBreaker(
                window_size=10, min_samples=3, failure_threshold=0.5,
            )

            # 1. Start in CLOSED
            assert cb.state == FSMState.CLOSED
            audit.log("evolve", "start", target="closed")

            # 2. Simulate failures → OPEN
            for i in range(5):
                cb.record_failure(duration=0.1)
            assert cb.state == FSMState.OPEN
            audit.log("evolve", "circuit_open", target="open",
                      detail=str(cb.metrics()))

            # 3. Safety check before action
            ok, _ = guard.check_param(0.5, min_val=0, max_val=1.0)
            assert ok is True
            audit.log("safety", "param_check_passed", target="threshold=0.5")

            # 4. Verify full audit
            recent = audit.recent(10)
            assert len(recent) >= 3
            actions = [e["action"] for e in recent]
            assert "evolve" in actions
            assert "safety" in actions
