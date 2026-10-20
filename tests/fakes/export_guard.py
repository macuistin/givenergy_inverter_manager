"""A backend wrapper that fails when the integration reaches for anything that exports.

The GivTCP client can write a discharge schedule, a timed force and the Timed Export mode, for
other hosts of the client. This integration must never use them. The coordinator is typed against
InverterBackend and InverterControls, which hold none of them, and this wrapper turns a call
that goes round those types into a test failure. FakeCoordinator wraps its backend in it, so
every coordinator test runs behind the guard.
"""

from __future__ import annotations

from typing import Any

from custom_components.givenergy_inverter_manager.lib.givtcp import (
    BatteryMode,
    GivTCPForce,
    GivTCPSchedules,
    SelfUseMode,
)


def _public(cls: type) -> set[str]:
    return {name for name in dir(cls) if not name.startswith("_")}


# The client's own names, less the ones the integration's interfaces share with it.
_FORBIDDEN = (
    _public(GivTCPSchedules) | _public(GivTCPForce) | {"schedules", "force", "controls"}
) - {"apply_battery_mode"}  # the mode method is shared, and checked by its argument below
_SELF_USE = {mode.value for mode in SelfUseMode}


class IntegrationExported(AssertionError):
    """The integration used something that can send power to the grid."""


class ExportGuard:
    """Passes everything through to the backend except the export surface."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    def __getattr__(self, name: str) -> Any:
        if name in _FORBIDDEN:
            raise IntegrationExported(f"the integration reached for backend.{name}")
        attribute = getattr(self._backend, name)
        return self._checked_mode(attribute) if name == "apply_battery_mode" else attribute

    @staticmethod
    def _checked_mode(apply: Any) -> Any:
        async def apply_battery_mode(cfg: Any, mode: Any) -> Any:
            if str(mode) not in _SELF_USE or mode == BatteryMode.TIMED_EXPORT:
                raise IntegrationExported(f"the integration asked for battery mode {mode!r}")
            return await apply(cfg, mode)

        return apply_battery_mode

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_backend":
            object.__setattr__(self, name, value)
        else:
            setattr(self._backend, name, value)
