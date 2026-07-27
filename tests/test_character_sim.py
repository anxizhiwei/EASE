"""测试: daemon.py 的人物状态模拟功能。

功能目标: 记录、查询、变更人物状态数据。
- add_character(name, hp=100, mp=50, level=1) — 创建角色
- get_character(name) -> dict — 查询角色状态
- apply_to_character(name, event, value) — 对角色施加事件(伤害/治疗/升级)
- list_characters() -> list[str] — 列出所有角色

初始预期失败 — EASE 需要通过进化实现。
"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from kernel.daemon import ESAEDaemon


def test_add_character_exists():
    """ESAEDaemon 必须有 add_character() 方法"""
    assert hasattr(ESAEDaemon, "add_character"), \
        "缺少 add_character(name, hp=100, mp=50, level=1) — 创建角色"


def test_add_character_works():
    """add_character 能创建角色并存储"""
    if not hasattr(ESAEDaemon, "add_character"):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("勇者", hp=100, mp=50, level=1)
    d.add_character("法师", hp=60, mp=100, level=2)
    # 不抛异常 = 通过


def test_add_character_duplicate():
    """重复添加角色应更新而非崩溃"""
    if not hasattr(ESAEDaemon, "add_character"):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("战士", hp=80, mp=30, level=1)
    d.add_character("战士", hp=200, mp=50, level=5)  # 更新
    # 不抛异常 = 通过


def test_get_character_exists():
    """ESAEDaemon 必须有 get_character() 方法"""
    assert hasattr(ESAEDaemon, "get_character"), \
        "缺少 get_character(name) -> dict — 查询角色"


def test_get_character_returns_dict():
    """get_character 返回包含 hp/mp/level 的 dict"""
    if not hasattr(ESAEDaemon, "get_character") or \
       not hasattr(ESAEDaemon, "add_character"):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("测试角色", hp=100, mp=50, level=1)
    state = d.get_character("测试角色")
    assert isinstance(state, dict), f"返回值应为 dict, 实际为 {type(state)}"
    assert "hp" in state, "缺少 hp 字段"
    assert "mp" in state, "缺少 mp 字段"
    assert "level" in state, "缺少 level 字段"


def test_get_character_nonexistent():
    """查询不存在的角色应返回 None 或空 dict"""
    if not hasattr(ESAEDaemon, "get_character"):
        pytest.skip()
    d = ESAEDaemon()
    result = d.get_character("不存在的角色")
    assert result is None or result == {}, \
        f"不存在的角色应返回 None/{{}}, 实际为 {result}"


def test_apply_to_character_exists():
    """ESAEDaemon 必须有 apply_to_character() 方法"""
    assert hasattr(ESAEDaemon, "apply_to_character"), \
        "缺少 apply_to_character(name, event, value) — 施加事件"


def test_apply_to_character_damage():
    """apply_to_character 能对角色造成伤害"""
    if not all(hasattr(ESAEDaemon, m) for m in
               ["add_character", "get_character", "apply_to_character"]):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("测试目标", hp=100, mp=50, level=1)
    d.apply_to_character("测试目标", "damage", 30)
    state = d.get_character("测试目标")
    assert state["hp"] <= 70, f"伤害后 hp 应 ≤70, 实际为 {state['hp']}"


def test_apply_to_character_heal():
    """apply_to_character 能治疗角色"""
    if not all(hasattr(ESAEDaemon, m) for m in
               ["add_character", "get_character", "apply_to_character"]):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("伤者", hp=50, mp=50, level=1)
    d.apply_to_character("伤者", "heal", 30)
    state = d.get_character("伤者")
    assert state["hp"] >= 80, f"治疗后 hp 应 ≥80, 实际为 {state['hp']}"


def test_list_characters_exists():
    """ESAEDaemon 必须有 list_characters() 方法"""
    assert hasattr(ESAEDaemon, "list_characters"), \
        "缺少 list_characters() — 列出所有角色"


def test_list_characters_works():
    """list_characters 返回所有角色名列表"""
    if not all(hasattr(ESAEDaemon, m) for m in
               ["add_character", "list_characters"]):
        pytest.skip()
    d = ESAEDaemon()
    d.add_character("角色A", hp=100, mp=50, level=1)
    d.add_character("角色B", hp=80, mp=80, level=2)
    names = d.list_characters()
    assert isinstance(names, list), f"返回值应为 list, 实际为 {type(names)}"
    assert "角色A" in names, "应包含 角色A"
    assert "角色B" in names, "应包含 角色B"
