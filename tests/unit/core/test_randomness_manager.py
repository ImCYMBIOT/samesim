"""Unit tests for RandomnessManager."""
import pytest
from samesim.core.randomness_manager import RandomnessManager
from samesim.domain.ids import AgentId


class TestRandomnessManagerInit:
    def test_global_rng_raises_before_init(self):
        with pytest.raises(RuntimeError, match="initialize"):
            _ = RandomnessManager().global_rng

    def test_agent_rng_raises_before_init(self):
        with pytest.raises(RuntimeError, match="initialize"):
            RandomnessManager().get_agent_rng(AgentId(0))


class TestRandomnessDeterminism:
    def test_global_rng_same_seed_same_sequence(self):
        rm1 = RandomnessManager()
        rm1.initialize(42)
        rm2 = RandomnessManager()
        rm2.initialize(42)
        # Draw 10 values from each; must be identical
        seq1 = [rm1.global_rng.random() for _ in range(10)]
        seq2 = [rm2.global_rng.random() for _ in range(10)]
        assert seq1 == seq2

    def test_agent_rng_same_seed_same_sequence(self):
        rm1 = RandomnessManager()
        rm1.initialize(42)
        rm2 = RandomnessManager()
        rm2.initialize(42)
        aid = AgentId(7)
        seq1 = [rm1.get_agent_rng(aid).random() for _ in range(10)]
        seq2 = [rm2.get_agent_rng(aid).random() for _ in range(10)]
        assert seq1 == seq2

    def test_different_seeds_different_sequences(self):
        rm1 = RandomnessManager()
        rm1.initialize(1)
        rm2 = RandomnessManager()
        rm2.initialize(2)
        assert rm1.global_rng.random() != rm2.global_rng.random()


class TestRandomnessIndependence:
    def test_agent_rngs_independent(self):
        """Different agent IDs should produce different sequences."""
        rm = RandomnessManager()
        rm.initialize(42)
        v0 = rm.get_agent_rng(AgentId(0)).random()
        v1 = rm.get_agent_rng(AgentId(1)).random()
        # With overwhelming probability these differ (they use different seeds)
        assert v0 != v1

    def test_agent_rng_cached(self):
        """Same agent_id always returns the same RNG object."""
        rm = RandomnessManager()
        rm.initialize(42)
        r1 = rm.get_agent_rng(AgentId(5))
        r2 = rm.get_agent_rng(AgentId(5))
        assert r1 is r2


class TestRandomnessReset:
    def test_reset_restores_sequence(self):
        rm = RandomnessManager()
        rm.initialize(99)
        v1 = rm.global_rng.random()
        rm.reset()
        v2 = rm.global_rng.random()
        assert v1 == v2

    def test_reset_clears_agent_rngs(self):
        rm = RandomnessManager()
        rm.initialize(42)
        r_before = rm.get_agent_rng(AgentId(0))
        _ = r_before.random()  # advance state
        rm.reset()
        r_after = rm.get_agent_rng(AgentId(0))
        # After reset, the agent RNG is a fresh object (re-seeded)
        assert r_before is not r_after


class TestStreamsAreDistinctAcrossSeeds:
    """Every (seed, agent) pair and every named stream must be its own stream.

    Replicate runs are only independent if different seeds give different
    streams, not the same streams handed to different agents. The seed used
    to be seed XOR agent_id: for seeds below the agent count that only
    permutes ids, so seeds 1 and 2 used the identical set of agent streams
    and "independent" replicates were partly copies of each other. Any seed
    + id arithmetic has the same flaw. These checks fail for all of them.
    """

    SEEDS = range(64)
    AGENTS = range(1024)

    @staticmethod
    def _first_draws(rng, k=2):
        return tuple(rng.random() for _ in range(k))

    def test_no_two_seed_agent_pairs_share_a_stream(self):
        seen = {}
        for seed in self.SEEDS:
            rm = RandomnessManager()
            rm.initialize(seed)
            for a in self.AGENTS:
                key = self._first_draws(rm.get_agent_rng(AgentId(a)))
                assert key not in seen, (
                    f"seed {seed} agent {a} reuses the stream of seed/agent {seen[key]}"
                )
                seen[key] = (seed, a)

    def test_different_seeds_give_different_agent_populations(self):
        # The symptom XOR produced: the same multiset of initial draws.
        def population(seed):
            rm = RandomnessManager()
            rm.initialize(seed)
            return {rm.get_agent_rng(AgentId(a)).random() for a in range(200)}
        assert not (population(1) & population(2))

    def test_named_streams_never_coincide_with_agent_streams(self):
        rm = RandomnessManager()
        rm.initialize(5)
        agents = {self._first_draws(rm.get_agent_rng(AgentId(a))) for a in range(64)}
        names = ["dynamics", "agent/0", "agent/1", "0", "1", "stream/dynamics"]
        streams = {self._first_draws(rm.stream(n)) for n in names}
        assert len(streams) == len(names)
        assert not (agents & streams)
        assert self._first_draws(rm.global_rng) not in agents | streams
