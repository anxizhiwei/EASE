"""熔断器 — 基于滑动窗口的故障检测。

参考 Resilience4j 参数调优 + ESAE V1 计划的 MoA 评审结论。
内核模块，纯 stdlib，零第三方依赖。

双模式：
- COUNT_BASED: 固定大小的环形缓冲，统计最近 N 次调用
- (Phase 2 预留 TIME_BASED 扩展点)

慢调用检测：超过 slow_call_threshold_seconds 的调用计为慢调用，
慢调用率 >= slow_call_rate_threshold 时触发熔断。
"""

import time
from collections import deque
from typing import Any, Optional

from .fsm import FSM, FSMState


class CircuitBreakerError(Exception):
    """熔断器拒绝请求（OPEN 状态）。"""

    def __init__(self, message: str = "circuit breaker is open",
                 state: Optional[FSMState] = None) -> None:
        self.state = state
        super().__init__(message)


class CircuitBreaker:
    """滑动窗口熔断器。

    Args:
        window_size: 滑动窗口大小（COUNT_BASED 模式最近 N 次调用）。
        min_samples: 触发阈值计算所需的最小样本数。
        failure_threshold: 失败率阈值（0.0 - 1.0），超过则熔断。
        slow_call_threshold_seconds: 慢调用判定阈值（秒）。
        slow_call_rate_threshold: 慢调用率阈值（0.0 - 1.0），超过则熔断。
        half_open_max_permits: HALF_OPEN 状态允许的最大试探请求数。
        wait_duration_seconds: OPEN → HALF_OPEN 等待时间（秒）。
    """

    def __init__(
        self,
        window_size: int = 20,
        min_samples: int = 5,
        failure_threshold: float = 0.5,
        slow_call_threshold_seconds: float = 30.0,
        slow_call_rate_threshold: float = 0.8,
        half_open_max_permits: int = 3,
        wait_duration_seconds: float = 30.0,
    ) -> None:
        # 参数校验
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        if not 0.0 < failure_threshold <= 1.0:
            raise ValueError("failure_threshold must be in (0, 1]")
        if not 0.0 < slow_call_rate_threshold <= 1.0:
            raise ValueError("slow_call_rate_threshold must be in (0, 1]")
        if min_samples > window_size:
            raise ValueError("min_samples must not exceed window_size")

        self._window_size: int = window_size
        self._min_samples: int = min_samples
        self._failure_threshold: float = failure_threshold
        self._slow_call_threshold: float = slow_call_threshold_seconds
        self._slow_call_rate_threshold: float = slow_call_rate_threshold
        self._half_open_max_permits: int = half_open_max_permits
        self._wait_duration: float = wait_duration_seconds

        # 内部状态机
        self._fsm: FSM = FSM(FSMState.CLOSED)

        # 滑动窗口 (环形缓冲)
        self._calls: deque[dict[str, Any]] = deque(maxlen=window_size)

        # HALF_OPEN 许可计数
        self._half_open_permits_used: int = 0

    # ── Public API ────────────────────────────────────────────────────

    @property
    def state(self) -> FSMState:
        """当前熔断器状态。"""
        return self._fsm.state

    def is_call_permitted(self) -> bool:
        """判断当前调用是否允许通过。

        Returns:
            True: 调用允许。
            False: 调用被熔断器拒绝。

        副作用：当 OPEN 状态等待期满后，自动过渡至 HALF_OPEN。
        """
        current = self._fsm.state

        if current == FSMState.CLOSED:
            return True

        if current == FSMState.OPEN:
            # 检查等待期是否已过 → 转入 HALF_OPEN
            if self._fsm.dwell_time() >= self._wait_duration:
                self._fsm.transition(FSMState.HALF_OPEN)
                self._half_open_permits_used = 1  # 本次调用消耗一个许可
                return True
            return False

        # HALF_OPEN: 检查是否还有剩余试探许可
        if current == FSMState.HALF_OPEN:
            if self._half_open_permits_used < self._half_open_max_permits:
                self._half_open_permits_used += 1
                return True
            return False

        return True  # fallback

    def record_success(self, duration: float = 0.0) -> None:
        """记录一次成功调用。

        Args:
            duration: 调用耗时（秒），用于慢调用检测。
        """
        self._add_call(failed=False, slow=duration > self._slow_call_threshold,
                       duration=duration)

        # HALF_OPEN 下成功 → 试探性恢复检查
        if self._fsm.state == FSMState.HALF_OPEN:
            if self._all_permitted_succeeded():
                self._fsm.transition(FSMState.CLOSED)
                self._half_open_permits_used = 0

    def record_failure(self, duration: float = 0.0) -> None:
        """记录一次失败调用。

        Args:
            duration: 调用耗时（秒）。
        """
        self._add_call(failed=True, slow=duration > self._slow_call_threshold,
                       duration=duration)
        self._evaluate()

    def record_slow_call(self, duration: float) -> None:
        """记录一次慢调用（无论基础失败状态如何）。

        慢调用同时计为失败调用。

        Args:
            duration: 调用耗时（秒）。
        """
        self._add_call(failed=True, slow=True, duration=duration)
        self._evaluate()

    # ── Metrics ───────────────────────────────────────────────────────

    def metrics(self) -> dict[str, Any]:
        """返回熔断器当前指标快照。"""
        total = len(self._calls)
        failures = sum(1 for c in self._calls if c["failed"])
        slow = sum(1 for c in self._calls if c["slow"])

        return {
            "state": self._fsm.state.value,
            "window_size": self._window_size,
            "total_calls_in_window": total,
            "failure_count": failures,
            "failure_rate": failures / total if total > 0 else 0.0,
            "slow_count": slow,
            "slow_rate": slow / total if total > 0 else 0.0,
            "half_open_permits_used": self._half_open_permits_used,
            "half_open_max_permits": self._half_open_max_permits,
            "dwell_time_s": round(self._fsm.dwell_time(), 6),
            "is_call_permitted": self.is_call_permitted(),
        }

    def reset(self) -> None:
        """重置熔断器到初始 (CLOSED) 状态，清空滑动窗口。"""
        self._fsm.reset()
        self._calls.clear()
        self._half_open_permits_used = 0

    # ── Internal ──────────────────────────────────────────────────────

    def _add_call(self, *, failed: bool, slow: bool, duration: float) -> None:
        """向滑动窗口添加一条调用记录。"""
        self._calls.append({
            "failed": failed,
            "slow": slow,
            "duration": duration,
            "timestamp": time.time(),
        })

    def _evaluate(self) -> None:
        """检查阈值是否达到，必要时触发状态转换。"""
        if len(self._calls) < self._min_samples:
            return

        current = self._fsm.state

        if current == FSMState.CLOSED:
            failure_rate = sum(1 for c in self._calls if c["failed"]) / len(self._calls)
            slow_rate = sum(1 for c in self._calls if c["slow"]) / len(self._calls)

            if failure_rate >= self._failure_threshold or slow_rate >= self._slow_call_rate_threshold:
                self._fsm.transition(FSMState.OPEN)

        elif current == FSMState.HALF_OPEN:
            # HALF_OPEN 下任何失败立即回到 OPEN
            if any(c["failed"] for c in self._calls):
                self._fsm.transition(FSMState.OPEN)
                self._half_open_permits_used = 0

    def _all_permitted_succeeded(self) -> bool:
        """检查 HALF_OPEN 期间所有试探调用是否全部成功。"""
        # 检查最近 half_open_max_permits 条记录是否全部成功
        recent = list(self._calls)[-self._half_open_max_permits:]
        return len(recent) > 0 and all(not c["failed"] for c in recent)
