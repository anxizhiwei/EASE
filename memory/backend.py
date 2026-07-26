"""MemoryBackend Protocol — ESAE 记忆后端协议。

从 Raven memory_engine/backend.py 提取并精简为 5 方法 ABC。
纯 stdlib，无第三方依赖。

设计要点：
- recall 通过 user_id / agent_id 区分用户记忆和智能体技能两条轨道。
- feedback 允许空实现（no-op），各后端按需支持。
- MemoryItem.metadata 是逃生舱，存放后端专有字段。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryItem:
    """一条记忆项。

    frozen=True 防止持有引用的代码意外修改他人视图。
    """

    id: str
    """记忆项唯一标识。"""

    content: str
    """LLM 可见的预渲染内容。后端负责格式化。"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """后端专有逃生舱字段。"""

    score: float = 0.0
    """适配器归一化到 [0, 1] 的相关性分数。"""

    timestamp: float = 0.0
    """创建/更新时间戳（Unix 时间戳或后端自定义值）。"""

    agent_id: str = ""
    """归属智能体 ID。"""

    user_id: str = ""
    """归属用户 ID。"""


class MemoryBackend(ABC):
    """记忆后端协议 —— 每个记忆插件实现的单一契约。

    5 个方法，按热路径排序：

    1. recall — 每轮对话由上下文引擎调用（可两次：user 和 agent 轨道）。
    2. store — 每轮对话后将切片持久化。
    3. feedback — 耗用执行信号（允许空实现）。
    4. start — 一次性初始化。
    5. stop — 清理。
    """

    @abstractmethod
    async def recall(
        self,
        *,
        user_id: str = "",
        agent_id: str = "",
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """检索匹配 query 的记忆。

        user_id 与 agent_id 二选一设置（XOR）。扁平后端（mem0 等）
        使用 user_id，对 agent_id 调用返回 []。两者均空时返回 []。

        空结果合法（无命中）；传输/鉴权错误应抛出异常。
        """
        ...

    @abstractmethod
    async def store(self, item: MemoryItem) -> None:
        """持久化一条记忆项。

        抛出传输/鉴权错误以便上层处理。
        """
        ...

    @abstractmethod
    async def feedback(self, item_id: str, rating: float) -> None:
        """注入执行信号（如已使用的 skill id）。

        空实现完全合法 —— 仅 EverOS 风格后端需要实质性工作。
        """
        ...

    async def start(self) -> None:
        """一次性/幂等初始化（建连、预热缓存、运行迁移）。

        失败应中止启动流程。
        """

    async def stop(self) -> None:
        """一次性/幂等清理。

        在部分初始化的 start 后也能安全调用。
        """


__all__ = ["MemoryItem", "MemoryBackend"]
