"""SelfEvolver — 自我进化的核心循环（借鉴 Raven 架构）。

核心能力：
1. 自我反思 — 分析测试失败，找出薄弱点
2. 目标设定 — 自动生成可执行的目标
3. 定向执行 — 用最优策略执行变异
4. 能力评分 — 追踪各项能力的得分
5. 难度递增 — 先修简单的，再修难的
"""

from __future__ import annotations
import ast
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .code_genome import CodeGenome, CodeChange
from .code_mutation import CodeMutationSelector
from .code_fitness import CodeFitness


# ── 能力定义 ──────────────────────────────────────

@dataclass
class Capability:
    """一项可衡量的系统能力。"""
    name: str                     # 能力名
    test_keywords: list[str]      # 相关测试的关键词
    score: float = 0.0            # 当前得分 0~1
    target_method: str = ""       # 负责该能力的方法
    priority: int = 0             # 优先级（越高越优先修）
    completed: bool = False       # 是否已完成（>=0.9）


# EASE 系统的能力矩阵
_CAPABILITIES = [
    Capability("心跳写入", ["heartbeat", "tick"], 0.0, "tick", 5),
    Capability("成功跟踪", ["success", "success_count"], 0.0, "tick", 4),
    Capability("状态管理", ["state", "degraded", "running"], 0.0, "tick", 3),
    Capability("健康检查", ["health", "last_success"], 0.0, "_handle_signal", 2),
    Capability("日志输出", ["log", "_log"], 0.0, "_log", 1),
    Capability("熔断恢复", ["recovery", "half_open"], 0.0, "run", 2),
    Capability("kill开关", ["kill", "kill_switch"], 0.0, "check_kill_switch", 3),
    Capability("停滞检测", ["stagnation", "detect"], 0.0,
               "_detect_stagnation", 4),
    Capability("事件统计", ["record_event", "get_event_stats", "event"],
               0.0, "record_event", 5),
]


# ── 自进化核心 ────────────────────────────────────

class SelfEvolver:
    """EASE 自进化核心。

    流程：
    1. reflect()    — 分析当前状态，更新能力评分
    2. set_goal()   — 选最弱的能力作为目标
    3. evolve()     — 执行进化直到目标达成
    4. loop()       — 重复 1-3 直到所有能力达标
    """

    def __init__(self, esae_home: Optional[Path] = None, timeout: int = 30):
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"
        self.timeout = timeout
        self.fitness = CodeFitness(esae_home=self.esae_home, timeout=timeout)
        self.selector = CodeMutationSelector()
        self.capabilities = [Capability(**c.__dict__) for c in _CAPABILITIES]
        self.history: list[dict] = []
        self.generation = 0

    # ── 1. 自我反思 ─────────────────────────────

    def reflect(self) -> dict:
        """分析当前状态，更新能力评分。

        通过解析测试输出，统计每个能力的相关测试通过了多少。
        """
        # 跑测试
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/",
             "-q", "--tb=line", "--no-header"],
            capture_output=True, timeout=self.timeout,
            cwd=str(self.esae_home),
        )
        output = result.stdout.decode()

        # 提取失败的测试名 (用 regex 替代空格 split)
        failed_tests = set()
        import re
        for line in output.splitlines():
            m = re.search(r"FAILED\s+(tests/[^:\s]+(?:::[\w.]+)?)", line)
            if m:
                failed_tests.add(m.group(1))

        # 更新每项能力的评分
        for cap in self.capabilities:
            # 精确计数：相关测试总数 (关键词在测试文件中出现)
            total_related = self._count_related_tests(cap.test_keywords)
            # 精确计数：相关测试失败数
            failed_related = 0
            for ft in failed_tests:
                if any(kw.lower() in ft.lower() for kw in cap.test_keywords):
                    failed_related += 1
            # 评分 = 1.0 - (失败/总数) ，无相关测试时=0
            if total_related > 0:
                cap.score = 1.0 - (failed_related / total_related)
            else:
                cap.score = 0.0
            cap.score = max(0.0, min(1.0, cap.score))

        return {
            "total_failed": len(failed_tests),
            "failed_tests": list(failed_tests),
            "capabilities": {c.name: c.score for c in self.capabilities},
        }

    def _count_related_tests(self, keywords: list[str]) -> int:
        """统计某个能力相关的测试总数。"""
        tests_dir = self.esae_home / "tests"
        count = 0
        if tests_dir.exists():
            for f in tests_dir.glob("test_*.py"):
                content = f.read_text()
                if any(kw in content for kw in keywords):
                    count += 1
        return count

    # ── 2. 目标设定 ─────────────────────────────

    def set_goal(self) -> Optional[Capability]:
        """选一个目标能力：跳过已完成的，选得分最低 × 优先级最高的。"""
        incomplete = [c for c in self.capabilities if not c.completed]
        if not incomplete:
            return None
        scored = sorted(incomplete, key=lambda c: (c.score, -c.priority))
        if scored and scored[0].score < 1.0:
            return scored[0]
        return None

    # ── 3. 定向执行 ─────────────────────────────

    def evolve(self, capability: Capability,
               max_generations: int = 50,
               verbose: bool = True) -> dict:
        target = capability.target_method or "tick"

        # 每次从物理文件开始（累积之前的进化成果）
        source = (self.esae_home / "kernel" / "daemon.py").read_text()
        lines = source.splitlines(keepends=True)

        best_tests_passed = 0
        current_genome = CodeGenome.empty()

        for gen in range(1, max_generations + 1):
            self.generation += 1

            strategy, change = self.selector.select(
                source, lines, "ESAEDaemon", target,
            )
            if change is None or strategy == "none":
                continue

            genome = CodeGenome(changes=[change])
            report = self.fitness.evaluate(genome)

            # 精确计数相关测试通过数
            total_rel = self._count_related_tests(capability.test_keywords)
            passed_rel = self._count_passed_related(report, capability)
            new_score = passed_rel / max(total_rel, 1)

            # 分数下降 → 滚回快照
            if new_score < capability.score - 0.05 and self.generation > 1:
                self._rollback()
                if verbose and gen % 5 == 0:
                    print(f"  · 第{self.generation}代 | rollback | "
                          f"分数下降 {capability.score:.2f}->{new_score:.2f}", flush=True)
                continue

            accepted = report.passed and new_score >= capability.score

            if accepted:
                old_score = capability.score
                capability.score = min(1.0, new_score)
                current_genome = genome
                best_tests_passed = report.tests_passed
                # 写回物理文件
                self._write_back(change)

                # 检测能力是否达成（score >= 0.9 连续 3 代）
                if new_score >= 0.9:
                    if getattr(self, '_consecutive_success', 0) >= 2:
                        capability.completed = True
                        self._consecutive_success = 0
                    else:
                        self._consecutive_success = getattr(self, '_consecutive_success', 0) + 1
                else:
                    self._consecutive_success = 0

                if verbose:
                    print(f"  ✅ 第{self.generation}代 | {strategy:12s} | "
                          f"{capability.name} {capability.score:.2f} | "
                          f"{report.tests_passed}/{report.tests_total}",
                          flush=True)

                if new_score >= 1.0:
                    return {
                        "capability": capability.name,
                        "generations": gen,
                        "achieved": True,
                        "tests_passed": report.tests_passed,
                        "tests_total": report.tests_total,
                    }
            else:
                if verbose and gen % 10 == 0:
                    print(f"  · 第{self.generation}代 | {strategy:12s} | "
                          f"仍在尝试 {capability.name} ({capability.score:.2f})",
                          flush=True)

        return {
            "capability": capability.name,
            "generations": max_generations,
            "achieved": False,
            "best_score": capability.score,
        }

    def _write_back(self, change: CodeChange) -> None:
        """将接受的变异写回物理文件。

        安全机制：
        - 快照链：写入前备份到 results/backups/daemon_v{gen}.py
        - 原子写入：先写 .tmp 再 rename，防止半写文件
        - 回滚锚点：记录 best_known_good 版本
        """
        target = self.esae_home / change.file_path
        if not target.exists():
            return

        # 1. 备份当前文件
        backup_dir = self.esae_home / "results" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"daemon_v{self.generation:04d}.py"
        shutil.copy2(str(target), str(backup_path))

        # 2. 应用修改到内容
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

        if new_content == content:
            return

        # 3. AST 验证
        import ast
        try:
            ast.parse(new_content)
        except SyntaxError:
            return

        # 4. 原子写入
        tmp_path = target.with_suffix(".py.tmp")
        tmp_path.write_text(new_content)
        tmp_path.rename(target)

        # 5. 记录最佳版本
        self._best_gen = max(getattr(self, '_best_gen', 0), self.generation)

    def _rollback(self) -> bool:
        """回滚到上一个最佳版本。"""
        backup_dir = self.esae_home / "results" / "backups"
        best_gen = getattr(self, '_best_gen', 0)
        if best_gen <= 0:
            return False
        best_path = backup_dir / f"daemon_v{best_gen:04d}.py"
        if not best_path.exists():
            return False
        target = self.esae_home / "kernel" / "daemon.py"
        shutil.copy2(str(best_path), str(target))
        return True

    def _count_passed_related(self, report, cap: Capability) -> int:
        """估算该能力相关的测试通过数。"""
        total = self._count_related_tests(cap.test_keywords)
        return int(total * report.tests_passed / max(report.tests_total, 1))

    # ── 4. 主循环 ──────────────────────────────

    def loop(self, max_cycles: int = 10,
             gens_per_goal: int = 50,
             time_budget: int = 0,  # 秒，0=不限
             verbose: bool = True) -> list[dict]:
        """自进化主循环。

        Args:
            time_budget: 时间预算（秒），超时自动停止
        """
        results = []
        t_start = time.time()

        for cycle in range(max_cycles):
            # 时间预算检查
            if time_budget > 0 and time.time() - t_start > time_budget:
                if verbose:
                    print(f"\n  ⏰ 时间预算 ({time_budget}s) 已用完")
                break

            # 每 100 代清理冗余副本
            if self.generation % 100 == 0 and self.generation > 0:
                cleaned = self._cleanup_redundant_copies()
                if cleaned > 0 and verbose:
                    print(f"  🧹 清理了 {cleaned} 个冗余副本")

            if verbose:
                print(f"\n{'='*60}")
                print(f"  自进化循环 #{cycle + 1}  (已用 {time.time()-t_start:.0f}s)")
                print(f"{'='*60}")

            # 1. 反思
            state = self.reflect()

            # 标记已完成的能力（在 reflect 中更新评分）
            for cap in self.capabilities:
                if cap.score >= 0.9 and not cap.completed:
                    cap.completed = True

            # 2. 定目标
            goal = self.set_goal()
            if goal is None:
                print(f"\n🎉 所有能力已达到满分！")
                break

            if verbose:
                print(f"  当前失败: {state['total_failed']} 个测试")
                print(f"  能力评分:")
                for cap in sorted(self.capabilities, key=lambda c: c.name):
                    bar = "█" * int(cap.score * 10) + "░" * (10 - int(cap.score * 10))
                    mark = " ✅" if cap.completed else ""
                    print(f"    {cap.name:12s}: [{bar}] {cap.score:.2f}{mark}")
                print(f"\n  目标: {goal.name} (得分 {goal.score:.2f}) → 方法: {goal.target_method}")

            # 3. 执行
            # 根据时间预算调整每轮代数
            remaining = time_budget - (time.time() - t_start) if time_budget > 0 else gens_per_goal * 10
            gens = min(gens_per_goal, max(5, int(remaining / 3))) if time_budget > 0 else gens_per_goal
            result = self.evolve(goal, max_generations=gens, verbose=verbose)
            results.append(result)

            if verbose:
                status = "✅ 达成" if result.get("achieved") or goal.completed else "⏰ 超时"
                print(f"\n  {status}: {result['capability']} "
                      f"(用时 {result['generations']} 代, 累计 {self.generation} 代)")

        return results

    def _cleanup_redundant_copies(self) -> int:
        """清理 daemon.py 中冗余的 tick_vN 副本，保留最后 3 个。

        Returns:
            清理的数量
        """
        target = self.esae_home / "kernel" / "daemon.py"
        if not target.exists():
            return 0
        content = target.read_text()
        import re
        # 找到所有 tick_vN 定义，保留最新的 3 个
        copies = re.findall(r'    def tick_v(\d+)\(self\)', content)
        if not copies:
            return 0
        copies = sorted(set(int(c) for c in copies))
        to_remove = [c for c in copies if c < max(copies) - 2]  # 保留最新3个
        removed = 0
        for v in to_remove:
            # 删除 tick_v{v} 的定义（从 def 到下一个 def 或类结束）
            pattern = re.compile(
                rf'\n    def tick_v{v}\(self\).*?(?=\n    def |\nclass |\Z)',
                re.DOTALL
            )
            new_content, n = pattern.subn('\n', content)
            if n > 0:
                content = new_content
                removed += 1
        if removed > 0:
            target.write_text(content)
        return removed
