"""Test: MemoryBackend protocol + MemoryItem (memory/backend.py)

AAA (Arrange-Act-Assert) pattern.
MemoryBackend is abstract — test MemoryItem dataclass and interface compliance.
"""

import pytest
from memory.backend import MemoryItem


class TestMemoryItem:
    """Contract: MemoryItem is frozen, has all required fields."""

    def test_creation_with_minimal_args(self):
        item = MemoryItem(id="g1", content="genome:heartbeat=10s")
        assert item.id == "g1"
        assert item.content == "genome:heartbeat=10s"

    def test_defaults(self):
        item = MemoryItem(id="g1", content="test")
        assert item.score == 0.0
        assert item.timestamp == 0.0
        assert item.agent_id == ""
        assert item.user_id == ""
        assert item.metadata == {}

    def test_all_fields(self):
        item = MemoryItem(
            id="g1", content="test", score=0.85,
            timestamp=1234567890.0, agent_id="a1", user_id="u1",
            metadata={"source": "evolve"},
        )
        assert item.score == 0.85
        assert item.agent_id == "a1"

    def test_frozen_cannot_be_modified(self):
        item = MemoryItem(id="g1", content="test")
        with pytest.raises((AttributeError, TypeError)):
            item.id = "new_id"

    def test_repr_is_readable(self):
        item = MemoryItem(id="g1", content="genome:heartbeat=10s")
        r = repr(item)
        assert "MemoryItem" in r
        assert "g1" in r
