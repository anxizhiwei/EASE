"""Genome — EASE 系统的基因组数据结构。

Genome = 一串带约束的参数，描述系统当前状态。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── 每个参数的元信息 ──────────────────────────────────────────────

@dataclass(frozen=True)
class ParamDef:
    """单个参数的定义：名字、范围、默认值。"""
    name: str
    min_val: float
    max_val: float
    default: float


# ── EASE 系统可进化参数表 ────────────────────────────────────────
# 对应 Phase 0 的 FSM + CircuitBreaker + Daemon 的可调参数

EASE_PARAMS: list[ParamDef] = [
    ParamDef("heartbeat_interval",    1.0,  30.0,  5.0),   # 心跳间隔(秒)
    ParamDef("failure_threshold",     0.1,   0.9,  0.5),   # 失败率熔断阈值
    ParamDef("window_size",           3.0,  50.0, 20.0),   # 滑动窗口大小
    ParamDef("relax_factor",          1.01,  2.0,  1.1),   # 放松系数
    ParamDef("tighten_factor",        0.1,   0.9,  0.5),   # 收紧系数
    ParamDef("wait_duration",         1.0,  60.0, 30.0),   # 熔断等待(秒)
    ParamDef("half_open_max_permits", 1.0,  10.0,  3.0),   # 试探许可数
]


def default_genome_values() -> list[float]:
    """返回所有参数的默认值列表。"""
    return [p.default for p in EASE_PARAMS]


def clamp_params(params: list[float]) -> list[float]:
    """将参数裁剪到合法范围内。"""
    return [
        max(p.min_val, min(p.max_val, params[i]))
        for i, p in enumerate(EASE_PARAMS)
    ]


# ── Genome ────────────────────────────────────────────────────────

@dataclass
class Genome:
    """一个基因组 = 系统的一组参数快照。

    Attributes:
        params:   参数值列表（有序，与 EASE_PARAMS 对应）
        fitness:  适应度（0~1，越高越好）
        stable:   是否通过稳定性检查
        generation: 所属代际
        parent_ids: 亲本 genome 的 ID（用于追踪）
    """
    params: list[float] = field(default_factory=default_genome_values)
    fitness: float = 0.0
    stable: bool = True
    generation: int = 0
    genome_id: str = ""
    parent_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.genome_id:
            import uuid
            self.genome_id = uuid.uuid4().hex[:12]

    def to_dict(self) -> dict:
        """序列化为 JSON 可序列化字典。"""
        return {
            "genome_id": self.genome_id,
            "generation": self.generation,
            "params": self.params,
            "fitness": self.fitness,
            "stable": self.stable,
            "parent_ids": self.parent_ids,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Genome:
        """从字典反序列化。"""
        return cls(
            params=data["params"],
            fitness=data.get("fitness", 0.0),
            stable=data.get("stable", True),
            generation=data.get("generation", 0),
            genome_id=data.get("genome_id", ""),
            parent_ids=data.get("parent_ids", []),
        )

    def param_names(self) -> list[str]:
        """返回参数名列表。"""
        return [p.name for p in EASE_PARAMS]

    def describe(self) -> str:
        """人类可读的描述。"""
        lines = [f"Genome #{self.genome_id[:8]}  (gen {self.generation})"]
        for i, p in enumerate(EASE_PARAMS):
            val = self.params[i]
            marker = "●" if val == p.default else "○"
            lines.append(f"  {marker} {p.name:25s} = {val:6.2f}  [{p.min_val:.0f}~{p.max_val:.0f}]")
        lines.append(f"  FITNESS: {self.fitness:.4f}  STABLE: {self.stable}")
        return "\n".join(lines)


# ── Fast helpers ─────────────────────────────────────────────────

def make_genome(*overrides: float, generation: int = 0) -> Genome:
    """快速创建 genome，可覆盖指定参数。"""
    vals = default_genome_values()
    for i, v in enumerate(overrides):
        if i < len(vals):
            vals[i] = v
    return Genome(params=clamp_params(vals), generation=generation)


def genome_distance(a: Genome, b: Genome) -> float:
    """计算两个 genome 的参数距离（归一化欧氏距离）。"""
    total = 0.0
    for i, p in enumerate(EASE_PARAMS):
        norm_range = p.max_val - p.min_val
        if norm_range > 0:
            diff = (a.params[i] - b.params[i]) / norm_range
            total += diff * diff
    return (total / len(EASE_PARAMS)) ** 0.5
