---
description: "Home Assistant conventions this integration follows: entities, state limits, flows, reloads, services"
paths:
  - "custom_components/**"
  - "tests/ha_e2e/**"
---

# Home Assistant rules

Each rule is checked by a test or by the Home Assistant source. The test is named where one exists.

## Entities

- Entity ids, unique ids and keys never change once released. The unique id is `{entry_id}_{key}`.
  `tests/ha_e2e/test_entity_snapshot.py` pins every entity id, key and name.
- A rename changes only the display name (`tests/test_renamed_sensors.py`). Old names are listed in
  `docs/sensors.md` under "Renamed sensors".
- To retire a sensor, add its key to `_RETIRED_SENSOR_KEYS` in `__init__.py`. Setup then deletes its
  registry entry. A repair issue goes in `_RETIRED_ISSUE_IDS` the same way.
- A setting the user tunes is a control (`controls.py`), not a form field. It writes its own option
  key through `async_set_option`, shows the value in force, and the key is in `LIVE_KEYS`.
- Every platform sets `PARALLEL_UPDATES` (`tests/test_metadata.py`). All entities use
  `_attr_has_entity_name = True` through `GivEnergyEntity`.
- Listeners and other hooks that Home Assistant calls synchronously are `@callback` functions. To
  start async work from one, use `hass.async_create_task` or the coordinator's `_create_task`.
  An `async def` handed to a sync hook never runs.
- No blocking calls in the event loop. File and recorder work goes through
  `hass.async_add_executor_job` (see `async_detect_test_instance` in `coordinator.py`).

## State and attributes

- A sensor state is at most 255 characters (`homeassistant.const.MAX_LENGTH_STATE_STATE`). A longer one
  is logged as an error on every update and reads unknown.
- Text goes through `fit_state` in `core/text_state.py`. `GivEnergyManagerSensor.native_value` already
  does this. A cut state ends in `…` and the whole text is in the `full_text` attribute
  (`ATTR_FULL_TEXT`). `STATE_MAX_LENGTH` in `const.py` repeats the limit because `core/` cannot import
  Home Assistant. Do not write a second cutting helper.
- `tests/test_state_length.py` and `tests/ha_e2e/test_state_length_e2e.py` audit every text sensor.
  A new text sensor needs no new test. It must be in `SENSOR_DESCRIPTIONS`.
- Attributes of one state stay under 16 KiB (`MAX_STATE_ATTRS_BYTES` in the recorder). Large or
  text-heavy attributes (`html`, `full_text`) are listed in `_unrecorded_attributes`. That is a class
  attribute on `GivEnergyManagerSensor`, a `frozenset`. Add a new large attribute to it.
- `state_class` and `device_class` follow Home Assistant's `DEVICE_CLASS_STATE_CLASSES`
  (`tests/test_sensor_integrity.py` checks every description against it):
  - monetary totals that accumulate: `TOTAL`. Estimates and projections: `None`. A price per
    unit has no monetary device class and uses `MEASUREMENT`
  - energy that resets daily, weekly, monthly or yearly: `TOTAL` with `is_daily_total=True` or
    `reset_period`, which makes the entity report `last_reset`
  - yesterday, trailing 12 month and forecast sensors are not cumulative: `None`
  - live power: `MEASUREMENT`

## Config and options flows

- The setup wizard is a checklist of pages: `system`, then only the ticked pages (`tariff`,
  `tariff_rates`, `forecast`, `hot_water`), then `confirm`. The options wizard is the same pages plus
  `battery`, `ev`, `bill` and `schedule_change`. Page logic is in `core/wizard_*.py`, the flow steps
  in `wizard/`, and `config_flow.py` only registers the handlers. Reconfigure is the inverter connection.
- `NumberSelector` needs `step >= 0.001` or `"any"`. A smaller step fails validation.
  `tests/test_config_flow_schemas.py` runs the real selectors.
- A time selector returns `HH:MM:SS`. Rate periods are stored as `HH:MM` (`rows_from_sections` in `core/wizard_tariff.py`).
- A wizard keeps plain values on the handler and stores nothing until `confirm`. The options wizard
  reads `config_entry.options` when it writes (never in `__init__`) and returns the current options
  with only the changed keys replaced, so a control moved meanwhile keeps its value. A page that was
  not ticked is never rewritten, and a value equal to the one in force is not written.
- Reconfigure writes with `async_update_and_abort`. The entry's update listener does the reload. Do
  not call `async_update_reload_and_abort`: Home Assistant 2026.9 reports it for an entry with an
  update listener and removes it in 2026.12. Do not use `OptionsFlowWithReload` either.
- `core/reload_policy.py` decides whether an options save reloads (`change_effect`). A new option
  key reloads until it is in `LIVE_KEYS`. Add a key there only when the coordinator reads it from
  `_effective_cfg()` on every cycle or `async_apply_config_change` copies it on, and add its row to
  `tests/core/test_reload_policy.py`.
- Every form field has a label and help text in `strings.json`.
  `translations/en.json` is a byte copy of `strings.json` (`tests/test_translations.py`).
- Text for config, options, entities, issues, exceptions and services lives in `strings.json`.
  `services.yaml` holds structure only. Repair fix flows are in `repair_flows.py`.
- Service actions raise `ServiceValidationError` with a `translation_key` when no entry is loaded
  (`require_loaded_entries` in `services.py`).
