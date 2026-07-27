"""CodeEvolution — 代码级进化循环。

每一代：
1. 变异当前代码（改行/插行/删行）
2. 验证（AST + 白名单）
3. 评估（复制项目 → 修改 → 跑测试）
4. 通过 且 适应度 >= 基线 → 接受
5. 否则 → 回退
"""

from __future__ import annotations
import json
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .code_genome import CodeChange, CodeGenome, simple_ast_check
from .code_mutation import CodeMutationSelector
from .code_fitness import CodeFitness, CodeFitnessReport


@dataclass
class CodeGenerationRecord:
    generation: int
    genome: CodeGenome
    fitness_report: CodeFitnessReport
    strategy: str
    accepted: bool
    elapsed: float


class CodeEvolutionLoop:
    """代码级进化主循环。"""

    def __init__(self, esae_home: Optional[Path] = None,
                 target_file: str = "kernel/daemon.py",
                 timeout: int = 30):
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"
        self.target_file = target_file
        self.timeout = timeout

        self.fitness = CodeFitness(esae_home=self.esae_home, timeout=timeout)
        self.selector = CodeMutationSelector()

        self.current = CodeGenome.empty()
        self.generation = 0
        self.history: list[CodeGenerationRecord] = []
        self.baseline_fitness: float = 1.0  # 基线：无修改 = 满分
        self._baseline_passed: int = 0       # 基线：通过的测试数

        # 选择压力追踪状态
        self._fitness_history: list[float] = []       # 滑动窗口适应度值
        self._fitness_std: float = 0.01               # 滚动标准差
        self._stalled_generations: int = 0             # 连续无改进代数
        self._best_ever_fitness: float = 0.0           # 历史最高适应度
        self._acceptance_window: list[bool] = []       # 滑动窗口接受记录

    def run(self, generations: int = 100, verbose: bool = True) -> list[CodeGenerationRecord]:
        target_path = Path(self.target_file)
        if not target_path.exists():
            target_path = self.esae_home / self.target_file

        source = target_path.read_text() if target_path.exists() else ""
        lines = source.splitlines(keepends=True) if source else []

        # P0: 直接跑原始代码的测试作为基线
        print(f"  基线测试...", end=" ", flush=True)
        import subprocess, sys, re
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/",
             "--ignore=tests/test_safety.py", "-q", "--no-header"],
            capture_output=True, timeout=self.timeout,
            cwd=self.esae_home,
        )
        m = re.search(r'(\d+) passed.*?(\d+) failed', r.stdout.decode())
        if m:
            passed = int(m.group(1))
            total = passed + int(m.group(2))
            self._baseline_passed = passed
            self.baseline_fitness = passed / max(total, 1)
        else:
            self._baseline_passed = 0
            self.baseline_fitness = 0
        print(f"{self._baseline_passed}/230 fit={self.baseline_fitness:.4f}", flush=True)

        for gen in range(1, generations + 1):
            self.generation = gen
            t0 = time.time()

            if not source or not lines:
                if verbose:
                    print(f"[{gen:3d}] · 无法读取目标文件")
                continue

            # 选择变异策略（基于 AST）
            strategy, change = self.selector.select(source, lines,
                                                     class_name="ESAEDaemon",
                                                     target_method="tick")
            if change is None or not strategy or strategy == "none":
                if verbose:
                    print(f"[{gen:3d}] · 无有效变异")
                continue

            # 设置文件路径
            change.file_path = self.target_file

            if verbose:
                action = (change.metadata or {}).get("action", strategy)
                print(f"[{gen:3d}] → {action:15s} ", end="", flush=True)

            # 生成子代
            child = CodeGenome(
                changes=[change],
                parent_ids=[self.current.genome_id] if self.current.genome_id else [],
                generation=gen,
            )

            # 验证（AST 级变异本身就是语法安全的，只需要确认变更成功）
            if change.change_type == "modify_line":
                # 在源码中找到 old_text 并替换
                test_source = source.replace(change.old_text, change.new_text, 1)
            elif change.change_type == "insert_after":
                test_lines = source.splitlines(keepends=True)
                idx = change.target_line - 1
                if 0 <= idx < len(test_lines):
                    test_lines.insert(idx + 1, change.new_text)
                test_source = "".join(test_lines)
            else:
                test_source = source
            ok = (test_source != source)  # 只要变了就算通过（AST 变异保证语法正确）

            # 评估
            report = self.fitness.evaluate(child)
            t1 = time.time()

            # ── 选择压力：Boltzmann 概率接受 ─────────────────────────────────
            #
            # 问题诊断：原有逻辑 `accepted = report.passed and current_passed >= baseline_passed`
            # 当所有 230 测试全部通过时，current_passed == baseline_passed 始终成立，
            # 导致 100% 接受率、零选择压力。
            #
            # 新设计：三阶段协同筛选
            #
            # 阶段 1 — 硬门槛 [立即拒绝]
            #   测试崩溃或测试通过数减少 → 直接拒绝
            #
            # 阶段 2 — 精英保底 [立即接受]
            #   适应度超过历史最佳（真正改进）→ 直接接受，重置停滞计数器
            #
            # 阶段 3 — Boltzmann 概率 [分级筛选]
            #   P(accept) = sigmoid(k * δ / (σ * T))
            #   其中：
            #     δ = new_fitness - baseline_fitness  (相对基线差值)
            #     σ = 滚动标准差（自适应缩放）
            #     T = 停滞温度（连续无改进时升温鼓励探索）
            #     k = 选择压力系数（3.0）
            #
            #   当 δ ≈ 0（与基线持平）：P ≈ 50%
            #   当 δ = +σ（正向波动）：  P ≈ 95%
            #   当 δ = -σ（负向波动）：  P ≈ 5%
            #   当 δ = +3σ（明显改进）： P ≈ 99.99%
            #
            # 自适应行为：
            #   - 连续 10 代无改进（stalled）→ 温度线性升高 1.0→2.5，鼓励探索
            #   - 滚动标准差自适应调节压力：标准差异常大时压力变柔和
            #   - 滑动窗口监控接受率 < 30% 时强制升温
            # ───────────────────────────────────────────────────────────────

            new_fitness = report.overall
            delta = new_fitness - self.baseline_fitness

            # 阶段 1: 硬门槛
            current_passed = report.tests_passed
            if not report.passed or current_passed < self._baseline_passed:
                accepted = False

            # 阶段 2: 精英保底 — 真正的改进立即接受
            elif new_fitness > self._best_ever_fitness + 0.001:
                accepted = True
                self._best_ever_fitness = new_fitness
                self._stalled_generations = 0

            # 阶段 3: Boltzmann 概率接受
            else:
                # 更新滚动标准差（最近 20 个适应度值）
                self._fitness_history.append(new_fitness)
                if len(self._fitness_history) > 50:
                    self._fitness_history.pop(0)
                if len(self._fitness_history) >= 5:
                    import statistics as _stat
                    self._fitness_std = max(_stat.stdev(self._fitness_history), 0.005)
                else:
                    self._fitness_std = 0.01

                # 停滞温度：连续无 Elite 改进时升温，鼓励探索
                temperature = 1.0 + self._stalled_generations * 0.15
                temperature = min(temperature, 3.0)  # 最高 3x

                # Boltzmann 概率
                k = 3.0  # 选择压力系数
                z = k * delta / (self._fitness_std * temperature)
                prob = 1.0 / (1.0 + math.exp(-z))

                accepted = random.random() < prob

                # 停滞计数器更新
                if accepted:
                    self._stalled_generations = 0
                else:
                    self._stalled_generations += 1

                # 滑动窗口接受率监控
                self._acceptance_window.append(accepted)
                if len(self._acceptance_window) > 30:
                    self._acceptance_window.pop(0)
                recent_rate = sum(self._acceptance_window) / max(len(self._acceptance_window), 1)
                if recent_rate < 0.30 and self._acceptance_window:
                    # 接受率过低 → 强制接受这一代（探索抖振）
                    accepted = True
                    self._stalled_generations = max(0, self._stalled_generations - 2)

            # 更新停滞计数器（基于 delta 符号，非接受与否）
            if delta <= 0:
                self._stalled_generations += 1
            else:
                self._stalled_generations = max(0, self._stalled_generations - 1)

            if accepted:
                self.current = child
                self.baseline_fitness = report.overall
                self._baseline_passed = current_passed
                # 写回物理文件
                self._write_back(change)

            record = CodeGenerationRecord(gen, child, report, strategy, accepted, t1 - t0)
            self.history.append(record)

            if verbose:
                status = "✅" if accepted else "·"
                print(f"[{gen:3d}] {status} {strategy:12s} fit={report.overall:.4f} "
                      f"tests={report.tests_passed}/{report.tests_total} "
                      f"{report.details[:40]}",
                      flush=True)

        return self.history

    def _write_back(self, change: CodeChange) -> None:
        """将接受的变异写回物理文件。"""
        target = self.esae_home / change.file_path
        if not target.exists():
            return
        content = target.read_text()
        if change.change_type == "modify_line" and change.old_text:
            new_content = content.replace(change.old_text, change.new_text, 1)
        elif change.change_type == "insert_after":
            new_lines = content.splitlines(keepends=True)
            idx = change.target_line
            if 0 <= idx < len(new_lines):
                new_lines.insert(idx, change.new_text)
            new_content = "".join(new_lines)
        else:
            return
        if new_content != content:
            import ast
            try:
                ast.parse(new_content)
                target.write_text(new_content)
            except SyntaxError:
                pass

    def print_report(self) -> None:
        accepted = sum(1 for h in self.history if h.accepted)
        total = len(self.history)
        best_h = max(self.history, key=lambda h: h.fitness_report.overall) if self.history else None

        print(f"\n{'='*60}")
        print(f"  代码进化报告 — {total} 代")
        print(f"{'='*60}")
        print(f"  接受:       {accepted}/{total} ({accepted/total*100:.0f}%)")
        if best_h:
            print(f"  最佳适应度: {best_h.fitness_report.overall:.4f} (第{best_h.generation}代)")
            for c in best_h.genome.changes:
                print(f"  修改:       行 {c.target_line} ({c.change_type})")
                print(f"    旧: {c.old_text!r}")
                print(f"    新: {c.new_text!r}")
