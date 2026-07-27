"""Test: DaemonRunner — daemon_runner.py (evolution module)."""
import pytest
from evolution.genome import make_genome
from evolution.daemon_runner import DaemonRunner


class TestDaemonRunner:
    """Contract: DaemonRunner produces deterministic, discriminative scores."""

    def test_deterministic(self):
        """同一 genome 必须得到完全相同的结果。"""
        runner = DaemonRunner(timeout=10, num_cycles=50)
        g = make_genome()
        r1 = runner.evaluate(g)
        r2 = runner.evaluate(g)
        assert r1.overall == r2.overall
        assert r1.stability == r2.stability

    def test_good_vs_bad(self):
        """好 genome 的分数必须明显高于坏 genome。"""
        runner = DaemonRunner(timeout=10, num_cycles=50)
        good = make_genome()
        bad = make_genome(5.0, 0.1, 5.0, 1.1, 0.5, 60.0, 1.0)
        r1 = runner.evaluate(good)
        r2 = runner.evaluate(bad)
        assert r1.overall > r2.overall
        assert r1.overall > 0.5

    def test_fitness_in_range(self):
        """适应度必须在 0~1 范围内。"""
        runner = DaemonRunner(timeout=10, num_cycles=50)
        g = make_genome()
        r = runner.evaluate(g)
        assert 0.0 <= r.overall <= 1.0
        assert 0.0 <= r.stability <= 1.0

    def test_report_has_all_fields(self):
        runner = DaemonRunner(timeout=10, num_cycles=50)
        r = runner.evaluate(make_genome())
        for attr in ("overall", "stability", "health", "failure_metric", "efficiency", "passed"):
            assert hasattr(r, attr)

    def test_timeout_returns_zero(self):
        """超时必须返回 0 分，不能崩溃。"""
        runner = DaemonRunner(timeout=0.001, num_cycles=999999)
        r = runner.evaluate(make_genome())
        assert r.overall == 0.0
