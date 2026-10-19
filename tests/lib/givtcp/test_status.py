"""WriteStatus: which results count as a success and which say the inverter holds the value."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp.status import WriteStatus


@pytest.mark.parametrize(
    ("status", "truthy", "confirmed", "sent"),
    [
        (WriteStatus.ALREADY_SET, True, True, False),
        (WriteStatus.WRITTEN, True, True, True),
        (WriteStatus.UNCONFIRMED, True, False, True),
        (WriteStatus.COOLDOWN, True, False, False),
        (WriteStatus.REFUSED, False, False, False),
        (WriteStatus.FAILED, False, False, False),
    ],
)
def test_each_status_says_what_it_proves(status, truthy, confirmed, sent):
    assert (bool(status), status.confirmed, status.sent) == (truthy, confirmed, sent)
