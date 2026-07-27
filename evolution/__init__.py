"""EASE Phase 1 — 进化引擎

核心概念：
- Genome: 系统的一组可调参数（一个"个体"）
- 变异策略：Crossover（主要）/ SnapshotRollback（安全网）/ Special（破局）
- 评测：稳定性优先，效率次要
- 可视化：每代输出 ASCII 图表
"""
