"""Visualization — 进化可视化（matplotlib 专业图表）。

生成多面板图表，包含：
- 适应度进化曲线（折线 + 关键事件标记）
- 稳定性趋势（折线 + 压力门槛线）
- 接受/回退统计（堆叠柱状图）
- 指标分解（堆叠面积图）
- 关键统计卡片

输出：PNG 图片，可通过 QQ MEDIA 发送。
"""

from __future__ import annotations
import io
import math
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # 无头模式
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from .genome import Genome
from .fitness import FitnessReport


# 中文字体配置
plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Noto Sans CJK SC",
                                    "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def render_evolution_chart(
    history: list,
    pressure_history: Optional[list] = None,
    output_path: Optional[str] = None,
    title: str = "EASE Phase 1 — 进化报告",
) -> bytes:
    """生成进化多面板图表。

    Args:
        history: GenerationRecord 列表
        pressure_history: 每代的压力状态列表（可选）
        output_path: 保存路径，None 则返回 bytes
        title: 图表标题

    Returns:
        PNG 图片的 bytes（output_path 为 None 时）
    """
    if not history:
        return b""

    # 提取数据
    gens = [h.generation for h in history]
    fitness = [h.report.overall for h in history]
    stability = [h.report.stability for h in history]
    health = [h.report.health for h in history]
    fail_metric = [h.report.failure_metric for h in history]
    efficiency = [h.report.efficiency for h in history]
    accepted = [h.accepted for h in history]
    rolled_back = [h.rolled_back for h in history]
    strategies = [h.strategy for h in history]
    timestamps = [getattr(h, 'timestamp', 0) for h in history]

    # 标记关键事件
    best_idx = int(np.argmax(fitness))
    special_idxs = [i for i, s in enumerate(strategies) if s == "special"]

    # 每 10 代的压力门槛
    pressure_thresholds = None
    if pressure_history:
        pressure_thresholds = [p.stability_threshold for p in pressure_history]

    fig = plt.figure(figsize=(20, 14))
    gs = fig.add_gridspec(4, 3, height_ratios=[1.2, 1, 1, 0.8],
                          hspace=0.30, wspace=0.25)

    # ── 统计卡片 ──────────────────────────────────────────────
    total = len(gens)
    accept_count = sum(accepted)
    rollback_count = sum(rolled_back)
    best_fit = max(fitness)
    best_gen = gens[best_idx] if best_idx < len(gens) else 0
    current_fit = fitness[-1] if fitness else 0
    improve = ((best_fit / fitness[0]) - 1) * 100 if fitness and fitness[0] > 0 else 0

    stats = [
        ("总代数", total, "#4A90D9"),
        ("接受", f"{accept_count} ({accept_count/max(total,1)*100:.0f}%)", "#27AE60"),
        ("回退", f"{rollback_count} ({rollback_count/max(total,1)*100:.0f}%)", "#E74C3C"),
        ("最佳适应度", f"{best_fit:.4f} (第{best_gen}代)", "#F39C12"),
        ("当前适应度", f"{current_fit:.4f}", "#8E44AD"),
        ("提升幅度", f"+{improve:.1f}%", "#2C3E50"),
    ]

    ax_stats = fig.add_subplot(gs[0, :])
    ax_stats.axis("off")
    for i, (label, value, color) in enumerate(stats):
        col = i % 3
        row = i // 3
        x = 0.02 + col * 0.33
        y = 0.5 - row * 0.45
        ax_stats.text(x, y + 0.2, label, fontsize=10, color="#666",
                      transform=ax_stats.transAxes, va="bottom")
        ax_stats.text(x, y - 0.1, str(value), fontsize=18, fontweight="bold",
                      color=color, transform=ax_stats.transAxes, va="top")

    # ── ① 适应度曲线 ────────────────────────────────────────
    ax1 = fig.add_subplot(gs[1, :])
    ax1.plot(gens, fitness, color="#3498DB", linewidth=1.5, alpha=0.7, label="适应度")
    ax1.fill_between(gens, fitness, alpha=0.1, color="#3498DB")

    # 最佳点
    ax1.scatter([best_gen], [best_fit], color="#F39C12", s=120, zorder=5,
                marker="*", label=f"最佳: {best_fit:.4f}")

    # 特殊变异事件
    if special_idxs:
        special_gens = [gens[i] for i in special_idxs]
        special_fits = [fitness[i] for i in special_idxs]
        ax1.scatter(special_gens, special_fits, color="#E74C3C", s=60,
                    marker="^", alpha=0.8, label="特殊变异", zorder=4)

    # 回退事件
    rollback_gens = [gens[i] for i in range(len(gens)) if rolled_back[i]]
    rollback_fits = [fitness[i] for i in range(len(gens)) if rolled_back[i]]
    if rollback_gens:
        ax1.scatter(rollback_gens, rollback_fits, color="#E74C3C", s=25,
                    marker="x", alpha=0.5, label=f"回退 ({len(rollback_gens)}次)")

    ax1.set_ylabel("适应度", fontsize=12)
    ax1.set_title("适应度进化曲线", fontsize=14, fontweight="bold", pad=10)
    ax1.legend(loc="upper left", fontsize=9, framealpha=0.7)
    ax1.set_ylim(min(0, min(fitness) - 0.05), min(1.05, max(fitness) + 0.05))
    ax1.grid(True, alpha=0.3)
    ax1.set_xlabel("代数", fontsize=11)

    # ── ② 稳定性 + 压力门槛 ────────────────────────────────
    ax2 = fig.add_subplot(gs[2, 0])
    ax2.plot(gens, stability, color="#27AE60", linewidth=1.5, label="稳定性")

    # 压力门槛线
    if pressure_thresholds:
        ax2.plot(gens, pressure_thresholds, color="#E74C3C", linewidth=2,
                 linestyle="--", alpha=0.7, label="压力门槛", zorder=3)
        ax2.fill_between(gens, pressure_thresholds, alpha=0.08, color="#E74C3C")

    ax2.axhline(y=0.6, color="#95A5A6", linewidth=0.8, linestyle=":", alpha=0.5)
    ax2.set_ylabel("稳定性", fontsize=12)
    ax2.set_title("稳定性 vs 压力门槛", fontsize=14, fontweight="bold", pad=10)
    ax2.legend(loc="lower right", fontsize=9, framealpha=0.7)
    ax2.set_ylim(min(-0.2, min(stability) - 0.05), 1.05)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel("代数", fontsize=11)

    # ── ③ 指标分解（堆叠面积） ──────────────────────────────
    ax3 = fig.add_subplot(gs[2, 1])
    ax3.stackplot(gens, health, fail_metric, efficiency,
                  labels=["健康度", "成功率", "效率"],
                  colors=["#2ECC71", "#3498DB", "#9B59B6"],
                  alpha=0.7)
    ax3.set_title("指标分解", fontsize=14, fontweight="bold", pad=10)
    ax3.legend(loc="upper right", fontsize=8, framealpha=0.7)
    ax3.set_ylim(0, 1.05)
    ax3.grid(True, alpha=0.3)
    ax3.set_xlabel("代数", fontsize=11)

    # ── ④ 接受/回退柱状图（每 10 代聚合） ──────────────────
    ax4 = fig.add_subplot(gs[2, 2])

    # 按 10 代分组
    bin_size = 10
    num_bins = max(1, (max(gens) + bin_size - 1) // bin_size)
    bin_labels = [f"{i*bin_size}-{(i+1)*bin_size-1}" for i in range(num_bins)]
    bin_accept = []
    bin_rollback = []

    for i in range(num_bins):
        start = i * bin_size
        end = min((i + 1) * bin_size, len(gens))
        bin_gens = gens[start:end]
        if not bin_gens:
            bin_accept.append(0)
            bin_rollback.append(0)
            continue
        bin_accept.append(sum(1 for g in bin_gens
                              if accepted[gens.index(g)]))
        bin_rollback.append(sum(1 for g in bin_gens
                                if rolled_back[gens.index(g)]))

    x = np.arange(len(bin_labels))
    width = 0.35
    bars1 = ax4.bar(x - width / 2, bin_accept, width, label="接受",
                    color="#27AE60", alpha=0.8)
    bars2 = ax4.bar(x + width / 2, bin_rollback, width, label="回退",
                    color="#E74C3C", alpha=0.8)

    ax4.set_title("接受 vs 回退 (每10代)", fontsize=14, fontweight="bold", pad=10)
    ax4.set_xticks(x)
    ax4.set_xticklabels(bin_labels, fontsize=7, rotation=30)
    ax4.legend(fontsize=9, framealpha=0.7)
    ax4.set_ylabel("次数", fontsize=11)
    ax4.grid(True, alpha=0.3, axis="y")

    # ── ⑥ 关键事件时间线 ──────────────────────────────────
    ax6 = fig.add_subplot(gs[3, :])
    ax6.axis("off")
    ax6.set_title("关键事件时间线（精选）", fontsize=13, fontweight="bold", pad=5)

    # 从 history 提取关键事件
    timeline_events = []
    for i, h in enumerate(history):
        ev_type = None
        if h.rolled_back:
            ev_type = ("回退", "#E74C3C", "x")
        elif h.strategy == "special":
            ev_type = ("特殊变异", "#9B59B6", "^")
        if ev_type and i > 0:
            timeline_events.append((h.generation, ev_type[0], ev_type[1], ev_type[2]))

    # 画时间线
    if timeline_events:
        y_pos = 0.8
        step = max(1, len(timeline_events) // 20 + 1)
        shown = timeline_events[::step][:20]

        ax6.plot([0, 1], [y_pos, y_pos], color="#BDC3C7", linewidth=1,
                 transform=ax6.transAxes)
        for gen, label, color, _ in shown:
            x = gen / max(gens) if max(gens) > 0 else 0
            ax6.scatter(x, y_pos, color=color, s=40, zorder=5,
                        transform=ax6.transAxes)
            ax6.text(x, y_pos - 0.08, str(gen), fontsize=6, ha="center",
                     color=color, transform=ax6.transAxes)
            ax6.text(x, y_pos + 0.05, label, fontsize=5, ha="center",
                     color=color, rotation=45, transform=ax6.transAxes)

        ax6.text(1.01, y_pos, f"共 {len(timeline_events)} 个事件",
                 fontsize=8, color="#7F8C8D", va="center",
                 transform=ax6.transAxes)

    if pressure_history:
        last_p = pressure_history[-1]
        items = [
            ("稳定性门槛", last_p.stability_threshold, 0.75, 0.6),
            ("效率权重", last_p.efficiency_weight, 0.25, 0.1),
            ("综合压力", last_p.overall_pressure, 1.0, 0.0),
        ]
        for i, (name, val, max_v, min_v) in enumerate(items):
            ax = fig.add_axes([0.08 + i * 0.30, 0.03, 0.25, 0.06])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")

            # 进度条背景
            ax.barh(0.5, 1, height=0.4, color="#ECF0F1", transform=ax.transData)
            # 进度条
            ratio = (val - min_v) / (max_v - min_v)
            bar_color = "#27AE60" if ratio < 0.5 else ("#F39C12" if ratio < 0.75 else "#E74C3C")
            ax.barh(0.5, ratio, height=0.4, color=bar_color, transform=ax.transData)
            ax.text(0.5, -0.3, f"{name}: {val:.3f}", ha="center", va="top",
                    fontsize=10, transform=ax.transAxes)

    # 保存
    plt.suptitle(title, fontsize=16, fontweight="bold", y=0.98)

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        return Path(output_path).read_bytes()
    else:
        buf = io.BytesIO()
        fig.savefig(buf, dpi=150, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        return buf.getvalue()
