"""alert.py: what a caller does with a repair issue this cycle."""

from enum import StrEnum


class AlertAction(StrEnum):
    """What the caller does with the alert this cycle."""

    NONE = "none"
    RAISE = "raise"
    CLEAR = "clear"
