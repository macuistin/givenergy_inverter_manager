"""The integration works in Home Assistant's local time, not UTC.

Rate periods are written as local clock times. Read in UTC they would start an hour late in
an Irish summer, and the daily accumulators would reset at 01:00 local.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import Scenario

# 22:30 UTC on a July evening is 23:30 in Dublin, inside the default Night period (23:00 to
# 08:00). Read as UTC it would still be the Day rate.
SUMMER_NIGHT = Scenario(
    name="summer_late_evening",
    frozen_utc="2026-07-10 22:30:00+00:00",
    solar_w=0.0,
    battery_soc=55.0,
    battery_w=0.0,
    grid_w=-400.0,
    load_w=400.0,
)


@pytest.fixture
def scenario():
    return SUMMER_NIGHT


async def test_the_rate_period_follows_the_local_clock(loaded_entry):
    coordinator = loaded_entry.runtime_data

    assert coordinator._now().utcoffset() == timedelta(hours=1)
    assert coordinator.data.current_rate_name == "Night"


async def test_midnight_reset_is_stamped_at_local_midnight(hass, loaded_entry):
    coordinator = loaded_entry.runtime_data

    # 23:00 UTC is midnight in Dublin, the start of 11 July.
    coordinator._midnight_reset(datetime(2026, 7, 10, 23, 0, tzinfo=timezone.utc))
    await hass.async_block_till_done()

    assert coordinator._last_reset_time == "2026-07-11T00:00:00+01:00"
