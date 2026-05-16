"""TUI action handler wrappers.

These wrappers bridge Textual keybindings to the existing
hitl.action handler functions.  Each wrapper validates the
current entity and dispatches to the appropriate handler
based on entity_type.
"""
