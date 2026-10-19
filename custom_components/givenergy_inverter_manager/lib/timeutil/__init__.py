"""Elapsed-time maths that stays correct across a clock change."""

from .real_time import elapsed_seconds, local_time_on, real_time_after, shift_real

__all__ = ["elapsed_seconds", "local_time_on", "real_time_after", "shift_real"]
