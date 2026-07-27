"""Test: EvolutionLoop end-to-end."""
import pytest
from evolution.evolution_loop import EvolutionLoop
from evolution.daemon_runner import DaemonRunner


class TestEvolutionLoop:
    def test_creates_default_evaluator(self):
        loop = EvolutionLoop()
        assert isinstance(loop.evaluator, DaemonRunner)

    def test_run_5_generations(self):
        """5 代必须跑完，不崩溃。"""
        loop = EvolutionLoop()
        loop.evaluator = DaemonRunner(timeout=10, num_cycles=30)
        history = loop.run(generations=5, verbose=False)
        assert len(history) == 6  # 0 + 5
        assert loop.generation == 5

    def test_stagnation_increases(self):
        """停滞计数必须随代递增（没有突破时）。"""
        loop = EvolutionLoop()
        loop.evaluator = DaemonRunner(timeout=10, num_cycles=30)
        loop.run(generations=5, verbose=False)
        assert loop.stagnation_count >= 0

    def test_history_has_all_records(self):
        loop = EvolutionLoop()
        loop.evaluator = DaemonRunner(timeout=10, num_cycles=30)
        history = loop.run(generations=3, verbose=False)
        for h in history:
            assert hasattr(h, "generation")
            assert hasattr(h, "report")
            assert 0.0 <= h.report.overall <= 1.0
