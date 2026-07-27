"""Mutation strategies — 变异策略。

三种策略：
1. CrossoverMutation  — 从两个亲本交叉重组（主要手段）
2. SnapshotRollback  — 变异前快照，不稳就回退（安全网）
3. SpecialMutation   — 极小概率大幅跳跃（破局）
"""

from __future__ import annotations
import copy
import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .genome import Genome, EASE_PARAMS, clamp_params


# ── CrossoverMutation ────────────────────────────────────────────

def crossover(parent_a: Genome, parent_b: Genome,
              inherit_bias: float = 0.7) -> Genome:
    """交叉重组。

    Args:
        parent_a: 当前稳定运行的 genome（高概率继承）
        parent_b: 候选父母池中的 genome（低概率尝试）
        inherit_bias: 继承 parent_a 的概率 (0~1)

    Returns:
        子代 genome
    """
    child_params = []
    for i in range(len(EASE_PARAMS)):
        if random.random() < inherit_bias:
            child_params.append(parent_a.params[i])
        else:
            child_params.append(parent_b.params[i])

    child = Genome(
        params=clamp_params(child_params),
        generation=max(parent_a.generation, parent_b.generation) + 1,
        parent_ids=[parent_a.genome_id, parent_b.genome_id],
    )
    return child


# ── SpecialMutation ──────────────────────────────────────────────

def special_mutate(genome: Genome, probability: float = 0.02) -> Genome:
    """特殊变异：极小概率对单个参数做大幅跳跃。

    跳跃幅度：砍半(×0.5) 或 翻倍(×2.0)
    """
    new_params = list(genome.params)
    jumped = False
    for i in range(len(new_params)):
        if random.random() < probability:
            factor = random.choice([0.5, 2.0])
            new_params[i] = new_params[i] * factor
            jumped = True

    if not jumped:
        # 保证至少有一个参数被特殊变异
        i = random.randrange(len(new_params))
        factor = random.choice([0.5, 2.0])
        new_params[i] = new_params[i] * factor

    child = Genome(
        params=clamp_params(new_params),
        generation=genome.generation + 1,
        parent_ids=[genome.genome_id],
    )
    return child


# ── MutationSelector — 策略选择器 ────────────────────────────────

class MutationSelector:
    """根据当前状态自动选择变异策略。"""

    def __init__(self, special_prob: float = 0.02):
        self.special_prob = special_prob

    def select(self, genome: Genome, parent_pool: list[Genome],
               stagnation_count: int = 0) -> str:
        """选择变异策略。

        策略完全由 self.special_prob 控制，
        不再使用硬编码的停滞阈值（交给 pressure 系统管理）。
        """
        if random.random() < self.special_prob:
            return "special"

        # 默认：交叉重组
        return "crossover"

    def mutate(self, genome: Genome, parent_pool: list[Genome],
               stagnation_count: int = 0) -> Genome:
        """执行选中的变异策略。"""
        strategy = self.select(genome, parent_pool, stagnation_count)

        if strategy == "special":
            return special_mutate(genome)

        # crossover: 从父母池中选一个搭档
        if parent_pool:
            partner = random.choice(parent_pool)
        else:
            # 父母池为空 → 用默认 genome 做基准
            from .genome import default_genome_values
            partner = Genome(params=default_genome_values())

        child = crossover(genome, partner)

        # 微概率在交叉基础上加特殊变异
        if random.random() < 0.01:
            child = special_mutate(child, probability=0.5)

        return child


# ── SnapshotRollback — 快照回退安全网 ───────────────────────────

class SnapshotStore:
    """快照存储：变异前拍照，不稳回退。

    存储位置：~/.hermes/esae/snapshots/
    格式：JSONL，每条是一个完整的 genome 快照。
    """

    def __init__(self, snap_dir: Optional[Path] = None):
        self.snap_dir = snap_dir or Path.home() / ".hermes" / "esae" / "snapshots"
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        self._current_snapshot: Optional[Genome] = None

    def snapshot(self, genome: Genome) -> str:
        """拍照：保存当前 genome 并返回快照 ID。"""
        snap_id = f"snap_{int(time.time())}_{genome.genome_id[:8]}"
        path = self.snap_dir / f"{snap_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(genome.to_dict(), f, ensure_ascii=False)
        self._current_snapshot = genome
        return snap_id

    def restore(self, snap_id: Optional[str] = None) -> Optional[Genome]:
        """回退到指定快照，或最新的快照。"""
        if snap_id:
            path = self.snap_dir / f"{snap_id}.json"
        elif self._current_snapshot:
            return self._current_snapshot
        else:
            # 没有快照 → 找最新的
            files = sorted(self.snap_dir.glob("snap_*.json"))
            if not files:
                return None
            path = files[-1]

        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Genome.from_dict(data)

    def clean_old(self, keep_last: int = 50) -> int:
        """清理旧快照，保留最近 N 个。"""
        files = sorted(self.snap_dir.glob("snap_*.json"))
        to_remove = files[:-keep_last] if len(files) > keep_last else []
        for f in to_remove:
            f.unlink(missing_ok=True)
        return len(to_remove)
