"""Evolution loop — 进化循环主流程 + ASCII 可视化。

每个循环：
1. 检查是否触发变异（每 N 代 / 时间触发）
2. 快照当前 genome
3. 选策略 + 变异
4. 评估适应度
5. 决策（接受/拒绝/回退）
6. 记录到代际历史
7. 输出可视化证据
"""

from __future__ import annotations
import json
import math
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .genome import Genome, default_genome_values, make_genome
from .mutation import MutationSelector, SnapshotStore
from .fitness import FitnessReport
from .daemon_runner import DaemonRunner
from .tracker import EvolutionTracker
from .pressure import AdaptivePressure


# ── 代际历史 ─────────────────────────────────────────────────────

@dataclass
class GenerationRecord:
    """一代进化的完整记录。"""
    generation: int
    genome: Genome
    report: FitnessReport
    strategy: str = "initial"
    accepted: bool = True
    rolled_back: bool = False
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        return {
            "generation": self.generation,
            "genome": self.genome.to_dict(),
            "report": self.report.to_dict(),
            "strategy": self.strategy,
            "accepted": self.accepted,
            "rolled_back": self.rolled_back,
            "timestamp": self.timestamp or time.time(),
        }


# ── 进化循环 ─────────────────────────────────────────────────────

class EvolutionLoop:
    """进化循环主控制器。

    用法:
        loop = EvolutionLoop()
        loop.run(generations=50)
        loop.print_report()
    """

    def __init__(
        self,
        results_dir: Optional[Path] = None,
        accept_threshold: float = 0.5,
        rollback_threshold: float = 0.5,
        parent_pool_size: int = 5,
        tracker: Optional[EvolutionTracker] = None,
        pressure: Optional[AdaptivePressure] = None,
    ):
        self.results_dir = results_dir or Path.home() / ".hermes" / "esae" / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # 当前状态
        self.current: Genome = Genome()
        self.parent_pool: list[Genome] = []
        self.generation: int = 0
        self.stagnation_count: int = 0
        self.history: list[GenerationRecord] = []

        # 配置
        self.accept_threshold = accept_threshold
        self.rollback_threshold = rollback_threshold
        self.parent_pool_size = parent_pool_size

        # 组件
        self.selector = MutationSelector(special_prob=0.02)
        self.snapshot_store = SnapshotStore()
        self.evaluator = DaemonRunner()
        self.tracker = tracker or EvolutionTracker()
        self.pressure = pressure or AdaptivePressure()

    # ── 运行 ──────────────────────────────────────────────────

    def run(self, generations: int = 50, verbose: bool = True) -> list[GenerationRecord]:
        """运行 N 代进化。"""
        # 第 0 代：初始 genome
        self._record_initial()
        self.tracker.log_info("start", f"进化开始: {generations} 代, 评估器={type(self.evaluator).__name__}")

        for gen in range(1, generations + 1):
            self.generation = gen
            self.tracker.next_generation()

            # 先执行一步进化
            record = self._step()
            self.history.append(record)

            # 再更新压力状态（基于当前代的策略）
            best = max(h.report.overall for h in self.history) if self.history else 0.0
            ps = self.pressure.update(
                gen, self.stagnation_count, best, self.history[-1].report.overall,
                special_triggered=(record.strategy == "special"),
            )

            # 动态调整选择器的特殊变异概率（影响下一代）
            self.selector.special_prob = ps.special_probability

            if verbose:
                self._print_generation(record, ps)

            # 每 10 代清理快照 + 输出压力状态
            if gen % 10 == 0:
                self.snapshot_store.clean_old()
                if verbose:
                    print(f"         {self.pressure.describe()}")

        # 保存
        self._save_history()
        self.tracker.log_info("complete", f"进化完成: {generations} 代")
        self.tracker.save()

        return self.history

    def _record_initial(self) -> None:
        """第 0 代：评估初始 genome。"""
        report = self.evaluator.evaluate(self.current)
        self.current.fitness = report.overall
        record = GenerationRecord(
            generation=0, genome=self.current, report=report,
            strategy="initial", accepted=True, timestamp=time.time(),
        )
        self.history.append(record)
        self.tracker.log_info("initial_genome", f"基线适应度: {report.overall:.4f}")

    def _step(self) -> GenerationRecord:
        """单步进化（受压力系统影响）。"""
        # 1. 快照
        self.snapshot_store.snapshot(self.current)

        # 2. 选策略（受停滞压力影响）
        strategy = self.selector.select(
            self.current, self.parent_pool, self.stagnation_count
        )
        self.tracker.log_mutation(self.generation, self.current, strategy)

        # 3. 变异
        child = self.selector.mutate(
            self.current, self.parent_pool, self.stagnation_count
        )
        child.generation = self.generation

        # 4. 评估
        report = self.evaluator.evaluate(child)
        child.fitness = report.overall
        child.stable = report.passed

        # 5. 压力调整后的决策
        ps = self.pressure.state
        pressure_threshold = ps.stability_threshold  # 动态门槛

        accepted = False
        rolled_back = False

        if not report.passed or report.stability < pressure_threshold:
            # 不稳或未达压力门槛 → 回退
            restored = self.snapshot_store.restore()
            if restored:
                self.current = restored
            rolled_back = True
            self.tracker.log_rollback(
                self.generation, child,
                f"stability={report.stability:.3f} < threshold={pressure_threshold:.3f}",
                report,
            )
        elif report.overall >= self.accept_threshold:
            accepted = True
            self.current = child
            self.parent_pool.append(child)
            if len(self.parent_pool) > self.parent_pool_size:
                self.parent_pool.pop(0)

            prev_fitness = self.history[-1].report.overall if self.history else 0.0
            # 基于百分比的进步判断：相比历史最佳需提升 >0.5%
            best_ever = max(h.report.overall for h in self.history) if self.history else 0.0
            if report.overall > best_ever * 1.005:
                self.stagnation_count = 0
            else:
                self.stagnation_count += 1

            self.tracker.log_accept(self.generation, child, report)
        else:
            # 合格但分数不够 → 拒绝但不回退（保留当前状态）
            self.stagnation_count += 1
            self.tracker.log_reject(
                self.generation, child,
                f"fitness={report.overall:.4f} < accept={self.accept_threshold}",
                report,
            )

        return GenerationRecord(
            generation=self.generation,
            genome=child, report=report,
            strategy=strategy,
            accepted=accepted, rolled_back=rolled_back,
            timestamp=time.time(),
        )

    # ── 输出 ──────────────────────────────────────────────────

    def _print_generation(self, record: GenerationRecord,
                         pressure_state=None) -> None:
        """输出单代结果（含压力信息）。"""
        r = record.report
        status = "✓" if record.accepted else ("↩" if record.rolled_back else "·")
        pressure_info = ""
        if pressure_state:
            pressure_info = f" thr={pressure_state.stability_threshold:.2f}"
        print(
            f"[{record.generation:3d}] {status} "
            f"fit={r.overall:.4f} "
            f"sta={r.stability:.3f} "
            f"hea={r.health:.3f} "
            f"fail={r.failure_metric:.3f} "
            f"eff={r.efficiency:.3f} "
            f"str={record.strategy:10s}"
            f"{pressure_info}"
        )

    def _save_history(self) -> None:
        """保存完整历史到 JSONL。"""
        path = self.results_dir / "generations" / f"evolution_{int(time.time())}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for record in self.history:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        # 同时保存最新符号链接
        latest = self.results_dir / "generations" / "latest.jsonl"
        if latest.exists():
            latest.unlink()
        latest.symlink_to(path.name)

    # ── 可视化 ────────────────────────────────────────────────

    def print_report(self) -> str:
        """输出完整进化报告（ASCII 图表）。"""
        if not self.history:
            return "没有进化历史。"

        lines = []
        lines.append("")
        lines.append("=" * 72)
        lines.append("  EASE Phase 1 — 进化报告")
        lines.append("=" * 72)
        lines.append("")

        # 统计
        total = len(self.history) - 1  # 减去第0代
        accepted = sum(1 for h in self.history[1:] if h.accepted)
        rolled = sum(1 for h in self.history[1:] if h.rolled_back)
        best_record = max(self.history, key=lambda h: h.report.overall)

        lines.append(f"  总代数:     {total}")
        lines.append(f"  接受:       {accepted} ({accepted/total*100:.0f}%)" if total > 0 else "  接受:       0")
        lines.append(f"  回退:       {rolled} ({rolled/total*100:.0f}%)" if total > 0 else "  回退:       0")
        lines.append(f"  最佳适应度: {best_record.report.overall:.4f} (第 {best_record.generation} 代)")
        lines.append(f"  当前适应度: {self.history[-1].report.overall:.4f}")
        lines.append("")

        # ── 适应度曲线 ────────────────────────────────────────
        lines.append("  ── 适应度进化曲线 ──")
        lines.append("")
        fitness_values = [h.report.overall for h in self.history]
        lines.extend(self._ascii_chart(
            fitness_values,
            width=50, height=10,
            label="fitness",
            marker="●",
        ))
        lines.append("")

        # ── 稳定性趋势 ────────────────────────────────────────
        lines.append("  ── 稳定性趋势 ──")
        lines.append("")
        stability_values = [h.report.stability for h in self.history]
        lines.extend(self._ascii_chart(
            stability_values,
            width=50, height=8,
            label="stability",
            marker="■",
            threshold=0.5,  # 硬门槛线
        ))
        lines.append("")

        # ── 各代详情 —— 最后 10 代 ────────────────────────────
        lines.append("  ── 最近 10 代详情 ──")
        lines.append("")
        lines.append("  gen  result  fitness  stability  health   fail   eff  strategy")
        lines.append("  " + "-" * 60)
        for h in self.history[-10:]:
            r = h.report
            status = "✓ ACCEPT" if h.accepted else ("↩ ROLLBACK" if h.rolled_back else "· SKIP  ")
            lines.append(
                f"  {h.generation:3d}  {status}  "
                f"{r.overall:.4f}  {r.stability:.4f}  "
                f"{r.health:.4f}  {r.failure_metric:.4f}  "
                f"{r.efficiency:.4f}  {h.strategy}"
            )

        lines.append("")
        lines.append("=" * 72)

        report_str = "\n".join(lines)
        print(report_str)

        # 保存到文件
        report_path = self.results_dir / "generations" / f"report_{int(time.time())}.txt"
        report_path.write_text(report_str, encoding="utf-8")
        print(f"\n  报告已保存: {report_path}")

        return report_str

    @staticmethod
    def _ascii_chart(
        values: list[float],
        width: int = 50,
        height: int = 10,
        label: str = "",
        marker: str = "●",
        threshold: Optional[float] = None,
    ) -> list[str]:
        """生成 ASCII 折线图。"""
        if not values:
            return ["  (no data)"]

        min_val = min(values)
        max_val = max(values)
        if max_val - min_val < 0.001:
            max_val = min_val + 0.1
        range_val = max_val - min_val

        lines_out = []
        step = max(1, len(values) // width)

        # 取采样点
        sampled = values[::step]
        if len(sampled) < 2:
            sampled = values
        x_positions = list(range(0, len(values), step))
        if len(x_positions) < 2:
            x_positions = [0]
            sampled = [values[0]]

        # 生成每一行
        for row in range(height, -1, -1):
            y_val = min_val + (row / height) * range_val
            line = ""

            for x in x_positions:
                v = values[min(x, len(values) - 1)]
                if v >= y_val and (row == height or v < min_val + ((row + 1) / height) * range_val):
                    if threshold is not None and abs(v - threshold) < range_val / height:
                        line += "╳"  # 阈值交叉点
                    else:
                        line += marker
                elif threshold is not None and abs(y_val - threshold) < range_val / height * 0.5:
                    line += "─"  # 阈值线
                elif row == 0 or row == height // 2:
                    line += "·"
                else:
                    line += " "

            # 标签
            if row == height:
                line += f"  {max_val:.3f}"
            elif row == 0:
                line += f"  {min_val:.3f}"
            if row == height // 2 and threshold is not None:
                lines_out.append(f"  {line}  threshold={threshold}")
            else:
                lines_out.append(f"  {line}")

        # X轴
        x_axis = "  " + "·" * len(x_positions)
        lines_out.append(x_axis)
        lines_out.append(f"  0{' ' * (len(x_positions) - 5)} {len(values) - 1}  gen")

        return lines_out


# ── 快捷函数 ────────────────────────────────────────────────────

def run_evolution(generations: int = 50, verbose: bool = True) -> EvolutionLoop:
    """快捷运行进化循环。"""
    loop = EvolutionLoop()
    loop.run(generations=generations, verbose=verbose)
    if verbose:
        loop.print_report()
    return loop
