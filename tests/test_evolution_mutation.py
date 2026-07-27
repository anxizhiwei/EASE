"""Test: Mutation — mutation.py (evolution module)."""
import pytest
from evolution.genome import make_genome
from evolution.mutation import crossover, special_mutate, MutationSelector, SnapshotStore


class TestCrossover:
    def test_crossover_creates_child(self):
        a = make_genome(5.0, 0.5)
        b = make_genome(10.0, 0.8)
        child = crossover(a, b, inherit_bias=0.5)
        assert child.parent_ids == [a.genome_id, b.genome_id]
        assert child.generation == 1
        assert len(child.params) == 7

    def test_crossover_generation(self):
        a = make_genome(generation=5)
        b = make_genome(generation=3)
        child = crossover(a, b)
        assert child.generation == 6  # max+1


class TestSpecialMutation:
    def test_special_changes_params(self):
        g = make_genome(5.0, 0.5, 20.0)
        child = special_mutate(g, probability=1.0)
        # With 100% probability, at least one param must change
        diffs = sum(1 for i in range(7) if child.params[i] != g.params[i])
        assert diffs >= 1

    def test_special_jump_factor(self):
        g = make_genome(10.0)
        child = special_mutate(g, probability=1.0)
        # The changed param should be either 0.5x or 2x
        changed_idx = [i for i in range(7) if child.params[i] != g.params[i]]
        if changed_idx:
            ratio = child.params[changed_idx[0]] / g.params[changed_idx[0]]
            assert ratio in (0.5, 2.0)


class TestMutationSelector:
    def test_default_is_crossover(self):
        sel = MutationSelector(special_prob=0.0)
        strategy = sel.select(make_genome(), [], stagnation_count=0)
        assert strategy == "crossover"

    def test_stagnation_increases_probability(self):
        """停滞时 special_prob 应该升高。"""
        from evolution.pressure import AdaptivePressure
        p = AdaptivePressure()
        # 停滞 30 代
        ps = p.update(generation=50, stagnation_count=30, best_fitness=0.9, current_fitness=0.9)
        assert ps.special_probability > 0.02  # 高于基线


class TestSnapshotStore:
    def test_snapshot_and_restore(self):
        store = SnapshotStore()
        g = make_genome(10.0)
        snap_id = store.snapshot(g)
        restored = store.restore(snap_id)
        assert restored is not None
        assert restored.params == g.params

    def test_restore_latest(self):
        store = SnapshotStore()
        g1 = make_genome(5.0)
        g2 = make_genome(10.0)
        store.snapshot(g1)
        store.snapshot(g2)
        restored = store.restore()
        assert restored is not None
        assert restored.params == g2.params  # latest
