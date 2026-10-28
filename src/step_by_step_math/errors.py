"""Errors whose message is short, actionable and safe to show to the model."""


class UserFacingError(Exception):
    """Base class: the server turns these into a ToolError with the same message."""
