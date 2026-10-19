"""Re-export of lib/givtcp so existing imports keep working. Import from lib/ in new code."""

from ...lib.givtcp import GetState
from ...lib.givtcp.reader import (
    PAUSED_STATUS,
    GivTCPReader,
)

__all__ = [
    "GetState",
    "GivTCPReader",
    "PAUSED_STATUS",
]
