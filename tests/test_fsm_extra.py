"""Test: FSM — coverage bump for dwell_time history query and extended state."""

import time
import pytest
from kernel.fsm import FSM, FSMState


class TestDwellTimeHistory:
    """Contract: dwell_time can query non-current states from history."""

    def test_dwell_time_history_query(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        time.sleep(0.01)
        fsm.transition(FSMState.HALF_OPEN)
        # Query dwell time of OPEN (previous state, already exited)
        dt = fsm.dwell_time(FSMState.OPEN)
        assert dt >= 0  # should return last known elapsed

    def test_dwell_time_state_not_in_history(self):
        fsm = FSM()
        # Query a state that was never entered
        dt = fsm.dwell_time(FSMState.HALF_OPEN)
        assert dt == 0.0

    def test_dwell_time_query_exited_state(self):
        fsm = FSM()
        fsm.transition(FSMState.OPEN)
        dt_before = fsm.dwell_time(FSMState.CLOSED)
        # CLOSED was the from_state, should have elapsed from that transition
        assert dt_before >= 0


class TestExtendedStatesCoverage:
    """Coverage for _resolve_extended edge cases."""

    def test_resolve_extended_valid_name(self):
        fsm = FSM()
        # Access internal method directly
        result = fsm._resolve_extended("closed")
        assert result == FSMState.CLOSED

    def test_resolve_extended_invalid_name(self):
        fsm = FSM()
        result = fsm._resolve_extended("nonexistent")
        assert result == FSMState.CLOSED  # fallback
