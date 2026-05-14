"""Tests for the Hamilton DAG constructor (Feature 52).

Verifies that ``create_pipeline()`` builds a valid, cycle-free DAG with
the expected node count, config injection, and serializability.
"""

from __future__ import annotations

import json

import pytest
from pipeline.config import Config
from pipeline.constructor import create_pipeline

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dag():
    """Build the DAG once per module using env-var defaults."""
    config = Config.from_env()
    return create_pipeline(config).build()


@pytest.fixture(scope="module")
def dag_with_override():
    """Build the DAG with an explicitly constructed Config."""
    config = Config(
        groq_api_key="test-key",
        groq_model="test-model",
        groq_timeout=30,
        groq_max_retries=1,
        code_temperature=0.3,
        theme_temperature=0.4,
        interpretation_temperature=0.5,
        embedding_model="all-MiniLM-L6-v2",
        model_cache_dir="/tmp/cache",
        batch_size=15,
        log_level="DEBUG",
        data_path="/tmp/data.csv",
        tags_path="/tmp/tags.csv",
        processed_data_path="/tmp/processed",
        bm25_tokenizer_config="lowercase,split_by_space",
        fewshot_enabled=False,
        fewshot_count=2,
        fewshot_shuffle=False,
        token_cost_input_per_million=0.15,
        token_cost_output_per_million=0.60,
        max_stage_cost_usd=1.00,
    )
    return create_pipeline(config).build()


# ── Tests ───────────────────────────────────────────────────────────────────


class TestDagConstruction:
    """Structural validation of the Hamilton DAG."""

    def test_node_count(self, dag):
        """Verify at least 13 function nodes plus ``config``."""
        vars_ = dag.list_available_variables()
        # 15 function nodes + 1 auto-injected ``config`` node
        assert len(vars_) >= 16, f"Expected ≥16 nodes, got {len(vars_)}"

    def test_no_cycles(self, dag):
        """DAG must be acyclic — no circular dependencies."""
        fg = dag.graph
        nodes = fg.get_nodes()
        cycles = fg.get_cycles(nodes, [])
        assert cycles == [], f"DAG contains cycles: {cycles}"

    def test_validate_execution_passes(self, dag):
        """``validate_execution`` must succeed for the terminal ``export`` node."""
        # Should not raise
        dag.validate_execution(["export"], {})

    def test_config_injected(self, dag):
        """All user-defined nodes must declare ``config`` as a dependency."""
        fg = dag.graph
        for name, node in fg.nodes.items():
            if name == "config":
                continue
            deps = set(node.input_types.keys())
            assert (
                "config" in deps
            ), f"Node {name!r} is missing 'config' dependency; has {deps}"


class TestTopologicalOrder:
    """Verify topological validity of the DAG."""

    def test_all_dependencies_exist(self, dag):
        """Every node's dependencies must be present in the graph."""
        fg = dag.graph
        nodes = fg.get_nodes()
        all_names = {n.name for n in nodes}

        for node in nodes:
            for dep in node.dependencies:
                dep_name = dep.name
                if dep_name == "config":
                    continue
                assert dep_name in all_names, (
                    f"Node {node.name!r} depends on {dep_name!r} "
                    f"which is not in the graph"
                )

    def test_downstream_dependencies_valid(self, dag):
        """Verify that ``export`` has the expected transitive dependencies."""
        fg = dag.graph
        nodes = fg.get_nodes()
        node_map = {n.name: n for n in nodes}

        export_node = node_map["export"]
        export_deps = {d.name for d in export_node.dependencies}
        assert "review_interpretations" in export_deps

        # Walk upstream: export → review_interpretations → infer_interpretations
        review_interp = node_map["review_interpretations"]
        review_deps = {d.name for d in review_interp.dependencies}
        assert "infer_interpretations" in review_deps


class TestSerialization:
    """DAG must be serializable to JSON for debugging."""

    def test_list_available_variables_serializable(self, dag):
        """``list_available_variables`` output must be JSON-serializable."""
        vars_ = dag.list_available_variables()
        payload = [{"name": v.name, "type": str(v.type)} for v in vars_]
        serialized = json.dumps(payload, indent=2)
        assert isinstance(serialized, str)
        assert len(serialized) > 0
        # Round-trip
        restored = json.loads(serialized)
        assert len(restored) == len(vars_)

    def test_node_names_serializable(self, dag):
        """Node names and dependency info must serialize to JSON."""
        fg = dag.graph
        nodes = fg.get_nodes()
        payload = [
            {
                "name": n.name,
                "type": str(n.type),
                "dependencies": list(n.input_types.keys()),
            }
            for n in nodes
        ]
        serialized = json.dumps(payload, indent=2)
        restored = json.loads(serialized)
        names = {entry["name"] for entry in restored}
        assert "load_artifacts" in names
        assert "export" in names


class TestConfigOverride:
    """DAG must accept an overridden Config."""

    def test_dag_builds_with_override_config(self, dag_with_override):
        """Building with an explicit Config must not raise."""
        assert dag_with_override is not None

    def test_override_config_injected(self, dag_with_override):
        """The overridden config must be accessible via the ``config`` node."""
        vars_ = dag_with_override.list_available_variables()
        config_var = next((v for v in vars_ if v.name == "config"), None)
        assert config_var is not None, "config node not found in DAG variables"


class TestNodeNames:
    """All expected node names must be present."""

    MAIN_NODES = {
        "load_artifacts",
        "embed_exemplars",
        "embed_keywords",
        "build_bm25",
        "build_ontology",
        "retrieve_candidates",
        "infer_codes",
        "review_codes",
        "infer_themes",
        "review_themes",
        "infer_interpretations",
        "review_interpretations",
        "export",
    }

    SUPPORTING_NODES = {
        "init_embedding_model",
        "init_groq_client",
    }

    def test_all_main_nodes_present(self, dag):
        """All 13 main pipeline nodes must exist in the DAG."""
        vars_ = {v.name for v in dag.list_available_variables()}
        missing = self.MAIN_NODES - vars_
        assert not missing, f"Missing main nodes: {missing}"

    def test_all_supporting_nodes_present(self, dag):
        """All expected supporting nodes must exist in the DAG."""
        vars_ = {v.name for v in dag.list_available_variables()}
        missing = self.SUPPORTING_NODES - vars_
        assert not missing, f"Missing supporting nodes: {missing}"


class TestConfigDataclass:
    """``Config.from_env()`` must produce a valid frozen dataclass."""

    def test_from_env_returns_config(self):
        config = Config.from_env()
        assert isinstance(config, Config)

    def test_config_is_frozen(self):
        config = Config.from_env()
        with pytest.raises(AttributeError):
            config.groq_api_key = "nope"  # type: ignore[misc]

    def test_config_fields_populated(self):
        config = Config.from_env()
        # At minimum the required fields should have non-None values
        assert config.groq_api_key is not None
        assert config.groq_model is not None
        assert config.batch_size > 0
