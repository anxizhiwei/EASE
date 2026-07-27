"""Adaptive Pressure — 自适应进化压力系统。

压力原则：
- 代数越高，门槛越严（不进则退）
- 停滞越久，压力越大（逼系统破局）
- 从"能活就行"逐渐过渡到"不只要活还要活得好"

压力维度：
1. 稳定性门槛:  0.60 → 0.75（随代数递增）
2. 效率权重:    10% → 25%（效率越来越重要）
3. 评估噪声:    0% → 15%（环境不确定性递增）
4. 停滞惩罚:    连续无进步 → 触发特殊变异概率暴增
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class PressureConfig:
    """压力配置。"""
    base_stability_threshold: float = 0.65    # 起始稳定性门槛（0.6→0.65）
    max_stability_threshold: float = 0.80     # 最高稳定性门槛（0.75→0.80）
    threshold_ramp_generations: int = 80      # 多少代达到最高门槛
    base_efficiency_weight: float = 0.10      # 起始效率权重
    max_efficiency_weight: float = 0.25       # 最高效率权重
    stagnation_special_prob: float = 0.08     # 停滞时特殊变异概率（降了）
    normal_special_prob: float = 0.02         # 正常特殊变异概率
    noise_scale: float = 0.15                 # 最大评估噪声


@dataclass
class PressureState:
    """当前压力状态。"""
    generation: int = 0
    stagnation_count: int = 0
    best_fitness: float = 0.0
    current_fitness: float = 0.0

    # 计算出的压力值
    stability_threshold: float = 0.60
    efficiency_weight: float = 0.10
    noise_level: float = 0.0
    special_probability: float = 0.02
    overall_pressure: float = 0.0  # 0~1


class AdaptivePressure:
    """自适应压力计算器。

    用法:
        pressure = AdaptivePressure()
        ps = pressure.update(generation, stagnation_count, best_fitness, current_fitness)
        # 用 ps.stability_threshold 做评测门槛
    """

    def __init__(self, config: PressureConfig | None = None):
        self.config = config or PressureConfig()
        self.state = PressureState()

    def update(self, generation: int, stagnation_count: int,
               best_fitness: float, current_fitness: float,
               special_triggered: bool = False) -> PressureState:
        """更新压力状态。

        Args:
            special_triggered: 本代是否触发了特殊变异（触发后重置概率）
        """
        self.state.generation = generation
        self.state.stagnation_count = stagnation_count
        self.state.best_fitness = best_fitness
        self.state.current_fitness = current_fitness

        # 代数进度 (0~1)
        gen_progress = min(1.0, generation / self.config.threshold_ramp_generations)

        # 1. 稳定性门槛: 从 0.65 线性升到 0.80（比以前更严）
        thr_range = self.config.max_stability_threshold - self.config.base_stability_threshold
        self.state.stability_threshold = round(
            self.config.base_stability_threshold + thr_range * gen_progress, 3
        )

        # 2. 效率权重: 从 10% 升到 25%
        eff_range = self.config.max_efficiency_weight - self.config.base_efficiency_weight
        self.state.efficiency_weight = round(
            self.config.base_efficiency_weight + eff_range * gen_progress, 3
        )

        # 3. 评估噪声: 代数越高噪声越大
        self.state.noise_level = round(self.config.noise_scale * gen_progress, 3)

        # 4. 特殊变异概率:
        #    - 本代触发了特殊变异 → 重置为基线（避免死循环）
        #    - 未触发 → 随停滞缓慢增加
        if special_triggered:
            self.state.special_probability = self.config.normal_special_prob
        else:
            stg = stagnation_count
            base = self.config.normal_special_prob
            if stg >= 30:
                self.state.special_probability = min(0.15, base + 0.13)
            elif stg >= 20:
                self.state.special_probability = min(0.10, base + 0.08)
            elif stg >= 10:
                self.state.special_probability = min(0.06, base + 0.04)
            else:
                self.state.special_probability = base

        # 5. 综合压力 (0~1)
        self.state.overall_pressure = round(
            gen_progress * 0.4 +
            min(1.0, stagnation_count / 30) * 0.3 +
            (1.0 - current_fitness) * 0.3,
            3
        )

        return self.state

    def describe(self) -> str:
        """当前压力状态描述。"""
        s = self.state
        bar_len = 20
        filled = int(s.overall_pressure * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        return (
            f"压力: [{bar}] {s.overall_pressure:.0%}  "
            f"门槛: {s.stability_threshold:.2f}  "
            f"噪声: {s.noise_level:.2f}  "
            f"停滞: {s.stagnation_count}代  "
            f"特殊概率: {s.special_probability:.0%}"
        )
