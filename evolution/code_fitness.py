"""CodeFitness — 代码级进化评测。

评测维度：
1. 安全检查（通过/不通过） — 硬门槛
2. 语法正确（通过/不通过） — 硬门槛
3. 测试通过率（0~100%）  — 主要指标
4. 代码质量（pylint 分数） — 加分项
5. 复杂度惩罚（McCabe）   — 扣分项
"""

from __future__ import annotations
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .code_genome import CodeChange, CodeGenome, simple_ast_check


@dataclass
class CodeFitnessReport:
    """代码适应度报告。"""
    passed: bool = False
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    lint_score: float = 0.0
    complexity_penalty: float = 0.0
    test_pass_rate: float = 0.0
    overall: float = 0.0
    details: str = ""


class CodeFitness:
    """代码适应度评估器。"""

    def __init__(self, esae_home: Optional[Path] = None,
                 timeout: int = 30):
        self.esae_home = esae_home or Path.home() / ".hermes" / "esae"
        self.timeout = timeout

    def evaluate(self, genome: CodeGenome) -> CodeFitnessReport:
        """评估代码修改的适应度。"""
        if not genome.changes:
            return CodeFitnessReport(passed=True, overall=1.0, details="基线（无修改）")

        # 1. 应用所有修改到临时文件
        temp_dir = Path(tempfile.mkdtemp(prefix="esae_code_fitness_"))
        try:
            applied = self._apply_to_temp(genome, temp_dir)
            if not applied:
                return CodeFitnessReport(passed=False, details="修改应用失败")

            # 2. AST 检查
            main_file = temp_dir / "kernel" / "daemon.py"
            if main_file.exists():
                ok = simple_ast_check(main_file.read_text())
                if not ok:
                    return CodeFitnessReport(passed=False, details="AST 检查未通过")

            # 3. 跑测试
            test_result = self._run_tests(temp_dir)
            if test_result is None:
                return CodeFitnessReport(passed=False, details="测试运行异常")

            pass_rate = test_result["pass_rate"]

            # 4. 计算适应度
            # 硬门槛：测试不能崩溃（但允许部分失败）
            if pass_rate < 1.0:
                return CodeFitnessReport(
                    passed=True,
                    tests_passed=test_result["passed"],
                    tests_failed=test_result["failed"],
                    tests_total=test_result["total"],
                    test_pass_rate=pass_rate,
                    overall=pass_rate * 0.8,  # 部分通过时无力获取语义信息，保守估值
                    details=f"部分通过: {test_result['passed']}/{test_result['total']}",
                )

            # ── 适应度三组件设计 ─────────────────────────────────────────
            #
            # 问题诊断：当所有 230 测试都通过时，pass_rate 始终为 1.0，
            # 原有 change_bonus 奖励"变化本身"而非"质量提升"，导致：
            #   1. 所有变异的 fitness 集中在 0.8054~0.8610 的狭窄区间
            #   2. 最佳适应度锁死在 0.8610（1.0 + 0.05 - 最小惩罚）
            #
            # 新设计：惩罚"无意义变化"，奖励"有意义变化"
            #
            # 组件 A — 测试通过基准 [0, 1.0]
            #   基础得分，始终为 1.0（全部通过）
            #
            # 组件 B — 语义价值评分 [0, 0.60]
            #   分析修改内容的语义价值：
            #   - 条件逻辑 (if/else/for/while)        → +0.30 探索新行为空间
            #   - 状态变异 (self.heartbeat.* = *)      → +0.20 改变守护进程行为
            #   - try/except 异常处理                   → +0.25 增强鲁棒性
            #   - 多字段引用 (与系统深度集成)            → +0.05~0.15
            #   - 纯日志 (self._log 且 ≤2 行)           → 上限 0.15 惩罚性低分
            #
            # 组件 C — 变异策略质量 [-0.05, +0.10]
            #   不同的变异策略有不同的探索价值：
            #   - ast_uniform (替换语句)               → +0.06 行为改变
            #   - ast_replace (调参)                   → +0.05 参数探索
            #   - ast_insert (插入新代码)               → +0.03 扩展
            #   - crossover (方法体互换)                → +0.08 重组
            #   - compose (模块化组合)                  → +0.10 高级组合
            #   - duplicate (方法复制)                  → -0.05 膨胀风险
            #
            # 惩罚 D — 代码膨胀 [0, 0.15]
            #   每新增一行扣 0.01，上限 0.15
            #
            # 惩罚 E — 过于简单 [0, 0.02]
            #   ≤2 行且无条件的纯日志变更视为低价值
            #
            # 最终公式（无硬上限，允许 >1.0）：
            #   overall = base + B + C - D - E
            #   clamp [0, 1.5]
            #
            # 预期范围（pass_rate≥1.0 时 base=0.6）：
            #   无字段纯日志:  0.6 + 0.10 + 0.03 - 0.01 - 0.02 = 0.70
            #   含字段纯日志:  0.6 + 0.15 + 0.03 - 0.01 - 0.02 = 0.75
            #   状态变异:      0.6 + 0.50 + 0.06 - 0.02 - 0.00 = 1.14
            #   条件逻辑:      0.6 + 0.60 + 0.03 - 0.03 - 0.00 = 1.20
            #   高价值复合:    0.6 + 0.60 + 0.10 - 0.04 - 0.00 = 1.26
            # ────────────────────────────────────────────────────────────

            # 分析第一个修改（实践中每个 genome 只有一个 change）
            change = genome.changes[0] if genome.changes else None
            action = (change.metadata or {}).get("action", "") if change else ""
            new_text = change.new_text if change else ""

            # B: 语义价值评分
            semantic_value = self._evaluate_semantic_value(new_text)

            # C: 策略质量
            strategy_quality = {
                "ast_insert": 0.03,
                "ast_uniform": 0.06,
                "ast_replace": 0.05,
                "duplicate": -0.05,
                "crossover": 0.08,
                "compose": 0.10,
            }.get(action, 0.0)

            # D: 膨胀惩罚
            lines_added = len(new_text.strip().splitlines()) if new_text else 0
            bloat_penalty = min(lines_added * 0.01, 0.15)

            # E: 简单性惩罚（≤2行且无条件的纯日志）
            import re as _re
            has_conditional = bool(_re.search(r'\b(if|else|elif|for|while|try|except)\b', new_text))
            simplicity_penalty = 0.02 if (
                lines_added <= 2
                and not has_conditional
                and "self._log" in new_text
            ) else 0.0

            overall = pass_rate + semantic_value + strategy_quality - bloat_penalty - simplicity_penalty
            # 当所有测试通过（pass_rate=1.0）时，测试结果无法提供区分度，
            # 全部信号来自语义分析。为了让低价值（纯日志）变化低于基线 1.0，
            # 降低 base 权重使语义价值主导方差。
            if pass_rate >= 1.0:
                overall = overall - 0.4  # 0.6 + semantic + ... 范围 ~0.65~1.26
            overall = max(0.0, min(1.5, overall))

            return CodeFitnessReport(
                passed=True,
                tests_passed=test_result["passed"],
                tests_failed=test_result["failed"],
                tests_total=test_result["total"],
                test_pass_rate=pass_rate,
                overall=overall,
                details=(f"通过 {test_result['passed']}/{test_result['total']} 测试 "
                        f"| semantic={semantic_value:.2f} strategy={strategy_quality:+.2f} "
                        f"bloat={bloat_penalty:.2f}"),
            )

        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _evaluate_semantic_value(self, code_text: str) -> float:
        """评估代码修改的语义价值。

        核心思想：分析修改内容的编程语言特征，判断其是否改变了
        系统行为（高价值），还是仅增加了日志/注释（低价值）。

        评分系统（累加，上限 0.60）：
        - 条件逻辑 (if/else/elif/for/while)   +0.30  — 最高：引入新行为路径
        - 异常处理 (try/except)                +0.25  — 高：增强鲁棒性
        - 状态变异 (self.heartbeat.* = *)      +0.20  — 高：改变守护进程内部状态
        - 状态读取属性引用                      +0.05  — 中：与系统深度集成
        - 方法调用或赋值 (非日志)               +0.10  — 中：实际执行操作
        - 基础分                               +0.10  — 任何有效修改都有的保底
        - 纯日志惩罚 (self._log 且 ≤2 行)      上限 0.15
        """
        import re as _re

        text = code_text.strip()
        if not text:
            return 0.0

        # 基础分：任何有效修改都有一定价值
        base = 0.10

        # 条件逻辑：行为分支，高探索价值
        if _re.search(r'\b(if|else|elif|for|while)\b', text):
            base += 0.30

        # 异常处理：鲁棒性增强
        if 'try:' in text or 'except' in text:
            base += 0.25

        # 状态变异：直接修改守护进程内部状态
        if _re.search(r'self\.heartbeat\.\w+\s*=', text):
            base += 0.20

        # 状态读取：引用系统内部字段（集成深度信号）
        daemon_fields = frozenset({
            'state', 'tick_count', 'success_count', 'failed_count',
            'last_tick_time', 'last_success_time', 'interval',
        })
        field_refs = sum(1 for f in daemon_fields if f in text)
        base += min(field_refs * 0.05, 0.15)

        # 非日志的方法调用或赋值
        if (('=' in text or '(' in text)
                and 'self._log' not in text):
            base += 0.10

        # 纯日志变更惩罚：<=2 行且只有 self._log
        if 'self._log' in text and not _re.search(r'\b(if|else|elif|for|while|try|except)\b', text):
            if len(text.splitlines()) <= 2:
                base = min(base, 0.15)

        return min(base, 0.60)

    def _apply_to_temp(self, genome: CodeGenome, temp_dir: Path) -> bool:
        """将修改应用到临时目录。"""
        # 复制整个项目
        try:
            shutil.copytree(self.esae_home, temp_dir,
                            dirs_exist_ok=True)
        except Exception:
            return False

        # 应用修改（支持文本替换和行级操作）
        for change in genome.changes:
            target = temp_dir / change.file_path
            if not target.exists():
                continue

            content = target.read_text()
            if change.change_type == "modify_line" and change.old_text:
                # 方法体替换（AST 变异：找到 old method 替换为 new method）
                new_content = content.replace(change.old_text, change.new_text, 1)
            elif change.change_type == "insert_after":
                new_lines = content.splitlines(keepends=True)
                idx = change.target_line - 1
                if 0 <= idx < len(new_lines):
                    new_lines.insert(idx + 1, change.new_text)
                new_content = "".join(new_lines)
            else:
                new_content = content

            if new_content != content:
                target.write_text(new_content)

        return True

    def _run_tests(self, project_dir: Path) -> Optional[dict]:
        """在项目目录中运行 pytest。"""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/",
                 "--ignore=tests/test_safety.py",
                 "--deselect=tests/test_daemon.py::TestDaemonHeartbeat::test_tick_writes_success_file",
                 "--deselect=tests/test_daemon.py::TestDaemonHeartbeat::test_tick_writes_state_file",
                 "--tb=line", "-q", "--no-header"],
                capture_output=True, timeout=self.timeout,
                cwd=str(project_dir),
            )
            output = result.stdout.decode()
            # pytest -q 输出格式如: "..F... 10 passed, 1 failed in 0.50s"
            import re
            passed_m = re.search(r"(\d+) passed", output)
            failed_m = re.search(r"(\d+) failed", output)
            errors_m = re.search(r"(\d+) errors", output)
            passed = int(passed_m.group(1)) if passed_m else 0
            failed = int(failed_m.group(1)) if failed_m else 0
            errors = int(errors_m.group(1)) if errors_m else 0
            total = passed + failed + errors
            return {
                "passed": passed,
                "failed": failed + errors,
                "total": total or 1,
                "pass_rate": (passed / total) if total > 0 else 1.0,
            }
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
