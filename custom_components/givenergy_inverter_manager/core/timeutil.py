"""Re-export of lib/timeutil so existing imports keep working. Import from lib/ in new code."""

from ..lib.timeutil import elapsed_seconds, local_time_on, real_time_after, shift_real

__all__ = ["elapsed_seconds", "local_time_on", "real_time_after", "shift_real"]
