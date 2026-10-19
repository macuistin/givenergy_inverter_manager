---
name: add-sensor
description: "Add a sensor to the GivEnergy Inverter Manager integration with its translation, docs row, entity snapshot row and tests. Use when asked to add or expose a new sensor."
---

# Add a sensor

Before you start, search `sensor_descriptions/` and `const.py` for an existing sensor or constant
that already does the job. Do not add a config option.

All integration paths are under `custom_components/givenergy_inverter_manager/`.

1. Put the value logic in `core/` or `sensor_values.py` when it is longer than one expression. Both
   stay free of Home Assistant imports. Test it in `tests/core/` or `tests/test_sensor_values.py`.
2. Add a `GivEnergyManagerSensorDescription` to the matching theme module in
   `sensor_descriptions/`. The join order in `sensor_descriptions/__init__.py` is the registry
   order, so a new module also goes in that table. Rules for the fields:
   - `key` is the unique id suffix and never changes after release.
   - `translation_key` names the entry under `entity.sensor` in `strings.json`. Set `device_class`, `native_unit_of_measurement` and
     `state_class` per `.claude/rules/home-assistant.md`. A resetting total sets `is_daily_total=True`
     or `reset_period`.
   - A sensor that is meaningless without an EV charger, immersion switch or immersion sensor sets
     `requires=Device.<X>`. A sensor with a text state needs no extra work, `native_value` fits it.
   - Rarely useful sensors set `entity_registry_enabled_default=False`.
   - A diagnostic sensor sets `entity_category=EntityCategory.DIAGNOSTIC`. A sensor with a fixed
     set of states sets `device_class=SensorDeviceClass.ENUM` and `options=[...]`, and its
     translation lists each state under `state` (see `charge_target_conflict`). Its attributes go
     in `attrs_fn`, and each name is placed in `tests/test_unrecorded_attributes.py`. Never name an
     attribute `entity_id`: Home Assistant reads that as a group.
   - A sensor that a dashboard card reads also needs an entry in `icons.json`.
3. Add the name under `entity.sensor.<key>` in `strings.json`, then copy the file over
   `translations/en.json`:
   `cp custom_components/givenergy_inverter_manager/strings.json custom_components/givenergy_inverter_manager/translations/en.json`
4. Add a `DESCRIPTIONS` entry (and a group if needed) in `scripts/gen_sensor_docs.py`, then run
   `python scripts/gen_sensor_docs.py` to rewrite `docs/sensors.md`.
5. Add the entity to `tests/ha_e2e/entity_snapshot.json` (`entity_id`, `key`, `name`, sorted by
   `entity_id`, JSON indent 1). Run the end-to-end suite to see the exact row it expects.
6. Add tests in `tests/test_sensors.py` for device class, unit, state class and `value_fn`. The
   `battery_power` tests are the pattern. For an optional device, add the absent and added-later
   cases (`tests/ha_e2e/test_optional_device_entities_e2e.py`).
7. Run `ruff check custom_components tests scripts packages`, the unit suite and the end-to-end suite.
   `tests/test_sensor_integrity.py`, `tests/test_docs_sensor_table.py` and `tests/test_translations.py`
   catch most mistakes in steps 2 to 4.
8. Add a bullet under `## Unreleased` in `CHANGELOG.md`, in plain words.
