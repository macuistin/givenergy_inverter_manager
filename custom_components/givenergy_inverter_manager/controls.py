"""
controls.py - the tuning controls: switches and numbers that each own one saved option.

A setting is either a form field (set once, changes rarely) or a control (a knob the user tries,
watches and adjusts), never both. The seven controls here write the flat option key they were
always stored under, so no data moves and an install keeps the value it had:

  switches  dry_run, verbose_logging
  numbers   surplus_divert_soc_pct, surplus_divert_min_power_w, cheap_rate_floor_soc,
            skip_charge_soc_threshold_pct, forecast_conservatism

The unique id is "{entry_id}_{key}" and the translation key is the option key. A control shows
the value in force (saved options over setup data, else the default), so a change made anywhere
shows on the next refresh. Writing one is a read-modify-write of the entry's current options
that touches only its own key. core/reload_policy.py lists every key as live, so a write never
reloads the integration. The coordinator re-reads the merged config on every cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from .config_helpers import effective_config
from .const import (
    CONF_CHEAP_RATE_FLOOR_SOC,
    CONF_DRY_RUN,
    CONF_FORECAST_CONSERVATISM,
    CONF_SKIP_CHARGE_SOC_THRESHOLD,
    CONF_SURPLUS_DIVERT_MIN_W,
    CONF_SURPLUS_DIVERT_SOC,
    CONF_VERBOSE_LOGGING,
    DEFAULT_CHEAP_RATE_FLOOR_SOC,
    DEFAULT_DRY_RUN,
    DEFAULT_FORECAST_CONSERVATISM,
    DEFAULT_SKIP_CHARGE_SOC_THRESHOLD,
    DEFAULT_VERBOSE_LOGGING,
    DOMAIN,
    SURPLUS_DIVERT_MIN_POWER_W,
    SURPLUS_DIVERT_SOC_THRESHOLD,
)
from .coordinator import GivEnergyConfigEntry, GivEnergyCoordinator
from .core.devices import Device
from .entity import GivEnergyEntity
from .logging import get_logger

_LOG = get_logger(__name__)

TEST_INSTANCE_LOCKED = "test_instance_dry_run_locked"


@callback
def async_set_option(
    hass: HomeAssistant, entry: GivEnergyConfigEntry, key: str, value: Any
) -> None:
    """Save one option. Reads the entry's current options and replaces only *key*.

    Never pass a copy taken earlier: another control or the options form may have saved a
    different key since, and a stale copy would write it back.
    """
    hass.config_entries.async_update_entry(entry, options={**entry.options, key: value})


@dataclass(frozen=True)
class NumberSpec:
    """The range, unit and default of one number control."""

    key: str
    default: float
    low: float
    high: float
    step: float
    unit: str | None = None
    device_class: NumberDeviceClass | None = None
    mode: NumberMode = NumberMode.BOX
    decimals: int = 0
    # The optional device the control is about. None means every install has it.
    requires: Device | None = None

    def stored(self, value: float) -> int | float:
        """The value as saved: a whole number, or rounded to the step's decimals."""
        return int(round(value)) if self.decimals == 0 else round(float(value), self.decimals)


NUMBER_SPECS: tuple[NumberSpec, ...] = (
    NumberSpec(
        CONF_SURPLUS_DIVERT_SOC,
        SURPLUS_DIVERT_SOC_THRESHOLD,
        50,
        100,
        5,
        PERCENTAGE,
        mode=NumberMode.SLIDER,
        requires=Device.IMMERSION_SWITCH,
    ),
    NumberSpec(
        CONF_SURPLUS_DIVERT_MIN_W,
        SURPLUS_DIVERT_MIN_POWER_W,
        100,
        2000,
        100,
        UnitOfPower.WATT,
        NumberDeviceClass.POWER,
        NumberMode.SLIDER,
        requires=Device.IMMERSION_SWITCH,
    ),
    NumberSpec(
        CONF_CHEAP_RATE_FLOOR_SOC,
        DEFAULT_CHEAP_RATE_FLOOR_SOC,
        0,
        80,
        5,
        PERCENTAGE,
        mode=NumberMode.SLIDER,
    ),
    NumberSpec(
        CONF_SKIP_CHARGE_SOC_THRESHOLD, DEFAULT_SKIP_CHARGE_SOC_THRESHOLD, 20, 100, 1, PERCENTAGE
    ),
    NumberSpec(
        CONF_FORECAST_CONSERVATISM, DEFAULT_FORECAST_CONSERVATISM, 0.0, 1.0, 0.05, decimals=2
    ),
)


class ControlEntity(GivEnergyEntity):
    """Shared base of the controls: one saved option, shown as it is in force."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GivEnergyCoordinator, key: str, default: Any) -> None:
        super().__init__(coordinator)
        self._option_key = key
        self._default = default
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_translation_key = key

    def _in_force(self) -> Any:
        """The value in force: saved options over setup data, else the default."""
        return effective_config(self.coordinator.entry).get(self._option_key, self._default)

    def _save(self, value: Any) -> None:
        """Write the option, show the new value now and let the coordinator pick it up."""
        async_set_option(self.hass, self.coordinator.entry, self._option_key, value)
        self.async_write_ha_state()


class ControlNumber(ControlEntity, NumberEntity):
    """A number control. Its range and unit come from its NumberSpec."""

    def __init__(self, coordinator: GivEnergyCoordinator, spec: NumberSpec) -> None:
        super().__init__(coordinator, spec.key, spec.default)
        self._spec = spec
        self._attr_native_min_value = spec.low
        self._attr_native_max_value = spec.high
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_device_class = spec.device_class
        self._attr_mode = spec.mode

    @property
    def native_value(self) -> float:
        try:
            return float(self._in_force())
        except (TypeError, ValueError):
            _LOG.warning("Ignoring the saved %s, which is not a number", self._option_key)
            return float(self._spec.default)

    async def async_set_native_value(self, value: float) -> None:
        self._save(self._spec.stored(value))


class ControlSwitch(ControlEntity, SwitchEntity):
    """A switch control that owns one boolean option."""

    @property
    def is_on(self) -> bool:
        return bool(self._in_force())

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._save(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._save(False)


class DryRunSwitch(ControlSwitch):
    """Dry run: decisions and sensors carry on, no command is sent to the hardware.

    It shows the coordinator's own answer, so it reads on whenever the test instance marker
    file forces dry run. Under the marker it cannot be turned off, and nothing the user does
    can leave the marker's guard.
    """

    def __init__(self, coordinator: GivEnergyCoordinator) -> None:
        super().__init__(coordinator, CONF_DRY_RUN, DEFAULT_DRY_RUN)

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_dry_run

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return {"test_instance": True} if self.coordinator.test_instance else None

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.coordinator.test_instance:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key=TEST_INSTANCE_LOCKED
            )
        await super().async_turn_off(**kwargs)


def control_switches(coordinator: GivEnergyCoordinator) -> list[ControlSwitch]:
    """The two switch controls."""
    return [
        DryRunSwitch(coordinator),
        ControlSwitch(coordinator, CONF_VERBOSE_LOGGING, DEFAULT_VERBOSE_LOGGING),
    ]


def control_numbers(
    coordinator: GivEnergyCoordinator, requires: Device | None = None
) -> list[ControlNumber]:
    """The number controls that need *requires*, or that every install has when it is None.

    The two immersion divert thresholds only act on an immersion switch, so they exist while
    one is set, like the other immersion entities.
    """
    return [ControlNumber(coordinator, s) for s in NUMBER_SPECS if s.requires == requires]
