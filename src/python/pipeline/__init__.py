"""Pipeline orchestration — Hamilton DAG node functions, constructor, and executor.

Modules:
    constructor: create_pipeline(config) -> Builder
    config: Config frozen dataclass
    dirty: Dirty flag propagation for incremental recomputation
    executor: execute_dag() with stage awareness and node execution logging
    stages: Workflow stage -> final_vars mapping (get_final_vars_for_stage)
    types: NodeExecutionRecord, ExecutionResult, get_execution_summary
    wiring: DAG validation, override execution, Mermaid visualization
    nodes: 50 node functions across 7 submodules (artifact, embedding, export,
           index, inference, retrieval, review)
"""
