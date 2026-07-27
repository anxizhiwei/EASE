"""V0.1.0 Driver — 端到端验证脚本。

运行流程:
  1. 创建 EvolutionLoop 实例（使用 KernelEvaluator 替代 DaemonRunner）
  2. 跑 100 代进化
  3. 每 10 代输出 ASCII 曲线
  4. 最终输出: 进化报告 + 最佳 genome 参数
  5. 验证: genome 参数真实改变了 CB 行为

验证标准:
  1. genome 参数在 100 代内产生真实变化（不是全部 0.92 不动）
  2. fitness 有区分度（不是所有代都相同分数）
  3. CB 状态分布随参数变化而不同
  4. 输出标准的 ASCII 进化报告
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path
from typing import Optional

# ── 确保 esae 在路径中 ──────────────────────────────────────────
_ESAE_HOME = Path.home() / ".hermes"
if str(_ESAE_HOME) not in sys.path:
    sys.path.insert(0, str(_ESAE_HOME))

from esae.evolution.evolution_loop import EvolutionLoop
from esae.evolution.fitness import FitnessReport
from esae.evolution.genome import EASE_PARAMS, Genome


# ═════════════════════════════════════════════════════════════════
# KernelEvaluator — 直接使用 FSM + CircuitBreaker 做评测
# ═════════════════════════════════════════════════════════════════

class KernelEvaluator:
    """Kernel 评估器：直接使用真实 FSM + CircuitBreaker 做评测。

    相比 DaemonRunner（subprocess 隔离），本评估器在进程内直接
    构造 CircuitBreaker 实例并模拟调用序列，更快、无进程开销。

    确定性：同一 genome 在同一环境下总是产生相同分数（Random(42)）。
    """

    def __init__(self, num_cycles: int = 200):
        self.num_cycles = num_cycles

    def evaluate(self, genome: Genome) -> FitnessReport:
        """评估 genome 在真实 CB/FSM 下的表现。"""
        from esae.kernel.circuit import CircuitBreaker
        from esae.kernel.fsm import FSMState

        params = genome.params
        _interval, threshold, window = params[0], params[1], params[2]
        _relax, _tighten = params[3], params[4]
        wait_duration, half_open_max = params[5], params[6]

        # 用 genome 参数构造真实 CircuitBreaker
        cb = CircuitBreaker(
            window_size=max(3, int(window)),
            min_samples=max(3, int(window * 0.3)),
            failure_threshold=threshold,
            wait_duration_seconds=wait_duration,
            half_open_max_permits=int(half_open_max),
            slow_call_threshold_seconds=999,
            slow_call_rate_threshold=1.0,
        )

        open_count = half_open_count = closed_count = 0
        success_calls = fail_calls = 0
        recovery_times: list[int] = []
        open_tick: Optional[int] = None
        rng = random.Random(42)  # 确定性种子 — 同一 genome 始终同分

        for tick in range(self.num_cycles):
            # 动态失败概率：threshold=0.5 为 sweet spot
            # threshold=0.7 → fail_prob=0.10 安全
            # threshold=0.6 → fail_prob=0.20 安全
            # threshold=0.5 → fail_prob=0.30 CB 边界（小变化决定开关）
            # threshold=0.4 → fail_prob=0.40 开始频繁打开
            # threshold=0.3 → fail_prob=0.50 频繁打开
            # threshold=0.2 → fail_prob=0.60 持续打开
            fail_prob = max(0.0, min(1.0, 0.8 - threshold))
            failed = rng.random() < fail_prob
            if failed:
                cb.record_failure(duration=0.1)
                fail_calls += 1
            else:
                cb.record_success(duration=0.05)
                success_calls += 1

            state = cb.state
            if state == FSMState.OPEN:
                open_count += 1
                if open_tick is None:
                    open_tick = tick
            elif state == FSMState.HALF_OPEN:
                half_open_count += 1
            else:
                closed_count += 1
                if open_tick is not None:
                    recovery_times.append(tick - open_tick)
                    open_tick = None

        total = max(self.num_cycles, 1)
        stability = closed_count / total
        health = 1.0 - (open_count / total)
        success_rate = success_calls / total
        if recovery_times:
            avg_rec = sum(recovery_times) / len(recovery_times)
            efficiency = 1.0 - min(1.0, avg_rec / max(total * 0.5, 1))
        else:
            efficiency = 0.8 if open_count == 0 else 0.2

        passed = stability >= 0.7
        overall = stability * 0.40 + health * 0.30 + success_rate * 0.20 + efficiency * 0.10
        if not passed:
            overall = 0.0

        return FitnessReport(
            genome_id=genome.genome_id,
            overall=round(overall, 4),
            stability=round(stability, 4),
            health=round(health, 4),
            failure_metric=round(success_rate, 4),
            efficiency=round(efficiency, 4),
            passed=passed,
        )


# ═════════════════════════════════════════════════════════════════
# ASCII 进化曲线（每 10 代输出）
# ═════════════════════════════════════════════════════════════════

def print_ascii_curve(
    fitness_values: list[float],
    label: str = "fitness",
    width: int = 40,
    height: int = 6,
) -> None:
    """每隔 10 代输出的简版 ASCII 曲线。"""
    if not fitness_values:
        return

    min_v = min(fitness_values)
    max_v = max(fitness_values)
    if max_v - min_v < 0.001:
        max_v = min_v + 0.1
    rng_v = max_v - min_v

    step = max(1, len(fitness_values) // width)
    sampled = fitness_values[::step]
    x_pos = list(range(0, len(fitness_values), step))
    if len(sampled) < 2:
        sampled = fitness_values
        x_pos = list(range(len(fitness_values)))

    lines = [f"  ── {label} 进化曲线 ──"]
    for row in range(height, -1, -1):
        y_val = min_v + (row / height) * rng_v
        line_chars: list[str] = []
        for x in x_pos:
            v = fitness_values[min(x, len(fitness_values) - 1)]
            if v >= y_val and v < min_v + ((row + 1) / height) * rng_v:
                line_chars.append("●")
            elif row == 0 or row == height // 2:
                line_chars.append("·")
            else:
                line_chars.append(" ")
        side_label = f"  {max_v:.3f}" if row == height else (
            f"  {min_v:.3f}" if row == 0 else ""
        )
        lines.append(f"  {''.join(line_chars)}{side_label}")

    # x 轴
    lines.append(f"  {'·' * len(x_pos)}")
    lines.append(f"  0{' ' * (len(x_pos) - 5)}{len(fitness_values) - 1}")
    for l in lines:
        print(l)


# ═════════════════════════════════════════════════════════════════
# 验证引擎
# ═════════════════════════════════════════════════════════════════

def run_validation(loop: EvolutionLoop) -> dict[str, bool]:
    """运行 4 项端到端验证，返回 {检查项: 是否通过}。"""
    history = loop.history
    results: dict[str, bool] = {}

    # ── 验证 1: 参数变化 ──
    initial_params = history[0].genome.params
    final_params = history[-1].genome.params
    params_changed = sum(
        1 for i in range(len(initial_params))
        if abs(initial_params[i] - final_params[i]) > 0.01
    )
    results["params_changed"] = params_changed > 0

    # ── 验证 2: fitness 区分度 ──
    fitness_values = [h.report.overall for h in history[1:]]
    unique_fitness = len(set(round(v, 4) for v in fitness_values))
    fitness_range = max(fitness_values) - min(fitness_values) if fitness_values else 0
    results["fitness_diverse"] = unique_fitness > 1 and fitness_range > 0.001

    # ── 验证 3: CB 状态分布变化 ──
    cb_stabilities = [h.report.stability for h in history]
    cb_range = max(cb_stabilities) - min(cb_stabilities) if cb_stabilities else 0
    results["cb_state_changed"] = cb_range > 0.01

    # ── 验证 4: 报告已保存 ──
    report_dir = loop.results_dir / "generations"
    reports = list(report_dir.glob("report_*.txt"))
    results["report_saved"] = len(reports) > 0

    total_checks = sum(1 for v in results.values())
    passed_checks = sum(1 for v in results.values() if v)
    results["all_passed"] = total_checks > 0 and passed_checks == total_checks

    return results


def print_validation(results: dict[str, bool], loop: EvolutionLoop) -> None:
    """输出验证结果。"""
    history = loop.history
    initial_params = history[0].genome.params

    print()
    print("  ── 验证结果 ──")
    print()

    labels = {
        "params_changed": "参数产生真实变化",
        "fitness_diverse": "Fitness 有区分度",
        "cb_state_changed": "CB 状态分布变化",
        "report_saved": "报告已保存到文件",
    }
    all_ok = True
    for key, label in labels.items():
        ok = results.get(key, False)
        icon = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        print(f"  {icon} [{key:20s}] {label}")

    # ── 最佳 genome ──
    best = max(history, key=lambda h: h.report.overall)
    print()
    print(f"  ── 最佳 genome (第 {best.generation} 代, fit={best.report.overall:.4f}) ──")
    for i, p in enumerate(EASE_PARAMS):
        init_v = initial_params[i]
        final_v = best.genome.params[i]
        arrow = "→" if abs(final_v - init_v) > 0.01 else "="
        marker = "●" if abs(final_v - p.default) > 0.01 else "○"
        print(f"    {marker} {p.name:25s} {init_v:6.2f} {arrow} {final_v:6.2f}  [{p.min_val:.0f}~{p.max_val:.0f}]")

    # ── 总体判定 ──
    print()
    verdict = "✅ V0.1.0 端到端验证通过" if all_ok else "❌ V0.1.0 验证未通过"
    print(f"  {verdict}")


# ═════════════════════════════════════════════════════════════════
# 主流程
# ═════════════════════════════════════════════════════════════════

def main(generations: int = 100) -> None:
    """V0.1.0 驱动主入口。

    1. 创建 EvolutionLoop（使用 KernelEvaluator）
    2. 跑 100 代进化，每 10 代输出 ASCII 曲线
    3. 输出进化报告 + 最佳 genome
    4. 运行 4 项验证
    """
    # ── 内核模块检查 ──
    kernel_path = _ESAE_HOME / "esae" / "kernel"
    if not kernel_path.exists():
        print(f"❌ kernel 模块不存在: {kernel_path}")
        sys.exit(1)

    # ── 标题 ──
    print()
    print("=" * 72)
    print("  EASE V0.1.0 端到端验证")
    print("=" * 72)
    print(f"  评估器: KernelEvaluator (进程内 FSM + CircuitBreaker)")
    print(f"  代数:   {generations}")
    print(f"  参数:  {len(EASE_PARAMS)} 个可进化参数")
    print()

    # ── 创建 EvolutionLoop 并替换评估器 ──
    evaluator = KernelEvaluator(num_cycles=200)
    loop = EvolutionLoop(accept_threshold=0.4)
    loop.evaluator = evaluator  # 使用 KernelEvaluator 替代默认 DaemonRunner

    # 提高初始特殊变异概率，打破对称性
    loop.selector.special_prob = 0.15

    # ── 运行进化 ──
    t0 = time.time()

    # 第 0 代（初始 genome）
    loop._record_initial()
    loop.tracker.log_info("start", f"进化开始: {generations} 代, 评估器=KernelEvaluator")
    print(f"  [  0] 基线 fit={loop.history[0].report.overall:.4f} "
          f"sta={loop.history[0].report.stability:.4f}")

    # 收集 fitness 历史用于每 10 代曲线
    all_fitness = [loop.history[0].report.overall]

    for gen in range(1, generations + 1):
        loop.generation = gen
        loop.tracker.next_generation()

        record = loop._step()
        loop.history.append(record)
        all_fitness.append(record.report.overall)

        # 更新压力系统
        best = max(h.report.overall for h in loop.history)
        ps = loop.pressure.update(
            gen, loop.stagnation_count, best, loop.history[-1].report.overall,
            special_triggered=(record.strategy == "special"),
        )
        loop.selector.special_prob = ps.special_probability

        # 常规输出
        r = record.report
        status = "✓" if record.accepted else ("↩" if record.rolled_back else "·")
        print(
            f"  [{gen:3d}] {status} "
            f"fit={r.overall:.4f} "
            f"sta={r.stability:.3f} "
            f"hea={r.health:.3f} "
            f"fail={r.failure_metric:.3f} "
            f"eff={r.efficiency:.3f} "
            f"str={record.strategy:10s}",
        )

        # 每 10 代输出 ASCII 曲线 + 压力状态
        if gen % 10 == 0:
            loop.snapshot_store.clean_old()
            print_ascii_curve(all_fitness, label=f"gen 0~{gen}")
            print(f"         {loop.pressure.describe()}")
            print()

    # ── 收尾 ──
    loop._save_history()
    loop.tracker.log_info("complete", f"进化完成: {generations} 代")
    loop.tracker.save()

    elapsed = time.time() - t0
    print(f"  ⏱  耗时: {elapsed:.1f}s")
    print()

    # ── 输出完整进化报告 ──
    loop.print_report()

    # ── 运行验证 ──
    results = run_validation(loop)
    print_validation(results, loop)

    # ── 退出码 ──
    if not results.get("all_passed", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
