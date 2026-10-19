"""Re-export of lib/givtcp so existing imports keep working. Import from lib/ in new code."""

from ...lib.givtcp.reader import (
    PAUSED_STATUS,
    GetState,
    GivTCPReader,
)

__all__ = [
    "GetState",
    "GivTCPReader",
    "PAUSED_STATUS",
]
