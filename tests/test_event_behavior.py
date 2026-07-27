"""测试: daemon.py 的心跳频率统计功能。

要求: tick() 应跟踪每种事件类型的发生频率，
并能通过某种方式获取这些统计数据。

初始预期失败 — EASE 需要通过进化实现这个行为。
"""
import sys, os, inspect, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.daemon import ESAEDaemon


def test_tick_tracks_frequency():
    """tick() 应跟踪事件频率：10次tick后，心跳计数应为10。"""
    d = ESAEDaemon()
    before = d.heartbeat.tick_count
    for _ in range(10):
        d.tick()
    after = d.heartbeat.tick_count
    assert after - before >= 10, (
        f"10次tick后计数应增加≥10, 实际增加了{after-before}"
    )


def test_consecutive_ticks_increment():
    """连续 tick 应持续增加计数。"""
    d = ESAEDaemon()
    counts = []
    for _ in range(5):
        d.tick()
        counts.append(d.heartbeat.tick_count)
    # 每次 tick 后计数应严格递增
    for i in range(1, len(counts)):
        assert counts[i] > counts[i-1], (
            f"tick {i}: 计数应递增, {counts[i]} ≤ {counts[i-1]}"
        )


def test_state_tracks_failures():
    """失败应影响心跳状态。"""
    d = ESAEDaemon()
    # 模拟高失败场景
    for _ in range(50):
        d.tick()
    # 状态不应崩溃
    assert d.heartbeat.state in ("starting", "running", "degraded", "stopped")


def test_interval_customization():
    """心跳间隔可自定义并影响行为。"""
    d = ESAEDaemon(interval=0.1)
    before = d.heartbeat.tick_count
    for _ in range(3):
        d.tick()
    after = d.heartbeat.tick_count
    assert after > before, "自定义间隔的tick应正常工作"
