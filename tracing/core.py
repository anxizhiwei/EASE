"""Tracing 基础设施 — 结构化追踪。

从 Raven tracing/trace.py + tracing/store.py 提取适配。

参考：Raven 的 tracing 设计被评为 7 个项目中最佳（混元 HY3 评价）。
"""

import functools
import hashlib
import json
import time
import uuid
from contextvars import ContextVar
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

# ── 7 类 span ──────────────────────────────────────────────────────────
VALID_SPAN_TYPES = frozenset({
    "session", "model", "tool", "subagent", "skill", "memory", "plugin",
})

# ── 全局状态 ───────────────────────────────────────────────────────────
_enabled: bool = True
_current_span: ContextVar[Optional["Span"]] = ContextVar("current_span", default=None)


# ═══════════════════════════════════════════════════════════════════════
# Span
# ═══════════════════════════════════════════════════════════════════════
class Span:
    """追踪跨度。

    自动嵌套：在 span 内创建的新 span 自动成为其子 span。
    支持 context manager 和装饰器两种使用方式。
    """

    __slots__ = (
        "span_id", "parent_id", "_parent", "_store", "name", "type", "attributes",
        "start_time", "end_time", "status", "error", "children",
        "_token",
    )

    def __init__(
        self,
        name: str,
        span_type: str = "tool",
        attributes: Optional[dict] = None,
        store: Optional["TraceStore"] = None,
    ) -> None:
        if span_type not in VALID_SPAN_TYPES:
            raise ValueError(
                f"Invalid span_type={span_type!r}; "
                f"valid: {sorted(VALID_SPAN_TYPES)}"
            )
        parent = _current_span.get()
        self._parent = parent  # capture parent ref for __exit__ child registration
        self._store = store  # optional custom store (defaults to global tracer)
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_id = parent.span_id if parent else None
        self.name = name
        self.type = span_type
        self.attributes = dict(attributes) if attributes else {}
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.status = "ok"
        self.error: Optional[str] = None
        self.children: list["Span"] = []
        self._token: Optional[Any] = None

    # -- context manager ------------------------------------------------
    def __enter__(self) -> "Span":
        self._token = _current_span.set(self)
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        self.end_time = time.time()
        if exc_type is not None:
            self.status = "error"
            self.error = f"{exc_type.__name__}: {exc_val}"
        # 将自己注册到父 span 的 children
        if self._parent is not None and self._parent is not self:
            self._parent.children.append(self)
        _current_span.reset(self._token)  # type: ignore[arg-type]
        self._token = None
        # 写入存储
        target = self._store if self._store is not None else tracer
        target.emit(self)

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        """设置 span 结束状态。"""
        self.status = status
        if error is not None:
            self.error = error

    def to_dict(self) -> dict:
        """序列化为 JSON 可序列化字典。"""
        return {
            "schemaVersion": "esae.trace.v1",
            "traceId": self._trace_id(),
            "spanId": self.span_id,
            "parentSpanId": self.parent_id,
            "name": self.name,
            "kind": "INTERNAL",
            "span_type": self.type,
            "startTime": datetime.utcfromtimestamp(self.start_time).isoformat() + "Z",
            "endTime": (
                datetime.utcfromtimestamp(self.end_time).isoformat() + "Z"
                if self.end_time is not None
                else None
            ),
            "status": {
                "code": self.status.upper(),
                "message": self.error or "",
            },
            "attributes": dict(self.attributes),
            "duration_ms": (
                round((self.end_time - self.start_time) * 1000, 3)
                if self.end_time is not None
                else None
            ),
        }

    def _trace_id(self) -> str:
        """派生 trace ID（回溯至根 span）。"""
        root = self
        while root._parent is not None and root._parent is not root:
            root = root._parent
        return f"trace-{root.span_id}"


# ═══════════════════════════════════════════════════════════════════════
# NoopSpan
# ═══════════════════════════════════════════════════════════════════════
class NoopSpan:
    """无操作 span — tracing disabled 时使用。

    零 I/O 零分配。接口兼容 ``Span`` 但所有方法均为空操作。
    """

    __slots__ = ()

    span_id: str = ""
    parent_id: Optional[str] = None
    name: str = ""
    span_type: str = ""
    attributes: dict = {}
    start_time: float = 0.0
    end_time: Optional[float] = None
    status: str = "ok"
    error: Optional[str] = None
    children: list = []

    def __enter__(self) -> "NoopSpan":
        return self

    def __exit__(
        self,
        exc_type: Optional[Any],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        pass

    def set_status(self, status: str, error: Optional[str] = None) -> None:
        pass

    def to_dict(self) -> dict:
        return {}


# ═══════════════════════════════════════════════════════════════════════
# instrument 装饰器
# ═══════════════════════════════════════════════════════════════════════
def instrument(
    name: Optional[str] = None,
    span_type: str = "tool",
    extract: Optional[Callable[..., dict]] = None,
) -> Callable:
    """装饰器：自动追踪函数调用。

    用法::

        @trace.instrument("llm.call", span_type="model")
        def call_llm(prompt: str) -> str: ...

        @trace.instrument(span_type="tool", extract=lambda r, **kw: {"result_len": len(r)})
        def my_tool(query: str) -> str: ...

    参数:
        name: span 名称，默认使用函数名
        span_type: span 类型（7 类之一）
        extract: 可选函数，接收函数返回值 ``r`` 和关键字参数，
                 返回要合并到 span.attributes 的字典
    """

    def decorator(func: Callable) -> Callable:
        span_name = name if name is not None else func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _enabled:
                return func(*args, **kwargs)
            attrs: dict[str, Any] = {}
            with Span(span_name, span_type=span_type, attributes=attrs) as span:
                try:
                    result = func(*args, **kwargs)
                    if extract is not None:
                        extra = extract(result, **kwargs)
                        if extra:
                            span.attributes.update(extra)
                    return result
                except BaseException:
                    # Span.__exit__ 已捕获异常并设置 status=error
                    raise

        return wrapper

    return decorator


# ═══════════════════════════════════════════════════════════════════════
# TraceStore
# ═══════════════════════════════════════════════════════════════════════
class TraceStore:
    """追踪存储 — JSONL。

    按日期轮转，artifact SHA1 去重。
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir = (log_dir or Path.home() / ".hermes" / "esae" / "traces").resolve()
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._seen_sha1: set[str] = set()

    def _log_path(self) -> Path:
        """按日期轮转的文件路径。"""
        today = date.today().isoformat()  # 2026-07-26
        return self._log_dir / f"spans-{today}.jsonl"

    def emit(self, span: Span) -> None:
        """将 span 写入 JSONL（已去重）。"""
        if not _enabled:
            return
        data = span.to_dict()
        payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
        sha1 = hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()  # nosec
        if sha1 in self._seen_sha1:
            return
        self._seen_sha1.add(sha1)
        path = self._log_path()
        # 原子追加：write → rename 防部分写入
        tmp = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        try:
            with open(tmp, "a", encoding="utf-8") as f:
                f.write(payload + "\n")
            if path.exists():
                # 合并 tmp 到主文件
                with open(path, "a", encoding="utf-8") as f:
                    with open(tmp, "r", encoding="utf-8") as tf:
                        f.write(tf.read())
                tmp.unlink()
            else:
                tmp.replace(path)
        except OSError:
            # I/O 失败不崩应用
            pass

    def recent(self, n: int = 10) -> list[dict]:
        """返回最近 ``n`` 条 span。"""
        path = self._log_path()
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines[-n:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records


# ═══════════════════════════════════════════════════════════════════════
# 全局追踪器
# ═══════════════════════════════════════════════════════════════════════
tracer = TraceStore()


def enable() -> None:
    """启用 tracing。"""
    global _enabled
    _enabled = True


def disable() -> None:
    """禁用 tracing — 此后所有 span 操作变为 noop。"""
    global _enabled
    _enabled = False


def current_span() -> Optional[Span]:
    """获取当前活动 span（None 表示不在 span 内）。"""
    return _current_span.get()
