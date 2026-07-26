"""memory — ESAE 记忆子系统。

当前导出：MemoryBackend 协议 + MemoryItem 数据载体 + EvidenceTracker。
"""
from .backend import MemoryBackend, MemoryItem
from .feedback import EvidenceTracker, FeedbackSignal, new_evidence_id

__all__ = [
    "MemoryBackend",
    "MemoryItem",
    "EvidenceTracker",
    "FeedbackSignal",
    "new_evidence_id",
]
