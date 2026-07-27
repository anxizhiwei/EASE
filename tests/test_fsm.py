"""Test: FSM — 3-state finite state machine (kernel/fsm.py)

AAA (Arrange-Act-Assert) pattern.
Behavior contract: test relationship invariance, not specific values.
"""

import time
import pytest
from kernel.fsm import FSM, FSMState, FSMError


# ── State transitions ──────────────────────────────────────────────

class TestStateTransitions:
    """Contract: only legal transitions are allowed."""

    def test_initial_state_is_closed(self):
        fsm = FSM()
        assert fsm.state == FSMState.CLOSED

    def test_closed_to_open_is_legal(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        assert fsm.state == FSMState.OPEN

    def test_closed_to_half_open_is_illegal(self):
        fsm = FSM()
        with pytest.raises(FSMError):
            fsm.transition(FSMState.HALF_OPEN)

    def test_open_to_half_open_is_legal(self):
        fsm = FSM(FSMState.OPEN)
        fsm.transition(FSMState.HALF_OPEN)
        assert fsm.state == FSMState.HALF_OPEN

    def test_open_to_closed_is_illegal(self):
        fsm = FSM(FSMState.OPEN)
        with pytest.raises(FSMError):
            fsm.transition(FSMState.CLOSED)

    def test_half_open_to_closed_is_legal(self):
        fsm = FSM(FSMState.HALF_OPEN)
        fsm.transition(FSMState.CLOSED)
        assert fsm.state == FSMState.CLOSED

    def test_half_open_to_open_is_legal(self):
        fsm = FSM(FSMState.HALF_OPEN)
        fsm.transition(FSMState.OPEN)
        assert fsm.state == FSMState.OPEN

    def test_full_cycle_closed_open_half_open_closed(self):
        """Contract: full lifecycle should return to CLOSED."""
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        fsm.transition(FSMState.HALF_OPEN)
        fsm.transition(FSMState.CLOSED)
        assert fsm.state == FSMState.CLOSED


# ── History ────────────────────────────────────────────────────────

class TestHistory:
    """Contract: each transition produces an event; history is append-only."""

    def test_transition_records_event(self):
        fsm = FSM()
        event = fsm.transition(FSMState.OPEN)
        assert event["from_state"] == "closed"
        assert event["to_state"] == "open"
        assert event["elapsed_s"] >= 0

    def test_history_length_equals_transition_count(self):
        fsm = FSM()
        assert len(fsm.history()) == 0
        fsm.transition(FSMState.OPEN)
        assert len(fsm.history()) == 1
        fsm.transition(FSMState.HALF_OPEN)
        assert len(fsm.history()) == 2

    def test_history_is_immutable_copy(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        hist = fsm.history()
        hist.clear()
        assert len(fsm.history()) == 1  # original unaffected


# ── Listeners ──────────────────────────────────────────────────────

class TestListeners:
    """Contract: all registered listeners fire on transition."""

    def test_listener_receives_transition_event(self):
        fsm = FSM()
        events = []
        fsm.on_transition(lambda old, new, ev: events.append((old, new, ev)))
        fsm.transition(FSMState.OPEN)
        assert len(events) == 1
        assert events[0][0] == FSMState.CLOSED
        assert events[0][1] == FSMState.OPEN

    def test_multiple_listeners_all_fire(self):
        fsm = FSM()
        counter = [0, 0]
        fsm.on_transition(lambda *a: counter.__setitem__(0, counter[0] + 1))
        fsm.on_transition(lambda *a: counter.__setitem__(1, counter[1] + 1))
        fsm.transition(FSMState.OPEN)
        assert counter[0] == 1
        assert counter[1] == 1

    def test_listener_exception_does_not_break_state_machine(self):
        """Contract: broken listener must not prevent transitions."""
        fsm = FSM()
        def broken(*_):
            raise RuntimeError("boom")
        fsm.on_transition(broken)
        event = fsm.transition(FSMState.OPEN)  # should not raise
        assert fsm.state == FSMState.OPEN
        assert event["to_state"] == "open"


# ── Dwell time ─────────────────────────────────────────────────────

class TestDwellTime:
    """Contract: dwell_time increases monotonically while in state."""

    def test_dwell_time_increases_over_time(self):
        fsm = FSM()
        t1 = fsm.dwell_time()
        time.sleep(0.01)
        t2 = fsm.dwell_time()
        assert t2 > t1

    def test_dwell_time_resets_after_transition(self):
        fsm = FSM()
        time.sleep(0.02)
        before = fsm.dwell_time()
        fsm.transition(FSMState.OPEN)
        after = fsm.dwell_time()
        assert after < before  # reset to near-zero


# ── Allowed transitions & reset ────────────────────────────────────

class TestAllowedTransitions:
    """Contract: allowed_transitions returns the legal targets."""

    def test_closed_allows_only_open(self):
        fsm = FSM()
        assert fsm.allowed_transitions() == [FSMState.OPEN]

    def test_open_allows_only_half_open(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        assert fsm.allowed_transitions() == [FSMState.HALF_OPEN]

    def test_half_open_allows_closed_and_open(self):
        fsm = FSM(FSMState.HALF_OPEN)
        assert set(fsm.allowed_transitions()) == {FSMState.CLOSED, FSMState.OPEN}

    def test_reset_clears_history_and_returns_to_closed(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        fsm.transition(FSMState.HALF_OPEN)
        fsm.reset()
        assert fsm.state == FSMState.CLOSED
        assert len(fsm.history()) == 0


# ── 5-state extension (Phase 2) ────────────────────────────────────

class TestExtendedStates:
    """Contract: register_state does not break basic transitions."""

    def test_register_state_does_not_affect_core(self):
        fsm = FSM()
        fsm.register_state("CALM", "calm")
        fsm.transition(FSMState.OPEN)
        assert fsm.state == FSMState.OPEN

    def test_register_state_with_targets(self):
        fsm = FSM()
        fsm.register_state("CALM", "calm", ["closed"])
        # Core transitions still work
        fsm.transition(FSMState.OPEN)
        assert fsm.state == FSMState.OPEN
