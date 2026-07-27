"""测试: daemon.py 的自绘界面功能。

功能目标: 根据角色数据自动生成可视化显示。
- render_character(name) -> str — 生成单个角色的显示文本
- render_all_characters() -> str — 生成所有角色的总览显示
- render_stats() -> str — 生成系统状态显示

显示应包含: 角色名、HP/MP条(图形化)、等级。
初始预期失败 — EASE 需要通过进化实现。
"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from kernel.daemon import ESAEDaemon


def test_render_character_exists():
    """ESAEDaemon 必须有 render_character() 方法"""
    assert hasattr(ESAEDaemon, "render_character"), \
        "缺少 render_character(name) -> str — 生成角色显示"


def test_render_character_returns_string():
    """render_character 返回非空字符串"""
    if not hasattr(ESAEDaemon, "render_character"):
        pytest.skip()
    d = ESAEDaemon()
    # 如果有 add_character 则先创建一个
    if hasattr(d, "add_character"):
        d.add_character("显示例", hp=100, mp=50, level=5)
    output = d.render_character("显示例")
    assert isinstance(output, str), f"返回值应为 str, 实际为 {type(output)}"
    assert len(output) > 0, "显示不应为空"


def test_render_character_contains_name():
    """render_character 输出应包含角色名"""
    if not hasattr(ESAEDaemon, "render_character"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "add_character"):
        d.add_character("艾琳", hp=80, mp=120, level=3)
    output = d.render_character("艾琳")
    assert "艾琳" in output or "Elina" in output or "Ailin" in output, \
        f"输出应包含角色名, 实际输出: {output[:50]}"


def test_render_character_has_hp_marker():
    """render_character 输出应有HP指示"""
    if not hasattr(ESAEDaemon, "render_character"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "add_character"):
        d.add_character("HP测试", hp=100, mp=50, level=1)
    output = d.render_character("HP测试")
    assert "HP" in output or "hp" in output or "❤" in output or "█" in output, \
        f"输出应包含HP指示, 实际: {output[:80]}"


def test_render_character_has_level():
    """render_character 输出应有等级"""
    if not hasattr(ESAEDaemon, "render_character"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "add_character"):
        d.add_character("等级测试", hp=100, mp=50, level=7)
    output = d.render_character("等级测试")
    has_lvl = any(marker in output for marker in
                  ["Lv", "LV", "lv", "Level", "LEVEL", "level", "级"])
    assert has_lvl, f"输出应包含等级, 实际: {output[:80]}"


def test_render_all_characters_exists():
    """ESAEDaemon 必须有 render_all_characters() 方法"""
    assert hasattr(ESAEDaemon, "render_all_characters"), \
        "缺少 render_all_characters() — 生成总览"


def test_render_all_characters_works():
    """render_all_characters 返回非空字符串"""
    if not hasattr(ESAEDaemon, "render_all_characters"):
        pytest.skip()
    d = ESAEDaemon()
    if hasattr(d, "add_character"):
        d.add_character("角色甲", hp=100, mp=50, level=1)
        d.add_character("角色乙", hp=60, mp=100, level=2)
    output = d.render_all_characters()
    assert isinstance(output, str), f"返回值应为 str, 实际为 {type(output)}"
    if hasattr(d, "add_character"):
        assert len(output) > 0, "有角色时显示不应为空"
