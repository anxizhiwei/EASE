"""Dashboard — 交互式进化仪表盘（Plotly）。

生成 HTML 文件，可在浏览器中交互查看。
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np


def render_dashboard(
    history: list,
    pressure_history: Optional[list] = None,
    output_path: str = "evolution_dashboard.html",
) -> str:
    if not history:
        return ""

    # 数据
    gens = [h.generation for h in history]
    fitness = [h.report.overall for h in history]
    stability = [h.report.stability for h in history]
    health = [h.report.health for h in history]
    fail_metric = [h.report.failure_metric for h in history]
    efficiency = [h.report.efficiency for h in history]
    accepted = [h.accepted for h in history]
    rolled = [h.rolled_back for h in history]
    strategies = [h.strategy for h in history]

    best_idx = int(np.argmax(fitness))
    best_fit = max(fitness)
    best_gen = gens[best_idx]
    total = len(gens)
    accept_count = sum(accepted)
    roll_count = sum(rolled)
    improve = ((best_fit / fitness[0]) - 1) * 100 if fitness[0] > 0 else 0

    rollback_gens = [gens[i] for i in range(len(gens)) if rolled[i]]
    rollback_fits = [fitness[i] for i in range(len(gens)) if rolled[i]]
    special_gens = [gens[i] for i, s in enumerate(strategies) if s == "special"]
    special_fits = [fitness[i] for i, s in enumerate(strategies) if s == "special"]

    # 创建子图
    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=(
            "适应度进化曲线", "参数热力图",
            "稳定性 vs 压力门槛", "指标分解",
            "接受/回退 (每10代)", "策略分布",
            "关键事件时间线", "",
        ),
        row_heights=[0.28, 0.22, 0.18, 0.20],
        vertical_spacing=0.08,
        horizontal_spacing=0.06,
    )

    # ── ROW 1 COL 1: 适应度曲线 ──────────────────────────────
    fig.add_trace(go.Scatter(x=gens, y=fitness, mode="lines+markers",
        name="适应度", line={"color": "#3498DB", "width": 2},
        marker={"size": 4},
        hovertemplate="<b>第%{x}代</b><br>适应度: %{y:.4f}<br>稳定性: %{customdata[0]:.3f}<extra></extra>",
        customdata=list(zip(stability))), row=1, col=1)

    fig.add_trace(go.Scatter(x=[best_gen], y=[best_fit], mode="markers+text",
        name=f"最佳: {best_fit:.4f}",
        marker={"color": "#F39C12", "size": 16, "symbol": "star"},
        text=[f"★{best_fit:.4f}"], textposition="top center",
        hovertemplate=f"最佳: 第{best_gen}代, {best_fit:.4f}<extra></extra>"), row=1, col=1)

    if rollback_gens:
        fig.add_trace(go.Scatter(x=rollback_gens, y=rollback_fits,
            mode="markers", name=f"回退({roll_count})",
            marker={"color": "#E74C3C", "size": 7, "symbol": "x"},
            hovertemplate="第%{x}代 回退<extra></extra>"), row=1, col=1)
    if special_gens:
        fig.add_trace(go.Scatter(x=special_gens, y=special_fits,
            mode="markers", name=f"特殊变异({len(special_gens)})",
            marker={"color": "#9B59B6", "size": 9, "symbol": "triangle-up"},
            hovertemplate="第%{x}代 特殊变异<extra></extra>"), row=1, col=1)

    fig.update_xaxes(title="代数", row=1, col=1)
    fig.update_yaxes(title="适应度", row=1, col=1)

    # ── ROW 1 COL 2: 参数热力图 ──────────────────────────────
    from evolution.genome import EASE_PARAMS as ep
    param_names = [p.name for p in ep]
    param_matrix = []
    for h in history:
        row_data = []
        for j, p in enumerate(h.genome.params):
            if j < len(ep):
                norm = (p - ep[j].min_val) / (ep[j].max_val - ep[j].min_val)
                row_data.append(round(norm, 3))
        param_matrix.append(row_data)
    param_matrix_t = list(zip(*param_matrix))

    fig.add_trace(go.Heatmap(z=param_matrix_t, y=param_names[:len(param_matrix_t)],
        x=gens, colorscale="Viridis", showscale=True,
        hovertemplate="%{y}<br>代%{x}<br>归一化: %{z:.2f}<extra></extra>"), row=1, col=2)

    # ── ROW 2 COL 1: 稳定性 vs 压力门槛 ──────────────────────
    fig.add_trace(go.Scatter(x=gens, y=stability, mode="lines",
        name="稳定性", line={"color": "#27AE60", "width": 2},
        fill="tozeroy", fillcolor="rgba(39,174,96,0.1)",
        hovertemplate="第%{x}代 稳定性: %{y:.3f}<extra></extra>"), row=2, col=1)

    if pressure_history:
        thr = [p.stability_threshold for p in pressure_history]
        fig.add_trace(go.Scatter(x=gens, y=thr, mode="lines",
            name="压力门槛", line={"color": "#E74C3C", "width": 2, "dash": "dash"},
            hovertemplate="第%{x}代 门槛: %{y:.3f}<extra></extra>"), row=2, col=1)

    fig.add_hline(y=0.6, line_color="#95A5A6", line_width=1, line_dash="dot",
                  annotation_text="基线", row=2, col=1)
    fig.update_yaxes(title="稳定性", row=2, col=1)

    # ── ROW 2 COL 2: 指标分解 ──────────────────────────────
    fig.add_trace(go.Scatter(x=gens, y=health, mode="lines", name="健康度",
        line={"color": "#2ECC71", "width": 1}, stackgroup="one"), row=2, col=2)
    fig.add_trace(go.Scatter(x=gens, y=fail_metric, mode="lines", name="成功率",
        line={"color": "#3498DB", "width": 1}, stackgroup="one"), row=2, col=2)
    fig.add_trace(go.Scatter(x=gens, y=efficiency, mode="lines", name="效率",
        line={"color": "#9B59B6", "width": 1}, stackgroup="one"), row=2, col=2)
    fig.update_yaxes(range=[0, 1.05], row=2, col=2)

    # ── ROW 3 COL 1: 接受/回退柱状图 ─────────────────────────
    bin_size = max(1, total // 10)
    num_bins = (total + bin_size - 1) // bin_size
    bin_acc, bin_rol, bin_lbl = [], [], []
    for i in range(num_bins):
        s = i * bin_size
        e = min((i + 1) * bin_size, total)
        seg = gens[s:e]
        if seg:
            bin_lbl.append(f"{seg[0]}-{seg[-1]}")
            bin_acc.append(sum(1 for g in seg if accepted[gens.index(g)]))
            bin_rol.append(sum(1 for g in seg if rolled[gens.index(g)]))

    fig.add_trace(go.Bar(x=bin_lbl, y=bin_acc, name="接受",
        marker_color="#27AE60"), row=3, col=1)
    fig.add_trace(go.Bar(x=bin_lbl, y=bin_rol, name="回退",
        marker_color="#E74C3C"), row=3, col=1)
    fig.update_xaxes(tickangle=30, row=3, col=1)

    # ── ROW 3 COL 2: 策略分布（条形图） ─────────────────
    sc = {}
    for s in strategies:
        if s: sc[s] = sc.get(s, 0) + 1
    fig.add_trace(go.Bar(x=list(sc.keys()), y=list(sc.values()),
        name="策略", marker_color=["#3498DB", "#9B59B6"],
        hovertemplate="%{x}: %{y}代<extra></extra>"), row=3, col=2)

    # ── ROW 4: 关键事件时间线 ────────────────────────────────
    ev_gens, ev_txts, ev_cols = [], [], []
    for i, h in enumerate(history):
        if h.rolled_back and i > 0:
            ev_gens.append(h.generation); ev_txts.append(f"回退"); ev_cols.append("#E74C3C")
        elif h.strategy == "special":
            ev_gens.append(h.generation); ev_txts.append("特殊变异"); ev_cols.append("#9B59B6")

    if ev_gens:
        fig.add_trace(go.Scatter(x=ev_gens, y=[1]*len(ev_gens), mode="markers+text",
            name="事件", marker={"color": ev_cols, "size": 10, "symbol": "x"},
            text=[f"G{g}" for g in ev_gens], textposition="top center",
            textfont={"size": 9},
            hovertemplate="第%{x}代 %{text}<extra></extra>"), row=4, col=1)
    fig.update_yaxes(visible=False, row=4, col=1)

    # ── 布局 ──────────────────────────────────────────────────
    # KPI 注解
    kpi = (
        f"<b>总代数</b>: {total} "
        f"<b>接受</b>: <span style='color:#27AE60'>{accept_count}({accept_count/total*100:.0f}%)</span> "
        f"<b>回退</b>: <span style='color:#E74C3C'>{roll_count}({roll_count/total*100:.0f}%)</span> "
        f"<b>最佳</b>: <span style='color:#F39C12'>{best_fit:.4f}</span>(第{best_gen}代) "
        f"<b>当前</b>: <span style='color:#8E44AD'>{fitness[-1]:.4f}</span> "
        f"<b>提升</b>: <span style='color:#2C3E50'>+{improve:.1f}%</span>"
    )
    fig.add_annotation(x=0.5, y=1.12, xref="paper", yref="paper",
        text=kpi, showarrow=False, font={"size": 13},
        bgcolor="rgba(44,62,80,0.08)", bordercolor="#2C3E50",
        borderwidth=1, borderpad=8)

    fig.update_layout(
        title={"text": f"EASE Phase 1 — 进化仪表盘 ({total}代)",
               "font": {"size": 22}, "x": 0.5},
        template="plotly_dark", height=1500,
        hovermode="x unified",
        legend={"orientation": "h", "y": -0.01, "font": {"size": 10}},
        margin={"l": 40, "r": 40, "t": 90, "b": 40},
    )

    html = fig.to_html(include_plotlyjs="cdn", full_html=True,
        config={"scrollZoom": True, "displayModeBar": True})

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")
        print(f"  ✅ 仪表盘已保存: {output_path}")

    return html
