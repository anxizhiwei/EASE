# EASE Phase 1 — 代码质量与架构审计报告

> 审计时间: 2026-07-26
> 审计范围: evolution/ 模块 (12 文件, ~2300 行)
> 审计方法: 逐文件阅读 + AST 扫描 + 导入/运行验证

---

## 一、核心结论

### ✅ 有条件推进 Phase 2 — 需先解决 3 个阻挡性问题

**代码本体质量不错（B+），但架构完整性和验证缺口很大。**

---

## 二、量化指标

| 指标 | 结果 | 评价 |
|------|------|------|
| 总函数数 | 65 | — |
| 空实现 (stub) | 0 (0%) | ✅ 完美 |
| bare except | 0 | ✅ 无裸except |
| TODO/FIXME | 0 | ✅ 无未完成标记 |
| 孤立模块 | 0 | ✅ 所有模块被 evolution_loop 引用 |
| 导入性 | 100% | ✅ 所有模块可正常导入 |
| 运行时路径 | 通过 | ✅ 完整2代运行正常 |
| 类型注解 | 全面 | ✅ 函数签名+返回类型完整 |
| 第三方依赖泄露 | 有 | ⚠️ matplotlib/plotly/numpy 未在 pyproject.toml 声明 |
| **测试覆盖率 (evolution)** | **0%** | ❌ **阻挡性问题** |

---

## 三、优点（代码质量好的方面）

### 1. 零 stub/零 TODO/零 bare except
- 所有 65 个函数都有真实实现体，没有 `pass` 占位
- 没有 TODO/FIXME/HACK 标记
- 所有 except 都指定了具体异常类型（除了 `daemon_runner.py` 的 1 处）

### 2. 架构模块化清晰
- 12 个文件职责分离合理：Genome 数据 → Mutation 变异 → Fitness 评估 → EvolutionLoop 编排 → Tracking/Viz/Dashboard 可视化
- 每个模块 100-400 行，没有超大文件
- 依赖方向正确：evolution_loop ← 所有其他模块

### 3. 类型注解完整
- 全量类型注解，包括复杂的 `Optional[Path]`、`list[Genome]` 等
- 使用 `from __future__ import annotations` 支持前向引用
- dataclass + frozen dataclass 使用恰当

### 4. 数据结构设计规范
- `Genome`, `FitnessReport`, `GenerationRecord` 都有 `to_dict()` / `from_dict()` 序列化
- JSONL 日志格式一致，便于事后分析
- `ParamDef` 使用 frozen dataclass 保证不变性

### 5. 错误处理干净
- 2 处 `try/except` 在 sandbox.py（subprocess timeout + JSON decode）
- 2 处 `try/except` 在 daemon_runner.py
- 没有深层嵌套的错误处理链

### 6. 自包含运行路径已验证
- 完整 2 代进化循环通过测试（导入 → 初始化 → 变异 → 评估 → 记录）
- 所有模块可独立导入

---

## 四、关键问题（按严重度排序）

### 🔴 问题 1：零测试覆盖（阻挡性）

evolution/ 模块没有任何测试文件。18 个现有测试文件（tests/ 下）全部覆盖 Phase 0 内核组件（daemon, circuit, fsm, guard, tracing, audit, feedback, memory, safety），一个也没有覆盖 evolution 模块。

**违反的铁律：**
- **AGENTS.md #11**: "kernel/* 测试覆盖率 100%" — evolution 不在 kernel/ 下，但作为 Phase 1 核心模块，这个标准应该继承
- **AGENTS.md #13**: "集成测试必须通过后方可声称 Phase 完成"

**具体缺失：**
- `test_genome.py` — 参数裁剪、距离计算、序列化反序列化
- `test_fitness.py` — SimulatedEvaluator 的各种参数组合，硬门槛验证
- `test_mutation.py` — 交叉重组、特殊变异、快照回退
- `test_evolution_loop.py` — 完整循环，接受/回退/拒绝三条路径
- `test_pressure.py` — 压力门槛随代数递增计算
- `test_sandbox.py` — 子进程运行、超时处理、清理验证

**影响：** 无法确定代码在边界条件下的行为，重构风险高。

---

### 🔴 问题 2：SimulatedEvaluator 偏置设计（架构性）

SimulatedEvaluator 采用**公式近似**而非真实系统行为评估，且公式有硬编码理想值：

```python
# fitness.py:72 — 间隔 5.0 被硬编码为"理想值"
stability_interval = 1.0 - min(1.0, abs(interval - 5.0) / 25.0)

# fitness.py:73 — relax 1.05 被硬编码为"理想值"
stability_relax = 1.0 - min(1.0, abs(relax - 1.05) / 0.95)

# fitness.py:74 — tighten 0.5 被硬编码为"理想值"
stability_tighten = 1.0 - min(1.0, abs(tighten - 0.5) / 0.4)
```

**问题：**
- 这些"理想值"就是每个参数的默认值（`default_genome_values()`）
- 意味着最优解永远在初始值附近，进化本质上是在测试随机噪声的抗性
- 适应度分数包含了 `random.gauss(0, noise)` 噪声 — 每次运行结果不同
- 进化跑出 0.976 的"最佳适应度"更多是因为随机噪声正波动，而非真正的参数优化

**这就是测试结果中"参数无显著变化"频繁出现的根本原因：** 模拟器不会对偏离默认值的参数产生真实的惩罚/奖励信号，导致选择压力不足。

---

### 🔴 问题 3：daemon_runner.py 被忽略（功能浪费/架构缺口）

`DaemonRunner` 类已经完整实现（163 行），但 `evolution_loop.py` 第 94 行硬编码了 `SimulatedEvaluator()`，从未使用过 `DaemonRunner`。

```python
# evolution_loop.py:94
self.evaluator = SimulatedEvaluator()  # 永远不是 DaemonRunner
```

**影响：**
- Phase 1 声称的"进化"从未连接到真实的 Phase 0 daemon
- 进化结果对实际系统行为没有任何影响
- 甚至 `DaemonRunner` 的代码没有被任何测试覆盖到
- 第 160 行有 `except Exception:` — 如果真用了这个类，这个宽泛的 catch 会隐藏错误

---

### 🟡 问题 4：events.py 的 dead code

`events.py` 第 159 行有一个不会执行的死分支：

```python
if hasattr(h, 'stagnation_count') and h.stagnation_count >= 5 and h.stagnation_count % 5 == 0:
```

`GenerationRecord` dataclass 没有 `stagnation_count` 字段，所以这个 `hasattr` 永远返回 False。停滞检测功能被静默禁用。

**影响：** "stagnation" 类型的关键事件永远不会被记录。

---

### 🟡 问题 5：延迟导入（代码异味）

`events.py` 和 `dashboard.py` 在函数体内部使用 `from evolution.genome import EASE_PARAMS`（共 4 处），而非文件顶部的标准导入：

```python
# events.py:94 — 函数体内部的导入
from evolution.genome import EASE_PARAMS
```

这通常暗示模块演进过程中引入了循环依赖隐患，或是重构不彻底。当前虽然没有循环依赖，但在不同 Python 路径环境下可能导入失败。

---

### 🟡 问题 6：第三方依赖未声明

`viz.py` 依赖 `matplotlib` 和 `numpy`，`dashboard.py` 依赖 `plotly` 和 `numpy`，但 `pyproject.toml` 只声明了 `stdlib only`：

```toml
dependencies = []  # L3 core = stdlib only
```

当前环境恰好有这些库（因 Hermes 全局安装），但在全新环境中会失败。需要至少声明为 optional-dependencies。

---

### 🟡 问题 7：DockerSandboxRunner 未测试，构建脚本缺失

`sandbox.py` 第 226-297 行的 `DockerSandboxRunner` 实现了完整的 Docker 隔离逻辑，但：
- 没有构建 Dockerfile
- 没有构建脚本
- `use_docker = False` 硬编码在第 177 行
- 没有任何测试

这是"写了但永远用不上"的代码，增加了模块的认知复杂度。

---

### 🟡 问题 8：fitness.py 和 sandbox.py 的测评不一致

存在 **两套独立的评测逻辑**：
1. `fitness.py` 的 `SimulatedEvaluator` — 用公式计算（4 个维度加权）
2. `sandbox.py` 的内联 `_SANDBOX_SCRIPT` — 用 tick 模拟器计算

它们的稳定性门槛不同：fitness.py 用 0.5，sandbox_script 用 0.6。
但 `evolution_loop.py` 始终用的是 fitness.py 的 `evaluate_fitness()`，sandbox.py 完全不走 fitness.py 逻辑。

这意味着未来如果要切换到 Docker 隔离模式，评测结果会与当前不一致。

---

## 五、架构评估

### 架构图（数据流）

```
Genome (params)
    │
    ▼
MutationSelector ───→ 变异策略 (crossover / special)
    │
    ▼
SnapshotStore ────→ 快照 → [回退]
    │
    ▼
SimulatedEvaluator ──→ FitnessReport
    │
    ▼
AdaptivePressure ──→ 动态门槛
    │
    ▼
EvolutionLoop ──→ 接受/回退/拒绝决策
    │
    ▼
EvolutionTracker ──→ JSONL 日志
Viz/Dashboard ──→ PNG / HTML 可视化
```

### 架构优点
- **分层合理**：数据流单向，无循环依赖
- **关注点分离**：变异策略、压力系统、评测、跟踪、可视化各自独立
- **可插拔评估器**：`SimulatedEvaluator` 和 `DockerSandboxRunner` 实现了统一接口 `evaluate(genome) -> FitnessReport`
- **快照安全网**：闪照→变异→回退机制提供基本的安全性保障
- **压力系统设计**：`AdaptivePressure` 的系统性设计是一个亮点，多维度压力调节

### 架构缺口
1. **闭环未闭合**：进化结果从未应用到实际系统，系统永远感知不到自己的进化
2. **可插拔但从未插拔**：虽然接口设计支持不同的评估器，但 `EvolutionLoop` 硬编码了 `SimulatedEvaluator`，没有公开的 setter 或构造参数让调用者替换
3. **DaemonRunner 断连**：Phase 0 的 daemon 和 Phase 1 的进化引擎之间没有任何实际连接

---

## 六、Phase 2 推进条件

### 必须修复（阻挡性）
| # | 问题 | 修复建议 | 预计工时 |
|---|------|----------|----------|
| 1 | 零测试覆盖 | 为 evolution 模块添加 pytest 测试（至少覆盖 genome, fitness, mutation, pressure, evolution_loop 的核心路径） | 4-6h |
| 2 | 模拟器偏置 | 重构 SimulatedEvaluator 使用无偏置公式，或实现 DaemonRunner 的真实连接 | 3-4h |
| 3 | daemon_runner 断连 | 在 EvolutionLoop 构造参数中支持 evaluator 注入，或者默认使用 DaemonRunner 跑少代 | 2h |

### 建议修复（非阻塞但推荐）
| # | 问题 | 修复建议 | 预计工时 |
|---|------|----------|----------|
| 4 | events.py dead code | 删除 stagnate_count 死分支，或将 stagnation_count 添加到 GenerationRecord | 0.5h |
| 5 | 延迟导入 | 将函数体内的 import 移到文件顶部 | 0.5h |
| 6 | 依赖声明 | 在 pyproject.toml 添加 [project.optional-dependencies] viz = ["matplotlib", "numpy"] 等 | 0.5h |
| 7 | DockerSandbox 无构建脚本 | 添加 Dockerfile + ensure_docker_image() | 1h |
| 8 | 两套评测逻辑 | 统一使用 sandbox.py 的内核，删除 fitness.py 的独立 SimulatedEvaluator | 1-2h |

---

## 七、最终建议

**Phase 2 可以有条件推进，前提是先修复问题 #1（测试覆盖）和 #2（模拟器偏置）。**

如果直接推进 Phase 2 而不解决这两个问题，会面临：
1. Phase 2 的新功能无法通过测试验证 — 每次修改都需要手动运行 100 代来确认
2. 模拟器偏置会让更复杂的参数空间搜索收敛到错误方向
3. Phase 0 和 Phase 1 的割裂状态持续扩大，增加后期整合成本

**建议分步走：**
1. **Phase 1.5（2-3天）**：修复上述 8 个问题，添加测试覆盖，将 daemon_runner 连入进化循环
2. **Phase 2（正式）**：在稳固的基础上继续
