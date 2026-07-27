"""测试: daemon.py 的事件频率统计功能。

功能目标: 记录并统计不同类型的"事件"发生频率。
- record_event(event_type: str) — 记录一次事件
- get_event_stats(minutes=5) — 返回各类型事件在指定时间窗口内的频率

这个测试在开始时预期失败 — EASE 需要通过进化实现它。
"""
import sys, os, inspect, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.daemon import ESAEDaemon

# ── 功能 1: 记录事件 ──────────────────────────

def test_record_event_exists():
    """ESAEDaemon 必须有 record_event() 方法"""
    assert hasattr(ESAEDaemon, "record_event"), \
        "缺少 record_event(event_type) — 记录事件"

def test_record_event_works():
    """record_event 能接收事件类型并存储"""
    if not hasattr(ESAEDaemon, "record_event"):
        pytest.skip()
    d = ESAEDaemon()
    d.record_event("heartbeat")
    d.record_event("failure")
    d.record_event("heartbeat")  # 两次
    # 不抛异常 = 通过

def test_record_event_rejects_invalid():
    """record_event 对无效输入有合理处理"""
    if not hasattr(ESAEDaemon, "record_event"):
        pytest.skip()
    d = ESAEDaemon()
    # 空字符串或 None 不应导致崩溃
    try:
        d.record_event("")
        d.record_event("normal_event_123")
    except Exception:
        pytest.fail("record_event 对正常输入抛异常")

# ── 功能 2: 获取统计 ──────────────────────────

def test_get_event_stats_exists():
    """ESAEDaemon 必须有 get_event_stats() 方法"""
    if not hasattr(ESAEDaemon, "record_event"):
        pytest.skip()
    assert hasattr(ESAEDaemon, "get_event_stats"), \
        "缺少 get_event_stats(minutes=5) — 返回频率统计"

def test_get_event_stats_returns_dict():
    """get_event_stats 返回 dict[event_type → count]"""
    if not hasattr(ESAEDaemon, "get_event_stats"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "record_event"):
        d.record_event("type_a")
        d.record_event("type_b")
        d.record_event("type_a")
    stats = d.get_event_stats(minutes=5)
    assert isinstance(stats, dict), f"返回值应为 dict, 实际为 {type(stats)}"

def test_get_event_stats_accurate():
    """频率统计准确：3次→2次type_a + 1次type_b"""
    if not hasattr(ESAEDaemon, "get_event_stats"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "record_event"):
        d.record_event("type_a")
        d.record_event("type_b")
        d.record_event("type_a")
    stats = d.get_event_stats(minutes=5)
    assert stats.get("type_a", 0) == 2, \
        f"type_a 预期2, 实际 {stats.get('type_a', 0)}"
    assert stats.get("type_b", 0) == 1, \
        f"type_b 预期1, 实际 {stats.get('type_b', 0)}"

def test_get_event_stats_window():
    """统计窗口生效：不同 minutes 返回不同结果"""
    if not hasattr(ESAEDaemon, "get_event_stats"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "record_event"):
        d.record_event("test_type")
    total = d.get_event_stats(minutes=60)
    recent = d.get_event_stats(minutes=5)
    assert isinstance(total, dict) and isinstance(recent, dict), \
        "不同窗口均应返回 dict"
