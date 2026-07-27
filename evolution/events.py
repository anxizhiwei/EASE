"""Key Events — 关键事件记录生成器。

独立于图表，输出结构化的关键事件时间线。
"""

from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def extract_key_events(
    history: list,
    pressure_history: Optional[list] = None,
    output_path: Optional[str] = None,
) -> dict:
    """从进化历史中提取关键事件。

    Args:
        history: GenerationRecord 列表
        pressure_history: 每代压力状态列表（可选）
        output_path: 保存路径

    Returns:
        关键事件结构体
    """
    events = []
    gens = [h.generation for h in history]
    fitness = [h.report.overall for h in history]
    stability = [h.report.stability for h in history]

    # ── 提取关键事件 ──────────────────────────────────────────
    prev_fitness = None
    best_fitness = 0.0
    best_gen = 0
    rollback_streak = 0
    accept_streak = 0

    for i, h in enumerate(history):
        gen_events = []
        fit = h.report.overall
        sta = h.report.stability

        # 最佳适应度突破
        if h.report.overall > best_fitness:
            prev_best = best_fitness
            best_fitness = h.report.overall
            best_gen = h.generation
            from_text = f"{prev_best:.4f}" if prev_best > 0 else "初始"
            gen_events.append({
                "type": "best_fitness",
                "icon": "🏆",
                "label": f"新最佳: {best_fitness:.4f}",
                "detail": f"从 {from_text} 提升至 {best_fitness:.4f}",
            })

        # 连续回退
        if h.rolled_back:
            rollback_streak += 1
            accept_streak = 0
            if rollback_streak >= 3:
                gen_events.append({
                    "type": "rollback_streak",
                    "icon": "⚠️",
                    "label": f"连续 {rollback_streak} 次回退",
                    "detail": f"stability={sta:.3f} < threshold",
                })
        else:
            rollback_streak = 0

        # 连续接受
        if h.accepted:
            accept_streak += 1
            if accept_streak >= 5:
                gen_events.append({
                    "type": "accept_streak",
                    "icon": "✅",
                    "label": f"连续 {accept_streak} 代接受",
                    "detail": f"稳定进化中",
                })
        else:
            accept_streak = 0

        # 特殊变异
        if h.strategy == "special":
            # 计算参数变化
            param_changes = []
            for j, p in enumerate(h.genome.params):
                if i > 0:
                    prev_val = history[i-1].genome.params[j]
                    if abs(p - prev_val) > 0.001:
                        change_pct = (p - prev_val) / max(abs(prev_val), 0.001) * 100
                        from evolution.genome import EASE_PARAMS
                        pname = EASE_PARAMS[j].name if j < len(EASE_PARAMS) else f"param_{j}"
                        param_changes.append(f"{pname}: {prev_val:.2f}→{p:.2f} ({change_pct:+.0f}%)")
            gen_events.append({
                "type": "special_mutation",
                "icon": "🔀",
                "label": "特殊变异触发",
                "detail": "; ".join(param_changes[:5]) if param_changes else "参数大幅跳跃",
            })

        # 回退事件增强
        if h.rolled_back and i > 0:
            # 计算参数变化
            param_diffs = []
            from evolution.genome import EASE_PARAMS
            for j, p in enumerate(h.genome.params):
                prev_val = history[i-1].genome.params[j]
                if abs(p - prev_val) > 0.001:
                    pname = EASE_PARAMS[j].name if j < len(EASE_PARAMS) else f"p{j}"
                    param_diffs.append(f"{pname}: {prev_val:.2f}→{p:.2f}")

            if not gen_events or gen_events[-1]["type"] not in ("rollback_streak",):
                gen_events.append({
                    "type": "rollback_detail",
                    "icon": "🔍",
                    "label": f"回退原因: stability={sta:.3f} < threshold",
                    "detail": "参数变化: " + "; ".join(param_diffs[:4]) if param_diffs else "参数无显著变化",
                })

        # 进步原因
        if h.accepted and h.report.overall > 0 and i > 0:
            prev_fit = history[i-1].report.overall
            if h.report.overall > prev_fit + 0.005:  # 有意义的进步
                # 找出哪几个参数变化最大
                param_impacts = []
                from evolution.genome import EASE_PARAMS
                for j, p in enumerate(h.genome.params):
                    prev_val = history[i-1].genome.params[j]
                    if abs(p - prev_val) > 0.001:
                        change_pct = (p - prev_val) / max(abs(prev_val), 0.001) * 100
                        pname = EASE_PARAMS[j].name if j < len(EASE_PARAMS) else f"p{j}"
                        direction = "↑" if change_pct > 0 else "↓"
                        param_impacts.append(f"{pname}{direction}{abs(change_pct):.0f}%")

                if param_impacts:
                    gen_events.append({
                        "type": "improvement_reason",
                        "icon": "📊",
                        "label": f"进步: {prev_fit:.4f}→{h.report.overall:.4f}",
                        "detail": ", ".join(param_impacts[:4]),
                    })

        # 压力门槛变化
        if pressure_history and i < len(pressure_history):
            ps = pressure_history[i]
            prev_ps = pressure_history[i - 1] if i > 0 else None
            if prev_ps and ps.stability_threshold != prev_ps.stability_threshold:
                gen_events.append({
                    "type": "threshold_up",
                    "icon": "🔧",
                    "label": f"压力门槛升至 {ps.stability_threshold:.2f}",
                    "detail": f"适应难度增加",
                })

        # 停滞警告（只在 5/10/15/20... 代时显示）
        if hasattr(h, 'stagnation_count') and h.stagnation_count >= 5 and h.stagnation_count % 5 == 0:
            gen_events.append({
                "type": "stagnation",
                "icon": "⏳",
                "label": f"停滞 {h.stagnation_count} 代",
                "detail": f"连续无显著改进",
            })

        # 如果这代有事件，记录
        if gen_events:
            events.append({
                "generation": h.generation,
                "fitness": round(fit, 4),
                "stability": round(sta, 4),
                "strategy": h.strategy,
                "accepted": h.accepted,
                "rolled_back": h.rolled_back,
                "events": gen_events,
            })

        prev_fitness = fit

    # ── 汇总统计 ──────────────────────────────────────────────
    summary = {
        "total_generations": len(history),
        "total_events": sum(len(e["events"]) for e in events),
        "event_types": {},
    }
    for e in events:
        for ev in e["events"]:
            t = ev["type"]
            summary["event_types"][t] = summary["event_types"].get(t, 0) + 1

    result = {
        "summary": summary,
        "events": events,
    }

    # ── 保存 ──────────────────────────────────────────────────
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        # 同时输出可读文本版本
        txt_path = path.with_suffix(".txt")
        txt_path.write_text(format_key_events_text(result))

    return result


def format_key_events_text(result: dict) -> str:
    """生成人类可读的关键事件文本。"""
    lines = []
    lines.append("=" * 72)
    lines.append("  EASE 关键事件记录")
    lines.append("=" * 72)
    lines.append(f"  总事件数: {result['summary']['total_events']}")
    lines.append("")

    for item in result["events"]:
        gen = item["generation"]
        status = "✓" if item.get("accepted") else ("↩" if item.get("rolled_back") else "·")
        lines.append(f"  ── 第 {gen} 代 [{status}] fit={item['fitness']:.4f} ──")

        for ev in item["events"]:
            lines.append(f"    {ev['icon']} {ev['label']}")
            if ev.get("detail"):
                lines.append(f"       {ev['detail']}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("  事件类型分布")
    lines.append("-" * 72)
    for t, count in sorted(result["summary"]["event_types"].items()):
        pct = count / result["summary"]["total_events"] * 100
        lines.append(f"  {t:25s}: {count:3d}  ({pct:.0f}%)")

    return "\n".join(lines)
