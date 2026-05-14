"""Constants and DDL for the inference_status table.

Status lifecycle for each ``(entity_id, entity_type, stage)``::

    pending  --[infer]-->  generated  --[approve]-->  approved
                                  ^                       |
                                  |                   [edit]
                                  |                       v
                                  |                    draft
                                  |                       |
                                  +----[re-infer]---------+

    generated --[reject]--> rejected
    draft     --[edit]-->   draft (attempts++)

References:
    ADR-007 (Incremental Evolution): dirty-state propagation
    Feature 36 (incremental-inference-tracker)
"""

# -- Status constants ---------------------------------------------------------

PENDING = "pending"
GENERATED = "generated"
APPROVED = "approved"
REJECTED = "rejected"
DRAFT = "draft"

ALL_STATUSES = {PENDING, GENERATED, APPROVED, REJECTED, DRAFT}
PENDING_STATUSES = {PENDING, DRAFT}

# -- Stage constants ----------------------------------------------------------

STAGE_CODE = "code"
STAGE_THEME = "theme"
STAGE_INTERPRETATION = "interpretation"

ALL_STAGES = {STAGE_CODE, STAGE_THEME, STAGE_INTERPRETATION}

# -- Entity type constants ----------------------------------------------------

ENTITY_EXEMPLAR = "exemplar"
ENTITY_CODE = "code"
ENTITY_THEME = "theme"
ENTITY_INTERPRETATION = "interpretation"

ALL_ENTITY_TYPES = {ENTITY_EXEMPLAR, ENTITY_CODE, ENTITY_THEME, ENTITY_INTERPRETATION}

# -- Validation --------------------------------------------------------------


def _validate_params(
    entity_id: str,
    entity_type: str,
    stage: str,
    status: str,
) -> None:
    """Validate function arguments and raise ValueError on invalid input."""
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError(f"entity_id must be a non-empty string, got {entity_id!r}")
    if entity_type not in ALL_ENTITY_TYPES:
        raise ValueError(
            f"entity_type must be one of {sorted(ALL_ENTITY_TYPES)}, "
            f"got {entity_type!r}"
        )
    if stage not in ALL_STAGES:
        raise ValueError(
            f"stage must be one of {sorted(ALL_STAGES)}, " f"got {stage!r}"
        )
    if status not in ALL_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(ALL_STATUSES)}, " f"got {status!r}"
        )


# -- Table DDL ----------------------------------------------------------------

INFERENCE_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS inference_status (
    entity_id VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,
    stage VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'pending',
    last_attempt_at TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    PRIMARY KEY (entity_id, entity_type, stage)
);
"""

__all__ = [
    "PENDING",
    "GENERATED",
    "APPROVED",
    "REJECTED",
    "DRAFT",
    "ALL_STATUSES",
    "PENDING_STATUSES",
    "STAGE_CODE",
    "STAGE_THEME",
    "STAGE_INTERPRETATION",
    "ALL_STAGES",
    "ENTITY_EXEMPLAR",
    "ENTITY_CODE",
    "ENTITY_THEME",
    "ENTITY_INTERPRETATION",
    "ALL_ENTITY_TYPES",
    "INFERENCE_STATUS_DDL",
    "_validate_params",
]
