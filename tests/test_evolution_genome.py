"""Test: Genome — genome.py (evolution module)."""
import pytest
from evolution.genome import Genome, EASE_PARAMS, make_genome, clamp_params, genome_distance


class TestEASEParams:
    def test_seven_params(self):
        assert len(EASE_PARAMS) == 7

    def test_each_param_has_name_and_bounds(self):
        for p in EASE_PARAMS:
            assert p.name
            assert p.min_val < p.max_val


class TestGenome:
    def test_default_params_length(self):
        g = Genome()
        assert len(g.params) == 7

    def test_make_genome_override(self):
        g = make_genome(10.0, 0.3)
        assert g.params[0] == 10.0
        assert g.params[1] == 0.3

    def test_genome_id_unique(self):
        g1, g2 = Genome(), Genome()
        assert g1.genome_id != g2.genome_id

    def test_clamp_params(self):
        clamped = clamp_params([-100, 0.5, 20, 1.1, 0.5, 30, 3])
        assert clamped[0] == 1.0  # min=1.0

    def test_genome_distance_zero(self):
        g = make_genome()
        assert genome_distance(g, g) == 0.0

    def test_genome_distance_different(self):
        a = make_genome(5.0)
        b = make_genome(30.0)
        assert genome_distance(a, b) > 0

    def test_to_dict_roundtrip(self):
        g = make_genome(10.0, 0.3)
        d = g.to_dict()
        g2 = Genome.from_dict(d)
        assert g2.params == g.params
        assert g2.genome_id == g.genome_id

    def test_describe(self):
        g = make_genome()
        desc = g.describe()
        assert "FITNESS" in desc
        assert "heartbeat_interval" in desc
