"""Tests for selective DAG execution (Feature 56).

Verifies stage-to-final-vars resolution, execution plan enumeration,
per-node execution records, and the full ``execute_dag()`` lifecycle.
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
from pipeline.executor import execute_dag  # noqa: E402
from pipeline.stages import get_final_vars_for_stage  # noqa: E402
from pipeline.types import (  # noqa: E402
    ExecutionResult,
    NodeExecutionRecord,
    get_execution_summary,
)
from pipeline.wiring import EXTERNAL_INPUTS  # noqa: E402

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dag():
    """Build the DAG once per module using env-var defaults."""
    config = Config.from_env()
    return create_pipeline(config).build()


# ── Stage → final_vars ──────────────────────────────────────────────────────


class TestStageFinalVars:
    """``get_final_vars_for_stage`` returns cumulative output node lists."""

    def test_stage_1_contains_load_nodes(self):
        vars_ = set(get_final_vars_for_stage(1))
        assert "load_exemplars" in vars_
        assert "load_tags" in vars_
        assert "load_keywords" in vars_
        assert "resolve_tag_dag" in vars_
        assert "validate_artifact_schemas" in vars_
        assert "compute_exemplar_statistics" in vars_
        assert "prepare_artifact_summary" in vars_
        # No inference or export nodes in stage 1
        assert "infer_codes" not in vars_
        assert "export_summary" not in vars_

    def test_stage_10_cumulative_includes_all(self):
        """Stage 10 should contain every terminal output from every prior stage."""
        vars_ = set(get_final_vars_for_stage(10))
        # Stage 1
        assert "load_exemplars" in vars_
        # Stage 2
        assert "cache_exemplar_embeddings" in vars_
        assert "verify_embedding_integrity" in vars_
        # Stage 3
        assert "build_ontology_graph" in vars_
        assert "build_bm25" in vars_
        # Stage 4
        assert "infer_codes" in vars_
        assert "prepare_code_nodes" in vars_
        # Stage 5
        assert "review_codes" in vars_
        # Stage 6
        assert "infer_themes" in vars_
        # Stage 7
        assert "review_themes" in vars_
        # Stage 8
        assert "infer_interpretations" in vars_
        # Stage 9
        assert "review_interpretations" in vars_
        # Stage 10
        assert "export_summary" in vars_
        assert "export_combined" in vars_

    def test_stage_4_includes_infer_codes(self):
        vars_ = set(get_final_vars_for_stage(4))
        assert "infer_codes" in vars_
        assert "prepare_code_nodes" in vars_
        # Prior stage outputs should also be present
        assert "load_exemplars" in vars_
        assert "cache_exemplar_embeddings" in vars_
        assert "build_ontology_graph" in vars_

    def test_invalid_stage_below_1_raises(self):
        with pytest.raises(ValueError, match="Unknown stage"):
            get_final_vars_for_stage(0)

    def test_invalid_stage_above_10_raises(self):
        with pytest.raises(ValueError, match="Unknown stage"):
            get_final_vars_for_stage(11)

    def test_cumulative_superset(self):
        """Each stage's variables are a superset of the previous stage's."""
        for stage in range(2, 11):
            prev = set(get_final_vars_for_stage(stage - 1))
            curr = set(get_final_vars_for_stage(stage))
            assert prev.issubset(curr), (
                f"Stage {stage - 1} vars not subset of stage {stage}. "
                f"Missing: {prev - curr}"
            )


# ── execute_dag validation ──────────────────────────────────────────────────


class TestExecuteDagValidation:
    """Argument validation for ``execute_dag``."""

    def test_requires_final_vars_or_stage(self):
        with pytest.raises(ValueError, match="Either final_vars or stage"):
            execute_dag(None, final_vars=None, stage=None)  # type: ignore[arg-type]

    def test_mutual_exclusion(self):
        with pytest.raises(ValueError, match="Only one of final_vars or stage"):
            execute_dag(
                None,  # type: ignore[arg-type]
                final_vars=["load_exemplars"],
                stage=1,
            )


# ── execute_dag execution ───────────────────────────────────────────────────


class TestExecuteDag:
    """``execute_dag`` produces correct outputs and execution records."""

    def test_basic_execution_with_override(self, dag):
        """Override a leaf node and verify the output is returned."""
        result = execute_dag(
            dag,
            final_vars=["load_exemplars"],
            overrides={"load_exemplars": "MOCK"},
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result.outputs["load_exemplars"] == "MOCK"
        assert result.total_duration_ms > 0
        assert result.stage is None

    def test_execution_with_stage_param(self, dag):
        """Using ``stage`` parameter resolves and computes cumulative vars."""
        overrides = {v: f"MOCK_{v}" for v in get_final_vars_for_stage(1)}
        result = execute_dag(
            dag,
            stage=1,
            overrides=overrides,
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result.stage == 1
        for var in get_final_vars_for_stage(1):
            assert var in result.outputs, f"Missing output: {var}"
            assert result.outputs[var] == f"MOCK_{var}"

    def test_stage_param_equivalent_to_final_vars(self, dag):
        """Passing ``stage=1`` yields the same outputs as ``final_vars=stage1_vars``."""
        stage1_vars = get_final_vars_for_stage(1)
        overrides = {v: f"MOCK_{v}" for v in stage1_vars}
        inputs = {
            "existing_codes": [],
            "existing_theme_nodes": [],
            "tag_metadata": {},
        }
        result_by_stage = execute_dag(dag, stage=1, overrides=overrides, inputs=inputs)
        result_by_vars = execute_dag(
            dag, final_vars=stage1_vars, overrides=overrides, inputs=inputs
        )
        assert result_by_stage.outputs == result_by_vars.outputs
        # Stage field differs — that's expected
        assert result_by_stage.stage == 1
        assert result_by_vars.stage is None

    def test_with_overrides_marks_overridden(self, dag):
        """Overridden nodes should have ``overridden`` status in execution records."""
        override_map = {"load_exemplars": "MOCK"}
        result = execute_dag(
            dag,
            final_vars=["load_exemplars"],
            overrides=override_map,
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        records_by_name = {r.node_name: r for r in result.node_executions}
        assert "load_exemplars" in records_by_name
        assert records_by_name["load_exemplars"].status == "overridden"

    def test_execution_result_structure(self, dag):
        """Result should be an ``ExecutionResult`` with expected fields."""
        result = execute_dag(
            dag,
            final_vars=["load_exemplars"],
            overrides={"load_exemplars": "MOCK"},
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert isinstance(result, ExecutionResult)
        assert hasattr(result, "outputs")
        assert hasattr(result, "node_executions")
        assert hasattr(result, "total_duration_ms")
        assert hasattr(result, "stage")
        assert hasattr(result, "cache_hit_count")
        assert hasattr(result, "cache_miss_count")

    def test_execution_records_count(self, dag):
        """Number of records should match the number of expected nodes."""
        result = execute_dag(
            dag,
            final_vars=["load_exemplars", "load_tags"],
            overrides={
                "load_exemplars": "MOCK_EX",
                "load_tags": "MOCK_TAG",
            },
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        # At minimum the two requested nodes should have records
        record_names = {r.node_name for r in result.node_executions}
        assert "load_exemplars" in record_names
        assert "load_tags" in record_names


class TestExecuteDagStage4:
    """Execute a multi-stage pipeline (stage 4) to verify transitive deps."""

    def test_stage_4_override_all(self, dag):
        """All stage 4 outputs can be overridden and execution succeeds."""
        stage4_vars = get_final_vars_for_stage(4)
        overrides = {v: f"MOCK_{v}" for v in stage4_vars}
        result = execute_dag(
            dag,
            stage=4,
            overrides=overrides,
            inputs={
                "existing_codes": [],
                "existing_theme_nodes": [],
                "tag_metadata": {},
            },
        )
        assert result.stage == 4
        for var in stage4_vars:
            assert var in result.outputs, f"Missing output: {var}"
            # Check that the execution record status is "overridden"
            records_by_name = {r.node_name: r for r in result.node_executions}
            assert records_by_name[var].status == "overridden"


# ── Execution summary ───────────────────────────────────────────────────────


class TestExecutionSummary:
    """``get_execution_summary`` produces correct statistics."""

    def test_summary_counts(self):
        result = ExecutionResult(
            outputs={},
            node_executions=[
                NodeExecutionRecord("a", "executed"),
                NodeExecutionRecord("b", "executed"),
                NodeExecutionRecord("c", "overridden"),
                NodeExecutionRecord("d", "skipped"),
            ],
            stage=3,
        )
        summary = get_execution_summary(result)
        assert summary["executed"] == 2
        assert summary["overridden"] == 1
        assert summary["skipped"] == 1
        assert summary["cached"] == 0
        assert summary["total_nodes"] == 4
        assert summary["stage"] == 3

    def test_summary_cache_hit_rate_zero_when_no_calls(self):
        result = ExecutionResult(
            outputs={},
            node_executions=[],
            cache_hit_count=0,
            cache_miss_count=0,
        )
        summary = get_execution_summary(result)
        assert summary["cache_hit_rate"] == 0.0

    def test_summary_cache_hit_rate_partial(self):
        result = ExecutionResult(
            outputs={},
            node_executions=[],
            cache_hit_count=9,
            cache_miss_count=1,
        )
        summary = get_execution_summary(result)
        assert summary["cache_hit_rate"] == 0.9


# ── All nodes covered by stages ─────────────────────────────────────────────


class TestDagCoverage:
    """Every DAG node must be reachable through at least one stage's plan."""

    def test_all_pipeline_nodes_covered(self, dag):
        """All non-external DAG nodes appear in at least one stage's execution plan."""
        all_dag_nodes: set[str] = set()
        for node in dag.graph.get_nodes():
            if node.name not in EXTERNAL_INPUTS:
                all_dag_nodes.add(node.name)

        all_planned: set[str] = set()
        for stage in range(1, 11):
            stage_vars = get_final_vars_for_stage(stage)
            plan, _ = dag.graph.get_upstream_nodes(stage_vars)
            all_planned.update(n.name for n in plan)
            all_planned.update(stage_vars)

        uncovered = all_dag_nodes - all_planned
        assert not uncovered, (
            f"{len(uncovered)} DAG nodes not covered by any stage's "
            f"execution plan: {sorted(uncovered)}"
        )
