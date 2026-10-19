"""Re-export of lib/guards so existing imports keep working. Import from lib/ in new code."""

from ..lib.givtcp.freshness import (
    frozen_age_s,
    newest_report,
)

__all__ = [
    "frozen_age_s",
    "newest_report",
]
