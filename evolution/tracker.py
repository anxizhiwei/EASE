"""Evolution Tracker — 进化过程日志与问题记录器。

记录每一代进化的详细信息，包括：
- 变异尝试（成功/失败/回退）
- 异常和警告
- 代际统计
- 问题追踪（供赫查看）

输出：~/.hermes/esae/results/evolution_log_{timestamp}.jsonl
"""

from __future__ import annotations
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .genome import Genome
from .fitness import FitnessReport


# ── 日志级别 ────────────────────────────────────────────────────

class LogLevel:
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ── 事件记录 ────────────────────────────────────────────────────

@dataclass
class EvolutionEvent:
    """一条进化事件记录。"""
    timestamp: str
    level: str           # INFO / WARN / ERROR / CRITICAL
    event: str           # 事件类型
    message: str         # 描述
    generation: int = 0
    genome_id: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "event": self.event,
            "message": self.message,
            "generation": self.generation,
            "genome_id": self.genome_id,
            "details": self.details,
        }


# ── 进化追踪器 ──────────────────────────────────────────────────

class EvolutionTracker:
    """进化过程追踪器。

    用法:
        tracker = EvolutionTracker()
        tracker.log_mutation(gen, genome, "crossover")
        tracker.log_accept(gen, genome, report)
        tracker.log_rollback(gen, genome, reason="stability=0.3")
        ...
        tracker.print_summary()
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or Path.home() / ".hermes" / "esae" / "results"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 当前会话
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.events: list[EvolutionEvent] = []
        self.problems: list[EvolutionEvent] = []  # 只记录 WARN+

        # 统计
        self.generation_count = 0
        self.accept_count = 0
        self.rollback_count = 0
        self.reject_count = 0
        self.special_count = 0
        self.errors = 0
        self.start_time = time.time()

    # ── 日志方法 ──────────────────────────────────────────────

    def _log(self, level: str, event: str, message: str,
             generation: int = 0, genome_id: str = "",
             details: dict | None = None) -> None:
        ev = EvolutionEvent(
            timestamp=datetime.now().isoformat(),
            level=level,
            event=event,
            message=message,
            generation=generation,
            genome_id=genome_id,
            details=details or {},
        )
        self.events.append(ev)
        if level in (LogLevel.WARN, LogLevel.ERROR, LogLevel.CRITICAL):
            self.problems.append(ev)

    def log_mutation(self, gen: int, genome: Genome, strategy: str) -> None:
        self._log(LogLevel.INFO, "mutation",
                  f"strategy={strategy}", gen, genome.genome_id,
                  {"strategy": strategy, "params": genome.params})

    def log_accept(self, gen: int, genome: Genome, report: FitnessReport) -> None:
        self.accept_count += 1
        self._log(LogLevel.INFO, "accept",
                  f"fitness={report.overall:.4f}", gen, genome.genome_id,
                  report.to_dict())

    def log_rollback(self, gen: int, genome: Genome,
                     reason: str, report: FitnessReport | None = None) -> None:
        self.rollback_count += 1
        details = {"reason": reason}
        if report:
            details["report"] = report.to_dict()
        self._log(LogLevel.WARN, "rollback",
                  f"rolled back: {reason}", gen, genome.genome_id, details)

    def log_reject(self, gen: int, genome: Genome,
                   reason: str, report: FitnessReport) -> None:
        self.reject_count += 1
        self._log(LogLevel.WARN, "reject",
                  f"rejected: {reason}", gen, genome.genome_id,
                  {"reason": reason, "report": report.to_dict()})

    def log_error(self, gen: int, genome: Genome,
                  error: str, exc_info: bool = False) -> None:
        self.errors += 1
        details = {"error": error}
        if exc_info:
            details["traceback"] = traceback.format_exc()
        self._log(LogLevel.ERROR, "error",
                  error, gen, genome.genome_id, details)

    def log_special(self, gen: int, genome: Genome) -> None:
        self.special_count += 1
        self._log(LogLevel.INFO, "special_mutation",
                  "special mutation triggered", gen, genome.genome_id)

    def log_info(self, event: str, message: str, gen: int = 0,
                 details: dict | None = None) -> None:
        self._log(LogLevel.INFO, event, message, gen, "", details)

    def log_warn(self, event: str, message: str, gen: int = 0,
                 details: dict | None = None) -> None:
        self._log(LogLevel.WARN, event, message, gen, "", details)

    def log_critical(self, event: str, message: str, gen: int = 0,
                     details: dict | None = None) -> None:
        self._log(LogLevel.CRITICAL, event, message, gen, "", details)

    # ── 代际 ──────────────────────────────────────────────────

    def next_generation(self) -> None:
        self.generation_count += 1

    # ── 保存和输出 ────────────────────────────────────────────

    def save(self) -> Path:
        """保存完整日志到 JSONL。"""
        path = self.log_dir / f"evolution_log_{self.session_id}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for ev in self.events:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")
        return path

    def print_problems(self) -> list[EvolutionEvent]:
        """打印所有问题（WARN+）。"""
        if not self.problems:
            print("  无问题记录 ✅")
            return []

        print(f"\n  ── 问题列表 ({len(self.problems)} 条) ──")
        for p in self.problems[-20:]:  # 最多最近 20 条
            icon = {"WARN": "⚠️", "ERROR": "❌", "CRITICAL": "🔴"}.get(p.level, "·")
            print(f"  {icon} [{p.level}] gen={p.generation} {p.message}")
        return self.problems

    def print_summary(self) -> str:
        """输出会话摘要。"""
        elapsed = time.time() - self.start_time
        lines = [
            "",
            "=" * 72,
            "  EASE Evolution Tracker — 会话摘要",
            "=" * 72,
            f"  会话:        {self.session_id}",
            f"  耗时:        {elapsed:.1f}s",
            f"  总代数:      {self.generation_count}",
            f"  接受:        {self.accept_count}",
            f"  回退:        {self.rollback_count}",
            f"  拒绝:        {self.reject_count}",
            f"  特殊变异:    {self.special_count}",
            f"  错误:        {self.errors}",
            f"  问题(WARN+): {len(self.problems)}",
        ]
        s = "\n".join(lines)
        print(s)
        return s

    @property
    def log_path(self) -> Path:
        return self.log_dir / f"evolution_log_{self.session_id}.jsonl"
