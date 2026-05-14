"""Shared test utilities for unit tests.

Provides autopatch() — a drop-in wrapper around unittest.mock.patch
with autospec=True by default.
"""

import warnings
from unittest import mock

warnings.filterwarnings("ignore", message=".*unauthenticated.*")


def autopatch(target, **kwargs):
    """Patch *target* with autospec=True unless explicitly overridden.

    Accepts all the same arguments from unittest.mock.patch (new, spec,
    create, etc.). If *autospec* is not provided, defaults to True.
    """
    kwargs.setdefault("autospec", True)
    return mock.patch(target, **kwargs)
