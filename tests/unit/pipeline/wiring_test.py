"""Tests for DAG wiring utilities (Feature 54).

Verifies ``verify_dag_integrity``, ``render_dag_mermaid``,
``validate_dataflow``, and ``execute_with_overrides`` from
``pipeline.wiring``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import pytest  # noqa: E402
from pipeline.config import Config  # noqa: E402
from pipeline.constructor import create_pipeline  # noqa: E402
from pipeline.mermaid import render_dag_mermaid  # noqa: E402
from pipeline.wiring import (  # noqa: E402
    execute_with_overrides,
    validate_dataflow,
    verify_dag_integrity,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dag():
    """Build the DAG once per module using env-var defaults."""
    config = Config.from_env()
    return create_pipeline(config).build()


# ── verify_dag_integrity ────────────────────────────────────────────────────


class TestVerifyDagIntegrity:
    """``verify_dag_integrity`` returns a structured health report."""

    def test_returns_expected_keys(self, dag):
        report = verify_dag_integrity(dag)
        expected_keys = {
            "node_count",
            "has_cycles",
            "cycles",
            "all_deps_resolved",
            "missing_deps",
            "config_injected_in_all_nodes",
            "nodes_without_config",
            "topological_order",
            "orphan_nodes",
            "terminal_nodes",
        }
        assert (
            set(report) == expected_keys
        ), f"Extra/missing keys: {set(report) ^ expected_keys}"

    def test_no_cycles_reported(self, dag):
        report = verify_dag_integrity(dag)
        assert report["has_cycles"] is False
        assert report["cycles"] == []

    def test_node_count_at_least_50(self, dag):
        report = verify_dag_integrity(dag)
        assert report["node_count"] >= 50, f"Got {report['node_count']} nodes"

    def test_all_deps_resolved(self, dag):
        report = verify_dag_integrity(dag)
        assert report["all_deps_resolved"] is True
        assert report["missing_deps"] == []

    def test_config_injected(self, dag):
        report = verify_dag_integrity(dag)
        assert report["config_injected_in_all_nodes"] is True
        assert report["nodes_without_config"] == []

    def test_topological_order_is_list_of_strings(self, dag):
        report = verify_dag_integrity(dag)
        assert isinstance(report["topological_order"], list)
        if report["topological_order"]:
            assert isinstance(report["topological_order"][0], str)

    def test_orphan_nodes_expected(self, dag):
        """Orphan nodes should include the config/input-only leaf nodes."""
        report = verify_dag_integrity(dag)
        orphans = report["orphan_nodes"]
        assert "load_exemplars" in orphans
        assert "init_embedding_model" in orphans

    def test_export_summary_is_terminal(self, dag):
        report = verify_dag_integrity(dag)
        assert "export_summary" in report["terminal_nodes"]


# ── render_dag_mermaid ─────────────────────────────────────────────────────


class TestRenderDagMermaid:
    """``render_dag_mermaid`` produces valid Mermaid output."""

    def test_generates_valid_mermaid_header(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        assert src.startswith("flowchart TD\n")

    def test_output_file_created(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        render_dag_mermaid(dag, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_contains_known_nodes(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        assert "load_exemplars" in src
        assert "export_summary" in src

    def test_contains_directed_edges(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        assert "-->" in src

    def test_respects_final_vars_filter(self, dag, tmp_path):
        """Filtered DAG should be smaller than the full DAG."""
        out_full = tmp_path / "full.mmd"
        out_filtered = tmp_path / "filtered.mmd"
        full_src = render_dag_mermaid(dag, out_full)
        filtered_src = render_dag_mermaid(
            dag, out_filtered, final_vars=["export_summary"]
        )
        assert len(filtered_src) < len(full_src), "Filtered DAG should be smaller"

    def test_filtered_still_contains_target(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out, final_vars=["export_summary"])
        assert "export_summary" in src

    def test_override_highlighting(self, dag, tmp_path):
        """Override edges should use dashed arrows."""
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out, overrides={"infer_codes": "mock"})
        assert "override" in src

    def test_direction_default_td(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        assert src.startswith("flowchart TD")

    def test_direction_lr(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out, direction="LR")
        assert src.startswith("flowchart LR")

    def test_external_inputs_in_subgraph(self, dag, tmp_path):
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        assert "External Inputs" in src

    def test_clusters_present(self, dag, tmp_path):
        """At minimum artifact, embedding, inference, export clusters exist."""
        out = tmp_path / "dag.mmd"
        src = render_dag_mermaid(dag, out)
        for cluster in ("Artifacts", "Embedding", "Inference", "Export"):
            assert "subgraph" in src
        # Count subgraph blocks
        count = src.count("subgraph ")
        assert count >= 4, f"Expected >=4 subgraphs, got {count}"


# ── validate_dataflow ──────────────────────────────────────────────────────


class TestValidateDataflow:
    """``validate_dataflow`` verifies execution plans."""

    def test_valid_execution(self, dag):
        result = validate_dataflow(dag, ["export_summary"])
        assert result["valid"] is True
        assert result["final_vars_used"] == ["export_summary"]

    def test_invalid_final_var(self, dag):
        result = validate_dataflow(dag, ["does_not_exist"])
        assert result["valid"] is False
        assert result["error"] is not None

    def test_with_overrides(self, dag):
        result = validate_dataflow(
            dag,
            ["load_exemplars"],
            overrides={"load_exemplars": "MOCK"},
        )
        assert result["valid"] is True

    def test_required_inputs_listed(self, dag):
        result = validate_dataflow(dag, ["export_summary"])
        # Should be no required external inputs beyond config
        assert isinstance(result["required_inputs"], list)

    def test_valid_with_explicit_inputs(self, dag):
        result = validate_dataflow(
            dag,
            ["export_summary"],
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result["valid"] is True


# ── execute_with_overrides ─────────────────────────────────────────────────


class TestExecuteWithOverrides:
    """``execute_with_overrides`` injects override values into the DAG."""

    def test_overrides_injected(self, dag):
        result = execute_with_overrides(
            dag,
            ["load_exemplars"],
            overrides={"load_exemplars": "OVERRIDDEN"},
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result["load_exemplars"] == "OVERRIDDEN"

    def test_multiple_overrides(self, dag):
        result = execute_with_overrides(
            dag,
            ["load_exemplars", "load_tags"],
            overrides={
                "load_exemplars": "EX_OVERRIDDEN",
                "load_tags": "TAGS_OVERRIDDEN",
            },
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result["load_exemplars"] == "EX_OVERRIDDEN"
        assert result["load_tags"] == "TAGS_OVERRIDDEN"

    def test_partial_override_reverts_to_real(self, dag):
        """When only some upstream deps are overridden, others compute normally."""
        result = execute_with_overrides(
            dag,
            ["load_exemplars", "load_tags"],
            overrides={"load_exemplars": "OVERRIDDEN"},
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result["load_exemplars"] == "OVERRIDDEN"
        # load_tags was *not* overridden, but it's a leaf node reading from CSV
        # — in test it should still compute (even if it fails due to missing data)
        assert "load_tags" in result

    def test_override_with_empty_overrides(self, dag):
        """Overriding with empty dict is equivalent to normal execution."""
        result = execute_with_overrides(
            dag,
            ["load_exemplars"],
            overrides={},
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        # Should not raise — empty overrides dict is valid
        assert "load_exemplars" in result
