"""Shared test utilities for unit tests.

Provides autopatch() — a drop-in wrapper around unittest.mock.patch
with autospec=True by default.
"""

from unittest import mock


def autopatch(target, **kwargs):
    """Patch *target* with autospec=True unless explicitly overridden.

    Accepts all the same arguments as unittest.mock.patch (new, spec,
    create, etc.). If *autospec* is not provided, defaults to True.
    """
    kwargs.setdefault("autospec", True)
    return mock.patch(target, **kwargs)
