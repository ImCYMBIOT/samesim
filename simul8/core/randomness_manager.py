"""
RandomnessManager — deterministic, reproducible randomness for the simulation.

Every source of randomness in the simulation goes through this manager.
Given the same seed, all random operations produce the same sequence,
regardless of how many agents exist or what order they are processed in.

Per-agent RNGs:
    Each agent receives its own random.Random instance seeded with:
        agent_seed = global_seed XOR agent_id

    XOR mixing ensures:
        - Agent 0 and agent 1 have independent sequences
        - Different global seeds produce different per-agent sequences
        - The formula is simple, deterministic, and Rust-portable

Global RNG:
    Used for topology generation and any experiment-level randomness
    (e.g., initial parameter sampling that is not per-agent).
"""
from __future__ import annotations

import random

from ..domain.ids import AgentId


class RandomnessManager:
    """Manages all seeded RNGs for the simulation.

    Purpose:
        Provide reproducible, independent randomness to all modules.

    Dependencies:
        None. Depends only on stdlib random and the AgentId type alias.

    Lifecycle:
        initialize(seed) is called once before any agents are created.
        reset() re-initializes to the same seed for multi-run experiments.
    """

    def __init__(self) -> None:
        self._seed: int | None = None
        self._global_rng: random.Random | None = None
        self._agent_rngs: dict[AgentId, random.Random] = {}

    def initialize(self, seed: int) -> None:
        """Seed all RNGs. Must be called before any RNG is accessed.

        Args:
            seed: The global experiment seed from ExperimentConfig.
        """
        self._seed = seed
        self._global_rng = random.Random(seed)
        self._agent_rngs.clear()

    @property
    def global_rng(self) -> random.Random:
        """The global experiment-level RNG.

        Used for topology generation and any non-per-agent randomness.

        Raises:
            RuntimeError: If initialize() has not been called.
        """
        if self._global_rng is None:
            raise RuntimeError(
                "RandomnessManager.initialize(seed) must be called before use."
            )
        return self._global_rng

    def stream(self, name: str) -> random.Random:
        """A dedicated RNG stream for one experiment-level component.

        Seeded from the string "<seed>/<name>" (hashed with SHA-512 by
        random.Random, identically on every platform and Python version), so
        it is independent of global_rng: adding a component that draws from
        its own stream never shifts anyone else's draws.
        """
        if self._seed is None:
            raise RuntimeError("RandomnessManager.initialize(seed) must be called before use.")
        return random.Random(f"{self._seed}/{name}")

    def get_agent_rng(self, agent_id: AgentId) -> random.Random:
        """Return the seeded RNG for a specific agent.

        Creates and caches the RNG on first access.
        Seed formula: global_seed XOR agent_id (integer XOR).

        Args:
            agent_id: The agent whose RNG is requested.

        Raises:
            RuntimeError: If initialize() has not been called.
        """
        if self._seed is None:
            raise RuntimeError(
                "RandomnessManager.initialize(seed) must be called before use."
            )
        if agent_id not in self._agent_rngs:
            agent_seed = self._seed ^ int(agent_id)
            self._agent_rngs[agent_id] = random.Random(agent_seed)
        return self._agent_rngs[agent_id]

    def reset(self) -> None:
        """Re-initialize all RNGs to the original seed.

        Restores full reproducibility for a second run.
        """
        if self._seed is not None:
            self.initialize(self._seed)
