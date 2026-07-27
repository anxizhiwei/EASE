"""KernelBridge — 进化循环 ↔ Phase 0 内核的评估桥接。

将 evolution_loop 的 Genome 参数映射到真实的 FSM + CircuitBreaker 行为：
  1. 用 genome.params 创建 CircuitBreaker 实例
  2. 模拟一系列「成功/失败」调用
  3. 评估熔断器的状态转换效率
  4. 返回 FitnessReport（overall, stability, health, failure_metric, efficiency）

参考:
  - evolution/genome.py (7 参数的 Genome)
  - evolution/fitness.py 的 FitnessReport
  - kernel/fsm.py 的 FSM
  - kernel/circuit.py 的 CircuitBreaker

Usage:
    from evolution.kernel_bridge import KernelEvaluator
    evaluator = KernelEvaluator()
    report = evaluator.evaluate(genome)
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Optional

# Flexible imports — works whether esae/ is on sys.path directly
# or as a subpackage under ~/.hermes/
try:
    from ..kernel.circuit import CircuitBreaker  # type: ignore[misc]
    from ..kernel.fsm import FSMState
    from .fitness import FitnessReport
    from .genome import Genome
    _PACKAGED = True
except ImportError:
    from kernel.circuit import CircuitBreaker  # type: ignore[import]
    from kernel.fsm import FSMState
    from evolution.fitness import FitnessReport
    from evolution.genome import Genome
    _PACKAGED = False


# ── Stress curve ─────────────────────────────────────────────────────────


def _stress_probability(tick: int, num_trials: int, *,
                        threshold: float,
                        relax_factor: float) -> float:
    """Generate failure probability at *tick*, modulated by *relax_factor*.

    The stress curve oscillates sinusoidally to simulate realistic
    burst-failure patterns.  *relax_factor* > 1.0 amplifies the peaks
    (harder stress), while *relax_factor* ~1.0 produces gentler waves.

    Returns:
        Probability in [0.05, 0.95].
    """
    phase = (tick / num_trials) * 2.0 * math.pi * 2.5  # 2.5 full cycles
    amplitude = 0.35 * relax_factor
    base = threshold * 0.65
    prob = base + amplitude * math.sin(phase)
    return max(0.05, min(0.95, prob))


# ── Single evaluation ────────────────────────────────────────────────────


def _single_eval(genome: Genome, num_trials: int, seed: int) -> FitnessReport:
    """Run one evaluation trial with a fixed *seed*."""
    rng = random.Random(seed)
    params = genome.params
    _interval, threshold, window, relax, _tighten, wait_duration, half_open_max = params
    # _interval 和 _tighten 在当前 Phase 保留供后续压力曲线调优使用

    cb = CircuitBreaker(
        window_size=max(3, int(round(window))),
        min_samples=max(3, int(round(window * 0.3))),
        failure_threshold=threshold,
        wait_duration_seconds=0.001,      # tiny → time check always passes;
        # tick-based tracking below enforces the actual wait_duration
        half_open_max_permits=max(1, int(round(half_open_max))),
        slow_call_threshold_seconds=999.0,   # disable slow-call detection
        slow_call_rate_threshold=1.0,
    )

    # ── Trial tracking ──────────────────────────────────────────
    success_calls = 0
    fail_calls = 0
    blocked_calls = 0
    prev_state = cb.state
    transitions = 0
    peaks_success = 0
    peaks_total = 0
    recovery_times: list[int] = []
    open_since: Optional[int] = None

    # Pre-compute stress values for peak-stress detection
    stress_values = [
        _stress_probability(t, num_trials, threshold=threshold,
                            relax_factor=relax)
        for t in range(num_trials)
    ]
    # Top-quartile threshold — any tick with stress above the 75th
    # percentile counts as "peak stress"
    peak_threshold = statistics.quantiles(stress_values, n=4)[-1]

    # translate wait_duration (seconds) to tick-based wait count
    wait_ticks = max(1, int(round(wait_duration * num_trials / 100.0)))

    for tick in range(num_trials):
        # ── OPEN → HALF_OPEN via tick-based timing ──────────────
        if open_since is not None and (tick - open_since) >= wait_ticks:
            # artificially advance wall-clock so dwell_time check passes
            cb._fsm._state_enter_time -= (wait_duration + 5.0)
            cb.is_call_permitted()        # triggers OPEN → HALF_OPEN

        # ── Real call flow: is_call_permitted → record_* ─────────
        if not cb.is_call_permitted():
            blocked_calls += 1
            if open_since is None:
                open_since = tick
            continue

        fail_prob = stress_values[tick]
        failed = rng.random() < fail_prob

        if failed:
            cb.record_failure(duration=0.1)
            fail_calls += 1
        else:
            cb.record_success(duration=0.05)
            success_calls += 1

        current_state = cb.state
        if current_state != prev_state:
            transitions += 1
            prev_state = current_state

        # Track recovery — how long until we exit OPEN
        if current_state != FSMState.OPEN and open_since is not None:
            recovery_times.append(tick - open_since)
            open_since = None
        elif current_state == FSMState.OPEN and open_since is None:
            open_since = tick

        # Peak-stress survival
        if fail_prob >= peak_threshold:
            peaks_total += 1
            if not failed:
                peaks_success += 1

    # ── Metrics ─────────────────────────────────────────────────
    total = max(num_trials, 1)

    # overall: basic success rate
    overall = success_calls / total

    # stability: inverse of transition frequency
    #   fewer transitions → more stable; cap the normalising divisor
    #   so the metric doesn't bottom out on short runs
    max_transitions = max(50, num_trials * 0.1)
    stability = 1.0 - min(1.0, transitions / max_transitions)

    # health: quality of the final state
    final_state = cb.state
    if final_state == FSMState.CLOSED:
        health = 1.0
    elif final_state == FSMState.HALF_OPEN:
        health = 0.5
    else:
        health = 0.0

    # failure_metric: survival rate during peak stress
    failure_metric = peaks_success / max(peaks_total, 1)

    # efficiency: average recovery speed (normalised)
    if recovery_times:
        avg_rec = sum(recovery_times) / len(recovery_times)
        efficiency = 1.0 - min(1.0, avg_rec / max(num_trials * 0.5, 1))
    else:
        # No recoveries needed → perfect efficiency if we never opened
        efficiency = 0.8 if transitions == 0 else 0.5

    # Hard stability gate (matches SimulatedEvaluator)
    passed = stability >= 0.5

    # Weighted composite (mirrors SimulatedEvaluator weights)
    composite = (
        stability * 0.40 +
        health * 0.30 +
        failure_metric * 0.20 +
        efficiency * 0.10
    )
    if not passed:
        composite = 0.0

    return FitnessReport(
        genome_id=genome.genome_id,
        overall=round(composite, 4),
        stability=round(stability, 4),
        health=round(health, 4),
        failure_metric=round(failure_metric, 4),
        efficiency=round(efficiency, 4),
        passed=passed,
    )


def _median_report(reports: list[FitnessReport]) -> FitnessReport:
    """Take the per-component median of multiple reports.

    Args:
        reports: List of FitnessReport instances (all for the same genome).

    Returns:
        A single FitnessReport with median-aggregated fields.
    """
    if not reports:
        return FitnessReport(genome_id="", overall=0.0, passed=False)

    def _median(key: str) -> float:
        vals = sorted(getattr(r, key) for r in reports)
        return vals[len(vals) // 2]

    return FitnessReport(
        genome_id=reports[0].genome_id,
        overall=round(_median("overall"), 4),
        stability=round(_median("stability"), 4),
        health=round(_median("health"), 4),
        failure_metric=round(_median("failure_metric"), 4),
        efficiency=round(_median("efficiency"), 4),
        passed=_median("passed") >= 0.5,
    )


# ── Public API ────────────────────────────────────────────────────────────


class KernelEvaluator:
    """Evaluate genomes using real FSM + CircuitBreaker instances.

    Replaces ``DaemonRunner.evaluate()`` with a direct in-process evaluation
    that avoids subprocess overhead.  Runs multiple independent trials and
    aggregates via median to produce stable, deterministic-like results.

    Args:
        num_trials: Number of simulated ``call() → record_*`` cycles per run.
        num_runs: Number of independent runs (median-aggregated).
        seed: Base random seed; each run uses ``seed + run_index``.
    """

    def __init__(self, num_trials: int = 100,
                 num_runs: int = 5,
                 seed: int = 42) -> None:
        self.num_trials = num_trials
        self.num_runs = num_runs
        self.seed = seed

    def evaluate(self, genome: Genome) -> FitnessReport:
        """Evaluate *genome* using real CircuitBreaker instances.

        Args:
            genome: The genome whose 7 params will be mapped to a
                CircuitBreaker configuration.

        Returns:
            A FitnessReport with median-aggregated metrics.
        """
        reports = [
            _single_eval(genome, self.num_trials, self.seed + i)
            for i in range(self.num_runs)
        ]
        return _median_report(reports)

    def __call__(self, genome: Genome) -> FitnessReport:
        """Convenience: call the evaluator directly."""
        return self.evaluate(genome)
