---
title: "Utils Layer"
description: "Shared utility modules: logging and error handling"
updated_at: "2026-05-12"
---

# Utils Layer

Provides core utility services used across all layers of the thematic analysis pipeline.

## Modules

- **Logging** (`@src/python/utils/logging.py`): Centralized structured logging with JSON formatting and sensitive data redaction.
- **Error Handling** (`@src/python/utils/`): Robust resilience patterns.
  - **Exceptions** (`@src/python/utils/exceptions.py`): Domain-specific exception classes.
  - **Retry** (`@src/python/utils/retry.py`): Exponential backoff decorator.
  - **Circuit Breaker** (`@src/python/utils/circuit_breaker.py`): Fail-fast mechanism.
  - **Graceful Shutdown** (`@src/python/utils/graceful_shutdown.py`): Signal-aware cleanup manager.

## Usage

Most utilities are exposed through the `utils` package entry point:

```python
from utils import (
    get_logger,
    make_retry,
    make_circuit_breaker,
    graceful_shutdown,
    GroqAPIError,
)
```

## Integration

- **Orchestration Layer**: Uses `graceful_shutdown` to handle user interrupts and `get_logger` for workflow visibility.
- **Inference Layer**: Uses `make_retry` for robust Groq API interaction and `make_circuit_breaker` for service resilience.
- **Persistence Layer**: Uses `get_logger` for auditing and error reporting.
