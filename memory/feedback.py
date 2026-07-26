"""EvidenceTracker — 跨代进化证据的权重累计器。

从 Raven Sentinel NudgeFeedbackTracker 提取并适配为 ESAE 样式。
纯 stdlib，无第三方依赖。

设计要点：
- ACCEPTED / DISMISSED / IGNORED 三种终端信号。
- IGNORED 权重为 DISMISSED 的 0.5 倍（软否定，需要约 2× 数量才能达到阈值）。
- 存储格式：追加式 JSONL，路径可配置。
- 空实现安全降级：构造函数不做 I/O，load() 幂等可重入。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any


class FeedbackSignal(str, Enum):
    """执行反馈信号类型。"""

    DISPATCHED = "dispatched"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    IGNORED = "ignored"
    NEUTRAL = "neutral"


# IGNORED 权重相对于 DISMISSED —— 沉默比显式拒绝更弱
_IGNORED_REJECT_WEIGHT: float = 0.5


class EvidenceTracker:
    """跨代进化证据的权重累计器。

    线程安全限制：非线程安全 —— 每个进程一个实例，序列化访问。

    Public API:
    - record_dispatched / record_accepted / record_dismissed / record_ignored
    - acceptance_rate() / topic_acceptance_rate()
    - counts() / recent()
    - load() / cleanup_older_than()

    典型用法::

        tracker = EvidenceTracker("~/.hermes/esae/evidence.jsonl")
        tracker.load()
        tracker.record_dispatched("ev-001", action="skill_inject")
        ...
        tracker.record_accepted("ev-001")
        rate = tracker.acceptance_rate()
    """

    def __init__(
        self,
        log_path: str = "~/.hermes/esae/evidence.jsonl",
        *,
        in_memory_window_days: int = 30,
    ) -> None:
        self.log_path = Path(log_path).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._window = timedelta(days=in_memory_window_days)
        self._recent: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Write — 记录事件

    def record_dispatched(
        self,
        evidence_id: str,
        *,
        action: str = "",
        topic_tag: str = "",
        priority: str = "normal",
        details: dict[str, Any] | None = None,
    ) -> None:
        """记录一次证据分发。"""
        self._emit(
            {
                "id": evidence_id,
                "signal": FeedbackSignal.DISPATCHED.value,
                "action": action,
                "topic_tag": topic_tag,
                "priority": priority,
                "details": details or {},
            }
        )

    def record_accepted(self, evidence_id: str, *, context: str | None = None) -> None:
        """记录一次接受 —— 证据被采纳。"""
        self._emit(
            {
                "id": evidence_id,
                "signal": FeedbackSignal.ACCEPTED.value,
                "context": context,
            }
        )

    def record_dismissed(self, evidence_id: str, *, reason: str | None = None) -> None:
        """记录一次显式驳回。"""
        self._emit(
            {
                "id": evidence_id,
                "signal": FeedbackSignal.DISMISSED.value,
                "reason": reason,
            }
        )

    def record_ignored(self, evidence_id: str, *, window_seconds: int = 0) -> None:
        """记录沉默忽略 —— 软否定。"""
        self._emit(
            {
                "id": evidence_id,
                "signal": FeedbackSignal.IGNORED.value,
                "window_seconds": window_seconds,
            }
        )

    # ------------------------------------------------------------------
    # 读 / 统计

    def load(self) -> None:
        """从 JSONL 日志重新加载内存缓存。

        幂等，安全重复调用。格式错误行被跳过。
        """
        if not self.log_path.exists():
            return
        cutoff = datetime.now() - self._window
        loaded: list[dict[str, Any]] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("ts")
                    if isinstance(ts, str):
                        try:
                            if datetime.fromisoformat(ts) >= cutoff:
                                loaded.append(rec)
                        except ValueError:
                            pass
        except OSError:
            return
        self._recent = loaded

    def acceptance_rate(
        self,
        *,
        since_days: int = 7,
        topic_tag: str | None = None,
        min_volume: int = 5,
    ) -> float | None:
        """返回窗口内 ACCEPTED / (DISPATCHED - NEUTRAL) 比率。

        topic_tag: 限定到某主题标签。
        min_volume: 低于此量返回 None（疑罪从无）。
        """
        cutoff = datetime.now() - timedelta(days=since_days)
        dispatched_ids: set[str] = set()
        accepted_ids: set[str] = set()
        neutral_ids: set[str] = set()
        topic_filter_ids: set[str] | None = set() if topic_tag is not None else None
        for rec in self._recent:
            ts = self._parse_ts(rec.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            signal = rec.get("signal")
            nid = rec.get("id")
            if not nid:
                continue
            if signal == FeedbackSignal.DISPATCHED.value:
                dispatched_ids.add(nid)
                if topic_filter_ids is not None:
                    tag = rec.get("topic_tag", "")
                    if tag == topic_tag:
                        topic_filter_ids.add(nid)
            elif signal == FeedbackSignal.ACCEPTED.value:
                accepted_ids.add(nid)
            elif signal == FeedbackSignal.NEUTRAL.value:
                neutral_ids.add(nid)
        scored = dispatched_ids - neutral_ids
        if topic_filter_ids is not None:
            scored &= topic_filter_ids
        if len(scored) < min_volume:
            return None
        return len(accepted_ids & scored) / len(scored)

    def weighted_reject_count(
        self,
        *,
        topic_tag: str | None = None,
        since_days: int = 1,
    ) -> float:
        """返回加权驳回计数。

        DISMISSED=1.0, IGNORED=0.5。已被 ACCEPTED 覆盖的不计数。
        topic_tag 可限定到某主题。
        """
        if not topic_tag:
            return 0.0
        cutoff = datetime.now() - timedelta(days=since_days)
        topic_for_id: dict[str, str] = {}
        accepted_ids: set[str] = set()
        reject_weight: dict[str, float] = {}
        for rec in self._recent:
            ts = self._parse_ts(rec.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            nid = rec.get("id")
            if not nid:
                continue
            signal = rec.get("signal")
            if signal == FeedbackSignal.DISPATCHED.value:
                tag = rec.get("topic_tag", "")
                if isinstance(tag, str) and tag:
                    topic_for_id[nid] = tag
            elif signal == FeedbackSignal.ACCEPTED.value:
                accepted_ids.add(nid)
            elif signal == FeedbackSignal.DISMISSED.value:
                reject_weight[nid] = 1.0
            elif signal == FeedbackSignal.IGNORED.value:
                reject_weight[nid] = max(
                    reject_weight.get(nid, 0.0),
                    _IGNORED_REJECT_WEIGHT,
                )
        return sum(
            w
            for nid, w in reject_weight.items()
            if topic_for_id.get(nid) == topic_tag and nid not in accepted_ids
        )

    def counts(self, since_days: int = 7) -> dict[str, int]:
        """窗口内各信号原始计数。"""
        cutoff = datetime.now() - timedelta(days=since_days)
        c: dict[str, int] = {s.value: 0 for s in FeedbackSignal}
        for rec in self._recent:
            ts = self._parse_ts(rec.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            signal = rec.get("signal", "unknown")
            c[signal] = c.get(signal, 0) + 1
        return c

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        """最近 N 条事件。"""
        return self._recent[-n:]

    def cleanup_older_than(self, days: int = 30) -> dict[str, int]:
        """保留窗口内日志，原子重写。

        通过临时文件 + rename 实现原子性。返回 ``{"kept": N, "dropped": N}``。
        """
        if not self.log_path.exists():
            return {"kept": 0, "dropped": 0}

        cutoff = datetime.now() - timedelta(days=days)
        tmp_path = self.log_path.with_suffix(self.log_path.suffix + ".cleanup")
        kept = 0
        dropped = 0
        try:
            with self.log_path.open("r", encoding="utf-8") as src, tmp_path.open(
                "w", encoding="utf-8"
            ) as dst:
                for line in src:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        rec = json.loads(s)
                    except json.JSONDecodeError:
                        dropped += 1
                        continue
                    ts = rec.get("ts")
                    if not isinstance(ts, str):
                        dropped += 1
                        continue
                    try:
                        rec_dt = datetime.fromisoformat(ts)
                    except ValueError:
                        dropped += 1
                        continue
                    if rec_dt >= cutoff:
                        dst.write(s + "\n")
                        kept += 1
                    else:
                        dropped += 1
            tmp_path.replace(self.log_path)
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return {"kept": 0, "dropped": 0, "error": 1}

        self._recent = [
            r
            for r in self._recent
            if isinstance(r.get("ts"), str)
            and self._parse_ts(r["ts"]) is not None
            and self._parse_ts(r["ts"]) >= cutoff
        ]
        return {"kept": kept, "dropped": dropped}

    # ------------------------------------------------------------------
    # Internals

    def _emit(self, payload: dict[str, Any]) -> None:
        record = {"ts": datetime.now().isoformat(), **payload}
        try:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            return
        self._recent.append(record)
        if len(self._recent) > 10_000:
            cutoff = datetime.now() - self._window
            self._recent = [
                r
                for r in self._recent
                if r.get("ts")
                and datetime.fromisoformat(r["ts"]) >= cutoff
            ]

    @staticmethod
    def _parse_ts(ts: str) -> datetime | None:
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None


def new_evidence_id() -> str:
    """生成短证据 ID，用于关联分发→接受/驳回。"""
    return uuid.uuid4().hex[:16]


__all__ = ["EvidenceTracker", "FeedbackSignal", "new_evidence_id"]
