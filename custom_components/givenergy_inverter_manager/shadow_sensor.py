"""
shadow_sensor.py - the sensors of the shadow tariffs, on their own Shadow tariffs device.

For each shadow tariff there are three entities: its bill so far this bill period, the difference
from the active tariff's bill over the same days, and whether it would have been cheaper. Every
figure is a re-pricing of usage the inverter already measured. These entities only read the
report the coordinator keeps. They are on as soon as a shadow tariff is set up.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import SensorEntity

from .const import DEFAULT_CURRENCY_SYMBOL
from .core.devices import DeviceGroup
from .core.shadow_pricing import ShadowBill, ShadowReport, bands_table
from .entity import GivEnergyEntity


def _symbol(coordinator: Any) -> str:
    data = coordinator.data
    return DEFAULT_CURRENCY_SYMBOL if data is None else str(data.currency_symbol)


RE_PRICED = "Re-priced from measured usage. Not a bill."


class ShadowEntity(GivEnergyEntity):
    """One figure of one shadow tariff."""

    _suffix = ""  # ends the unique id
    _label = ""  # follows the tariff's name in the entity's name

    def __init__(self, coordinator: Any, key: str, tariff: str) -> None:
        super().__init__(coordinator, DeviceGroup.SHADOW_TARIFFS)
        self._key = key
        self._attr_name = f"{tariff} {self._label}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_shadow_{key}_{self._suffix}"

    def _report(self) -> ShadowReport | None:
        data = self.coordinator.data
        return None if data is None else data.shadow_report

    def _bill(self) -> ShadowBill | None:
        report = self._report()
        if report is None:
            return None
        return next((bill for bill in report.bills if bill.key == self._key), None)

    @property
    def available(self) -> bool:
        return bool(self.coordinator.last_update_success) and self._bill() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        report, bill = self._report(), self._bill()
        if report is None or bill is None:
            return None
        return {
            "note": RE_PRICED,
            "bill_period_start": report.first_day.isoformat(),
            "priced_through": report.through.isoformat(),
            "days_priced": report.days,
            "days_in_bill_period": report.period_days,
            "days_with_data": bill.days_recorded,
            "bands_table": bands_table(bill, _symbol(self.coordinator)),
            "would_be_cheaper": "Yes" if bill.difference < 0 else "No",
            "data_from": bill.data_from.isoformat() if bill.data_from else None,
            "data_coverage": round(bill.coverage, 2),
            "active_tariff_total": round(report.active_total, 2),
            "shadow_tariff_total": round(bill.total, 2),
        }


class ShadowMoneyEntity(ShadowEntity, SensorEntity):
    """A shadow figure in the currency of the bill."""

    @property
    def native_unit_of_measurement(self) -> str:
        data = self.coordinator.data
        return DEFAULT_CURRENCY_SYMBOL if data is None else str(data.currency_symbol)


class ShadowBillSensor(ShadowMoneyEntity):
    """What this bill period's usage would cost under the shadow tariff."""

    _suffix = "bill"
    _label = "bill so far"

    @property
    def native_value(self) -> float | None:
        bill = self._bill()
        return None if bill is None else round(bill.total, 2)


class ShadowDifferenceSensor(ShadowMoneyEntity):
    """The shadow tariff's bill less the active tariff's: positive means the shadow costs more."""

    _suffix = "difference"
    _label = "difference from your tariff"

    @property
    def native_value(self) -> float | None:
        bill = self._bill()
        return None if bill is None else round(bill.difference, 2)


class ShadowCheaperSensor(ShadowEntity, BinarySensorEntity):
    """On while the shadow tariff would have cost less than the active one so far."""

    _suffix = "cheaper"
    _label = "would be cheaper so far"

    @property
    def is_on(self) -> bool | None:
        bill = self._bill()
        return None if bill is None else bill.difference < 0
