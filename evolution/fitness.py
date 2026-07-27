"""Fitness evaluation — 评测体系。

稳定性优先原则：
- 稳定性占 40%：心跳方差、失败率
- 健康度占 30%：OPEN/HALF_OPEN 状态占比
- 失败率占 20%：滑动窗口内的失败比例
- 效率占 10%：恢复速度

硬门槛：稳定性 < 0.5 → 适应度 = 0.0（直接拒绝）
"""

from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from typing import Optional

from .genome import Genome


# ── 评测指标 ─────────────────────────────────────────────────────

@dataclass
class FitnessReport:
    """一次评测的完整报告。"""
    genome_id: str
    overall: float = 0.0       # 综合适应度 0~1
    stability: float = 0.0     # 稳定性指标 0~1
    health: float = 0.0        # 健康度指标 0~1
    failure_metric: float = 0.0 # 失败指标 0~1（越高越好）
    efficiency: float = 0.0    # 效率指标 0~1
    passed: bool = False       # 是否通过稳定性硬门槛

    def to_dict(self) -> dict:
        return {
            "genome_id": self.genome_id,
            "overall": self.overall,
            "stability": self.stability,
            "health": self.health,
            "failure_metric": self.failure_metric,
            "efficiency": self.efficiency,
            "passed": self.passed,
        }


# ── 模拟评估器 ───────────────────────────────────────────────────
# Phase 1 先用数学模型模拟系统行为来评估 genome
# Phase 2 换成在真实 EASE 进程中跑一轮

class SimulatedEvaluator:
    """模拟评估器。

    用数学模型模拟 Phase 0 各模块在给定 genome 参数下的表现。
    不是真实跑系统，而是用公式近似——这样快，能快速迭代。
    """

    def __init__(self, noise: float = 0.0):
        self.noise = noise  # 模拟噪声

    def evaluate(self, genome: Genome) -> FitnessReport:
        """对 genome 做适应度评估。"""
        params = genome.params
        (
            interval, threshold, window,
            relax, tighten, wait_duration, half_open_max,
        ) = params

        # ── 1. 稳定性 (40%) ──────────────────────────────────
        # 基于心跳间隔、窗口大小、放松/收紧系数
        # 放松系数越接近 1.0，越稳定（变化慢）
        # 收紧系数越接近 0.5，越稳定（不极端）
        stability_interval = 1.0 - min(1.0, abs(interval - 5.0) / 25.0)
        stability_relax = 1.0 - min(1.0, abs(relax - 1.05) / 0.95)
        stability_tighten = 1.0 - min(1.0, abs(tighten - 0.5) / 0.4)
        stability_window = min(1.0, window / 30.0)

        stability = (
            stability_interval * 0.30 +
            stability_relax * 0.25 +
            stability_tighten * 0.25 +
            stability_window * 0.20
        )
        stability = max(0.0, min(1.0, stability + random.gauss(0, self.noise)))

        # ── 2. 健康度 (30%) ──────────────────────────────────
        # 模拟系统处于 OPEN/HALF_OPEN 的比例
        # threshold 越高，越不容易进入 OPEN（更健康）
        # wait_duration 越短，恢复越快
        health_base = threshold  # 阈值越高越健康
        health_recovery = 1.0 - min(1.0, wait_duration / 60.0)
        health = (health_base * 0.6 + health_recovery * 0.4)
        health = max(0.0, min(1.0, health + random.gauss(0, self.noise)))

        # ── 3. 失败指标 (20%) ────────────────────────────────
        # 窗口越大，失败率统计越准确
        # threshold 越高，容忍失败的能力越强
        failure_base = 1.0 - (1.0 - threshold) * 0.5  # threshold=0.9 → 0.95
        failure_window_bonus = min(0.2, window / 100.0)
        failure_metric = min(1.0, failure_base + failure_window_bonus)
        failure_metric = max(0.0, min(1.0, failure_metric + random.gauss(0, self.noise)))

        # ── 4. 效率 (10%) ────────────────────────────────────
        # 间隔越小，响应越快
        # wait_duration 越短，恢复越快
        # half_open_max 越大，试探越多
        speed_interval = 1.0 - min(1.0, (interval - 1.0) / 29.0)
        speed_wait = 1.0 - min(1.0, wait_duration / 60.0)
        speed_probes = min(1.0, half_open_max / 5.0)
        efficiency = (speed_interval * 0.4 + speed_wait * 0.4 + speed_probes * 0.2)
        efficiency = max(0.0, min(1.0, efficiency + random.gauss(0, self.noise * 0.5)))

        # ── 综合 ─────────────────────────────────────────────
        passed = stability >= 0.5  # 硬门槛
        overall = (
            stability * 0.40 +
            health * 0.30 +
            failure_metric * 0.20 +
            efficiency * 0.10
        )
        if not passed:
            overall = 0.0

        return FitnessReport(
            genome_id=genome.genome_id,
            overall=round(overall, 4),
            stability=round(stability, 4),
            health=round(health, 4),
            failure_metric=round(failure_metric, 4),
            efficiency=round(efficiency, 4),
            passed=passed,
        )


# ── 评测验证函数 ─────────────────────────────────────────────────

def evaluate_stability(genome: Genome,
                       evaluator: Optional[SimulatedEvaluator] = None) -> float:
    """快速稳定性检查（用于 SnapshotRollback 决策）。"""
    if evaluator is None:
        evaluator = SimulatedEvaluator(noise=0.03)
    report = evaluator.evaluate(genome)
    return report.stability


def evaluate_fitness(genome: Genome,
                     evaluator: Optional[SimulatedEvaluator] = None) -> FitnessReport:
    """完整适应度评估。"""
    if evaluator is None:
        evaluator = SimulatedEvaluator()
    return evaluator.evaluate(genome)
