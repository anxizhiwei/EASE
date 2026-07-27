"""Test: CircuitBreaker — sliding window fault detection (kernel/circuit.py)

AAA (Arrange-Act-Assert) pattern.
Behavior contract: test relationship invariance, not specific values.
"""

import time
import pytest
from kernel.fsm import FSMState
from kernel.circuit import CircuitBreaker, CircuitBreakerError


class TestParameterValidation:
    """Contract: invalid parameters raise ValueError."""

    def test_window_size_must_be_positive(self):
        with pytest.raises(ValueError, match="window_size"):
            CircuitBreaker(window_size=0)

    def test_min_samples_must_be_positive(self):
        with pytest.raises(ValueError, match="min_samples"):
            CircuitBreaker(min_samples=0)

    def test_min_samples_not_exceed_window(self):
        with pytest.raises(ValueError, match="min_samples"):
            CircuitBreaker(window_size=5, min_samples=10)

    def test_failure_threshold_must_be_positive(self):
        with pytest.raises(ValueError, match="failure_threshold"):
            CircuitBreaker(failure_threshold=0.0)

    def test_failure_threshold_max_one(self):
        cb = CircuitBreaker(failure_threshold=1.0)
        assert cb.state == FSMState.CLOSED


class TestCallPermitted:
    """Contract: is_call_permitted tracks state correctly."""

    def test_closed_permits_all_calls(self):
        cb = CircuitBreaker()
        assert cb.is_call_permitted() is True

    def test_open_rejects_calls(self):
        cb = CircuitBreaker(window_size=5, min_samples=2, failure_threshold=0.5)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == FSMState.OPEN
        assert cb.is_call_permitted() is False

    def test_half_open_permits_limited_calls(self):
        """Contract: HALF_OPEN allows exactly half_open_max_permits calls."""
        cb = CircuitBreaker(
            window_size=10, min_samples=2, failure_threshold=0.3,
            half_open_max_permits=3, wait_duration_seconds=0.01,
        )
        # Trigger OPEN
        for _ in range(4):
            cb.record_failure()
        assert cb.state == FSMState.OPEN

        # Wait for recovery window
        time.sleep(0.02)

        # Should auto-transition to HALF_OPEN and allow first call
        assert cb.is_call_permitted() is True
        assert cb.state == FSMState.HALF_OPEN

        # Remaining permits should be available
        assert cb.is_call_permitted() is True
        assert cb.is_call_permitted() is True

        # Exhausted permits → reject
        assert cb.is_call_permitted() is False


class TestFailureToOpen:
    """Contract: failure_rate >= threshold → OPEN state."""

    def test_sufficient_failures_trigger_open(self):
        cb = CircuitBreaker(window_size=5, min_samples=3, failure_threshold=0.5)
        # 3 failures out of 3 samples = 100% > 50%
        cb.record_failure()
        cb.record_failure()
        assert cb.state == FSMState.CLOSED  # below min_samples
        cb.record_failure()
        assert cb.state == FSMState.OPEN

    def test_below_threshold_stays_closed(self):
        cb = CircuitBreaker(window_size=10, min_samples=3, failure_threshold=0.5)
        cb.record_success()
        cb.record_failure()
        cb.record_success()
        # Failure rate = 1/3 ≈ 33% < 50%
        assert cb.state == FSMState.CLOSED


class TestSlowCallDetection:
    """Contract: slow call rate >= threshold → OPEN."""

    def test_slow_calls_trigger_open(self):
        cb = CircuitBreaker(
            window_size=5, min_samples=1, failure_threshold=0.8,
            slow_call_threshold_seconds=0.01, slow_call_rate_threshold=0.5,
        )
        # 1 call, 1 slow → 100% > 50% slow_rate
        cb.record_slow_call(duration=0.1)
        assert cb.state == FSMState.OPEN


class TestHalfOpenRecovery:
    """Contract: all permitted calls succeed in HALF_OPEN → back to CLOSED."""

    def test_all_success_in_half_open_recovers(self):
        cb = CircuitBreaker(
            window_size=10, min_samples=2, failure_threshold=0.3,
            half_open_max_permits=2, wait_duration_seconds=0.01,
        )
        for _ in range(4):
            cb.record_failure()
        assert cb.state == FSMState.OPEN

        time.sleep(0.02)
        cb.is_call_permitted()  # auto → HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == FSMState.CLOSED

    def test_failure_in_half_open_returns_to_open(self):
        cb = CircuitBreaker(
            window_size=10, min_samples=2, failure_threshold=0.3,
            half_open_max_permits=2, wait_duration_seconds=0.01,
        )
        for _ in range(4):
            cb.record_failure()
        assert cb.state == FSMState.OPEN

        time.sleep(0.02)
        cb.is_call_permitted()  # auto → HALF_OPEN

        cb.record_failure()  # failure in HALF_OPEN → back to OPEN
        assert cb.state == FSMState.OPEN


class TestMetrics:
    """Contract: metrics returns a consistent snapshot."""

    def test_metrics_structure(self):
        cb = CircuitBreaker()
        m = cb.metrics()
        for key in ("state", "window_size", "total_calls_in_window",
                     "failure_count", "failure_rate", "slow_count",
                     "slow_rate", "is_call_permitted"):
            assert key in m

    def test_metrics_reflects_state(self):
        cb = CircuitBreaker(window_size=5, min_samples=2, failure_threshold=0.5)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        m = cb.metrics()
        assert m["state"] == "open"
        assert m["failure_count"] >= 3
        assert m["is_call_permitted"] is False


class TestReset:
    """Contract: reset restores CLOSED with empty window."""

    def test_reset_clears_window(self):
        cb = CircuitBreaker(window_size=5, min_samples=2, failure_threshold=0.5)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == FSMState.OPEN
        cb.reset()
        assert cb.state == FSMState.CLOSED
        m = cb.metrics()
        assert m["total_calls_in_window"] == 0
        assert m["failure_count"] == 0
        assert cb.is_call_permitted() is True
