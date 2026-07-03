"""Unit tests for AgentRegistry."""
import pytest
from simul8.core.agent_registry import AgentRegistry
from simul8.domain.ids import AgentId
from simul8.domain.state import AgentState


class TestAgentRegistryCreation:
    def test_starts_empty(self):
        r = AgentRegistry()
        assert r.count() == 0

    def test_create_assigns_sequential_ids(self):
        r = AgentRegistry()
        id0 = r.create_agent()
        id1 = r.create_agent()
        id2 = r.create_agent()
        assert id0 == AgentId(0)
        assert id1 == AgentId(1)
        assert id2 == AgentId(2)

    def test_create_with_initial_state(self):
        r = AgentRegistry()
        state = AgentState(data={"value": 0.7})
        aid = r.create_agent(initial_state=state)
        assert r.get(aid).state.get("value") == 0.7

    def test_create_default_state_is_empty(self):
        r = AgentRegistry()
        aid = r.create_agent()
        assert r.get(aid).state.data == {}

    def test_count_tracks_creation(self):
        r = AgentRegistry()
        for i in range(5):
            r.create_agent()
        assert r.count() == 5


class TestAgentRegistryRetrieval:
    def test_get_existing_agent(self):
        r = AgentRegistry()
        aid = r.create_agent()
        agent = r.get(aid)
        assert agent.agent_id == aid

    def test_get_nonexistent_raises_keyerror(self):
        r = AgentRegistry()
        with pytest.raises(KeyError):
            r.get(AgentId(999))

    def test_all_agent_ids_order(self):
        r = AgentRegistry()
        ids = [r.create_agent() for _ in range(4)]
        retrieved = r.all_agent_ids()
        assert retrieved == ids

    def test_iter_agents_yields_all(self):
        r = AgentRegistry()
        for _ in range(3):
            r.create_agent()
        assert sum(1 for _ in r.iter_agents()) == 3


class TestAgentRegistryStateUpdate:
    def test_update_state_replaces_state(self):
        r = AgentRegistry()
        aid = r.create_agent(initial_state=AgentState(data={"value": 0.0}))
        new_state = AgentState(data={"value": 1.0})
        r.update_state(aid, new_state)
        assert r.get(aid).state.get("value") == 1.0

    def test_update_nonexistent_raises(self):
        r = AgentRegistry()
        with pytest.raises(KeyError):
            r.update_state(AgentId(42), AgentState())


class TestAgentRegistryClear:
    def test_clear_resets_count(self):
        r = AgentRegistry()
        for _ in range(5):
            r.create_agent()
        r.clear()
        assert r.count() == 0

    def test_clear_resets_id_counter(self):
        r = AgentRegistry()
        r.create_agent()
        r.clear()
        new_id = r.create_agent()
        assert new_id == AgentId(0)
