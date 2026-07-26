"""3 态 FSM — CLOSED / OPEN / HALF_OPEN。

参考 Resilience4j Circuit Breaker 状态机。
预留 5 态扩展接口（Phase 2: CALM / ALERT / ADAPT / EVOLVE / REGRESS）。
内核模块，纯 stdlib，零第三方依赖。
"""

import time
from enum import Enum
from typing import Any, Callable, Optional

# ── State definitions ──────────────────────────────────────────────────


class FSMState(str, Enum):
    """3 基本状态。"""

    CLOSED = "closed"       # 正常运行
    OPEN = "open"           # 熔断打开，拒绝请求
    HALF_OPEN = "half_open" # 试探性恢复，允许少量请求


# ── 5 态扩展预留 ──────────────────────────────────────────────────────
# Phase 2 启用，通过 register_state() 注册

_EXTENDED_STATE_MAP: dict[str, str] = {
    "CALM":    "calm",
    "ALERT":   "alert",
    "ADAPT":   "adapt",
    "EVOLVE":  "evolve",
    "REGRESS": "regress",
}


# ── Exceptions ─────────────────────────────────────────────────────────


class FSMError(Exception):
    """状态机非法操作。"""

    def __init__(self, message: str, *,
                 current: Optional[FSMState] = None,
                 target: Optional[FSMState] = None) -> None:
        self.current = current
        self.target = target
        super().__init__(message)


# ── FSM core ───────────────────────────────────────────────────────────

TransitionListener = Callable[[FSMState, FSMState, dict[str, Any]], None]


class FSM:
    """有限状态机。

    Phase 0: 3 态 (CLOSED / OPEN / HALF_OPEN)
    Phase 2: 可扩展至 5 态 (CALM / ALERT / ADAPT / EVOLVE / REGRESS)

    特性:
    - 合法转换表约束
    - 状态转换事件通知 (on_transition)
    - 状态驻留时间追踪 (dwell_time)
    """

    # 基本 3 态转换表
    _TRANSITIONS: dict[FSMState, list[FSMState]] = {
        FSMState.CLOSED:    [FSMState.OPEN],
        FSMState.OPEN:      [FSMState.HALF_OPEN],
        FSMState.HALF_OPEN: [FSMState.CLOSED, FSMState.OPEN],
    }

    def __init__(self, initial: FSMState = FSMState.CLOSED) -> None:
        self._state: FSMState = initial
        self._listeners: list[TransitionListener] = []
        self._history: list[dict[str, Any]] = []
        self._state_enter_time: float = time.monotonic()
        self._extended_states: dict[str, str] = dict(_EXTENDED_STATE_MAP)
        self._extended_transitions: dict[str, list[str]] = {}

    # ── Public API ────────────────────────────────────────────────────

    @property
    def state(self) -> FSMState:
        """当前状态。"""
        return self._state

    def transition(self, target: FSMState) -> dict[str, Any]:
        """执行到 *target* 的状态转换。

        Args:
            target: 目标状态。

        Returns:
            包含 from_state, to_state, elapsed_ms, timestamp 的事件字典。

        Raises:
            FSMError: 当转换不被允许时。
        """
        if target not in self._transitions_for(self._state):
            msg = (f"非法转换: {self._state.value} -> {target.value}"
                   if isinstance(target, FSMState)
                   else f"非法转换: {self._state.value} -> {target}")
            raise FSMError(msg, current=self._state, target=target)

        now = time.monotonic()
        elapsed = now - self._state_enter_time
        event: dict[str, Any] = {
            "from_state": self._state.value,
            "to_state": target.value,
            "elapsed_s": round(elapsed, 6),
            "timestamp": now,
        }
        self._history.append(event)

        old_state = self._state
        self._state = target
        self._state_enter_time = now

        self._notify(old_state, target, event)

        return event

    def on_transition(self, listener: TransitionListener) -> None:
        """注册转换监听器。

        Args:
            listener: 接收 (from_state, to_state, event_dict) 的回调。
        """
        self._listeners.append(listener)

    def allowed_transitions(self, state: Optional[FSMState] = None) -> list[FSMState]:
        """返回从 *state* 出发的合法目标状态列表。

        Args:
            state: 查询状态，默认当前状态。
        """
        if state is None:
            state = self._state
        return list(self._transitions_for(state))

    def dwell_time(self, state: Optional[FSMState] = None) -> float:
        """当前（或指定）状态已驻留的秒数。

        Args:
            state: 查询状态，默认当前状态。
        """
        if state is not None and state != self._state:
            # 查询非当前状态的驻留时间 → 从历史记录计算
            for i in range(len(self._history) - 1, -1, -1):
                if self._history[i]["to_state"] == state.value:
                    return self._history[i].get("elapsed_s", 0.0)
                if self._history[i]["from_state"] == state.value:
                    # 状态已退出，用最后一次驻留记录
                    return self._history[i].get("elapsed_s", 0.0)
            return 0.0
        return time.monotonic() - self._state_enter_time

    # ── 5 态扩展接口 (Phase 2) ────────────────────────────────────────

    def register_state(self, name: str, value: str,
                       allowed_targets: Optional[list[str]] = None) -> None:
        """注册一个扩展状态 (Phase 2 启用)。

        Args:
            name: 状态名 (如 "CALM", "ALERT")。
            value: 状态字符串值 (如 "calm", "alert")。
            allowed_targets: 此状态的合法转换目标名列表。
        """
        self._extended_states[name] = value
        if allowed_targets is not None:
            self._extended_transitions[name] = allowed_targets

    def history(self) -> list[dict[str, Any]]:
        """返回所有转换事件历史。"""
        return list(self._history)

    def reset(self) -> None:
        """重置到 CLOSED，清空历史。"""
        self._state = FSMState.CLOSED
        self._history.clear()
        self._state_enter_time = time.monotonic()

    # ── Internal helpers ──────────────────────────────────────────────

    def _transitions_for(self, state: FSMState) -> list[FSMState]:
        """解析给定状态的合法转换目标。"""
        if isinstance(state, FSMState):
            base = self._TRANSITIONS.get(state, [])
            ext_key = state.name
            extra = self._extended_transitions.get(ext_key, [])
            # 将扩展字符串名解析为 FSMState 或保留原值
            return base + [self._resolve_extended(e) for e in extra]
        return list(self._TRANSITIONS.get(state, []))

    def _resolve_extended(self, name: str) -> FSMState:
        """将扩展状态名解析为枚举成员（或预留占位）。"""
        if name in _EXTENDED_STATE_MAP:
            # Phase 2: 返回扩展状态 Enum (暂用 FSMState 占位)
            pass
        return FSMState(name) if name in {s.value for s in FSMState} else FSMState.CLOSED

    def _notify(self, old: FSMState, new: FSMState,
                event: dict[str, Any]) -> None:
        """通知所有已注册的监听器。"""
        for listener in self._listeners:
            try:
                listener(old, new, event)
            except Exception:
                pass  # 监听器不得中断状态机
