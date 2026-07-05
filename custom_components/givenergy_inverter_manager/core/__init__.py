"""
core/ — Pure Python logic layer for GivEnergy Inverter Manager.

No Home Assistant imports anywhere in this package. Every module is fully
testable with plain pytest and no HA fixtures.

Modules:
  tariff    — TariffConfig, EnergyAccumulator, rate periods
  battery   — BatteryStats, cycle tracking, night survival prediction
  rules     — Decision functions: charge target, immersion divert, EV protection,
               appliance suggestions
  engine    — CoordinatorData, build_coordinator_data(), accumulate_energy()
  reporting — HTML report generators for dashboard sensors
  optimizer — Backward-compat shim re-exporting from rules

The HA integration layer (coordinator.py, sensor.py, etc.) imports from here.
"""
