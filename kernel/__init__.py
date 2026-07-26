"""ESAE Kernel — 内核模块。

Phase 0:
- FSM: 3 态有限状态机 (CLOSED / OPEN / HALF_OPEN)
- CircuitBreaker: 基于滑动窗口的熔断器
- AuditLog: append-only JSONL 审计日志
- SafetyGuard: 安全门 — 坐标/按键/变异/参数检查
"""

from .fsm import FSM, FSMState, FSMError
from .circuit import CircuitBreaker, CircuitBreakerError
from .audit import AuditLog, AuditError, ESAEError
from .guard import SafetyGuard, GuardError

__all__ = [
    "FSM", "FSMState", "FSMError",
    "CircuitBreaker", "CircuitBreakerError",
    "AuditLog", "AuditError",
    "SafetyGuard", "GuardError",
    "ESAEError",
]
