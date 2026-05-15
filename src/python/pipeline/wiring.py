"""DAG validation and override execution for Hamilton pipelines.

All functions operate on an already-built ``Driver``.  Fully optional —
``constructor.create_pipeline()`` does not depend on this module.
"""

from __future__ import annotations

from typing import Any, cast

from hamilton.driver import Driver

EXTERNAL_INPUTS = frozenset(
    {
        "config",
        "existing_codes",
        "existing_theme_nodes",
        "tag_metadata",
        "dirty_flags",
    }
)


def verify_dag_integrity(driver: Driver) -> dict[str, Any]:
    """Return a structured report of DAG structural health.

    Returns a dict with 10 keys: ``node_count``, ``has_cycles``, ``cycles``,
    ``all_deps_resolved``, ``missing_deps``, ``config_injected_in_all_nodes``,
    ``nodes_without_config``, ``topological_order``, ``orphan_nodes``,
    ``terminal_nodes``.

    Parameters
    ----------
    driver :
        Built Hamilton driver.

    Returns
    -------
    dict
        Structured health report.
    """
    fg = driver.graph
    nodes = fg.get_nodes()
    all_names = {n.name for n in nodes}
    user_nodes = [n for n in nodes if n.name not in EXTERNAL_INPUTS]

    cycles = fg.get_cycles(nodes, [])
    has_cycles = len(cycles) > 0

    missing_deps: list[tuple[str, str]] = []
    nodes_without_config: list[str] = []
    for node in user_nodes:
        for dep_name in node.input_types:
            if dep_name == "config":
                continue
            if dep_name not in all_names:
                missing_deps.append((node.name, dep_name))
        if "config" not in node.input_types:
            nodes_without_config.append(node.name)

    topological_order = [n.name for n in nodes if n.name not in EXTERNAL_INPUTS]

    orphan_nodes: list[str] = []
    for node in user_nodes:
        deps = {d for d in node.input_types if d not in EXTERNAL_INPUTS}
        if not deps:
            orphan_nodes.append(node.name)

    downstream_counts: dict[str, int] = {n.name: 0 for n in user_nodes}
    for node in user_nodes:
        for dep_name in node.input_types:
            if dep_name in downstream_counts:
                downstream_counts[dep_name] += 1
    terminal_nodes = [name for name, count in downstream_counts.items() if count == 0]

    return {
        "node_count": len(user_nodes),
        "has_cycles": has_cycles,
        "cycles": cycles,
        "all_deps_resolved": len(missing_deps) == 0,
        "missing_deps": missing_deps,
        "config_injected_in_all_nodes": len(nodes_without_config) == 0,
        "nodes_without_config": nodes_without_config,
        "topological_order": topological_order,
        "orphan_nodes": sorted(orphan_nodes),
        "terminal_nodes": sorted(terminal_nodes),
    }


def validate_dataflow(
    driver: Driver,
    final_vars: list[str],
    *,
    inputs: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify the execution plan for *final_vars* is valid.

    Wraps ``Driver.validate_execution()``.  Returns a dict with keys
    ``valid`` (bool), ``final_vars_used``, ``error`` (str | None),
    ``required_inputs`` (list[str]).

    Parameters
    ----------
    driver :
        Built Hamilton driver.
    final_vars :
        Output node(s) to validate.
    inputs :
        External input values.
    overrides :
        Node overrides (same semantics as ``Driver.execute(overrides=...)``).

    Returns
    -------
    dict
        Structured validation result.
    """
    result: dict[str, Any] = {
        "valid": False,
        "final_vars_used": final_vars,
        "error": None,
        "required_inputs": [],
    }

    try:
        driver.validate_execution(final_vars, overrides=overrides, inputs=inputs)
        result["valid"] = True
    except Exception as exc:
        result["error"] = str(exc)
        return result

    needed_inputs: set[str] = set()
    for node in driver.graph.get_nodes():
        if node.name not in final_vars:
            continue
        for dep_name in node.input_types:
            if dep_name in EXTERNAL_INPUTS and dep_name != "config":
                needed_inputs.add(dep_name)

    if inputs:
        needed_inputs -= set(inputs)
    result["required_inputs"] = sorted(needed_inputs)
    return result


def execute_with_overrides(
    driver: Driver,
    final_vars: list[str],
    overrides: dict[str, Any],
    *,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the DAG with overridden node values.

    Thin wrapper around ``Driver.execute(overrides=...)`` for tests and
    controlled production runs.

    Parameters
    ----------
    driver :
        Built Hamilton driver.
    final_vars :
        Output node(s) to compute.
    overrides :
        Mapping of node name -> replacement value.
    inputs :
        External input values.

    Returns
    -------
    dict
        Computed outputs keyed by node name.
    """
    return cast(
        dict[str, Any],
        driver.execute(
            final_vars=final_vars,
            overrides=overrides,
            inputs=inputs,
        ),
    )
