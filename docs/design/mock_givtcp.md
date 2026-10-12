# Mock GivTCP

`tools/mock_givtcp.py` is the device side of every write the integration makes. It exists so a test can assert the exact commands sent to the inverter, the immersion switch and the Zappi, with nothing real in reach (brief card FN3).

## What it does

- Publishes the entity states GivTCP publishes, with the names `inverter/givtcp/discovery.py` expects: `sensor.givtcp_<serial>_pv_power`, `_soc`, `_battery_power`, `_grid_power`, `_load_power`, `_invertor_temperature`, `_invertor_serial_number`, `_battery_capacity_kwh`, the seven daily energy counters, and the controls `number.givtcp_<serial>_target_soc`, `switch.givtcp_<serial>_enable_charge_target`, `switch.givtcp_<serial>_enable_charge_schedule`, `select.givtcp_<serial>_charge_start_time_slot_1` and `_charge_end_time_slot_1`. Readings use GivTCP's own sign convention (grid positive when exporting, battery positive when discharging).
- Registers `number.set_value`, `switch.turn_on`, `switch.turn_off` and `select.select_option` and **records every call in order** as a `Write(domain, service, entity_id, value)`.
- Moves the written entity to the new value, as a real device would, so the writer's read-back sees what GivTCP would show. `follow = False` leaves the state alone and `fail_on(entity_id)` makes writes raise.
- Adds a stub immersion switch with a water temperature sensor (`add_immersion`) and a stub Zappi with a charge mode select (`add_zappi`).
- `python tools/mock_givtcp.py [serial]` prints the entity map and the write services as JSON. It needs no Home Assistant.

## Using it in a test

```python
mock = MockGivTCP(hass, serial="ab1234g567")
mock.publish(Readings(solar_w=0, battery_soc=55, grid_w=-600, load_w=600))
mock.add_immersion(temperature_c=48.2)
mock.install()                      # before setup
# ... set the config entry up ...
mock.install()                      # again: the switch and number platforms register their own services
mock.clear()                        # drop writes made by the setup cycle, if the test is not about them
# ... trigger a decision ...
assert mock.sequence() == [("switch.turn_on", "switch.givtcp_ab1234g567_enable_charge_schedule", None), ...]
```

The idle controls start with both window times at `00:00:00`, both switches off and a target of 50 % (`Readings.target_soc`). The writer skips a write when the entity already holds the value, so a test that wants to see a write picks an idle value that differs from the one the engine decides.

`tests/ha_e2e/test_write_sequence_e2e.py` is the end-to-end test. It asserts:

| Path | Asserted writes |
|---|---|
| Charge target (the timer's callback) | enable schedule, window start `02:00:00`, window end `04:00:00`, target, enable target, in that order |
| A second apply | nothing (read-before-write) |
| A rejected target write | steps 1 to 3 only, the target is not enabled |
| Cheap-rate floor top-up (setup cycle, 31 % battery) | target 40, enable target; and enable only when a higher target is already set |
| Immersion | `turn_on` when the water is cold, `turn_off` when hot, nothing when the switch already matches |
| EV mode request | one `select_option` to `Eco+` on the Zappi, none when not plugged in or already in Eco+ |
| Dry run | no write on any path, and the integration records "Would write charge target ...", "Would turn_on immersion heater ..." and "Would set Zappi ... → Eco+ ..." |

## Why there is no MQTT broker

The brief asked for a disposable Home Assistant with a local Mosquitto. The integration never speaks MQTT. It reads entity states from the state machine and calls Home Assistant services, so what it sees of GivTCP is the entities that GivTCP's MQTT discovery creates. Publishing those entities straight into the state machine drives the same code, needs nothing installed, runs in about a second and cannot leave the machine. A broker would add a second system (Mosquitto, the Home Assistant MQTT integration, discovery payloads) whose behaviour is not what these tests are about. Mosquitto is not installed on the machine this was built on, so an MQTT mode could not have been tested.

What the in-process mock does not cover: MQTT discovery itself (how GivTCP's discovery payloads become `givtcp_<serial>_...` entity ids), the real latency between a command and the state update, and GivTCP rejecting a write.

## Running it on a disposable instance (not built, not tested)

This is a sketch for the maintainer. None of it has been run, and GivTCP's topic names and discovery payload layout were not read for this document, so check them on the instance.

1. A clean Home Assistant (the floor version, then the latest) with an empty configuration, the branch's `custom_components/`, the MQTT integration pointed at a local Mosquitto, and the integration's `dry_run` on.
2. A small publisher built on `MockGivTCP.entities` and `describe()`: for each entity it sends an MQTT discovery message (`unique_id`, a name that makes Home Assistant produce `givtcp_<serial>_<suffix>`, a `state_topic`, and for number, switch and select a `command_topic`), then publishes states.
3. The same publisher subscribes to each `command_topic` and appends every message to a JSON lines file. That file replaces `mock.writes`, and an assertion script compares it with the table above.
4. Check on the instance that the entity ids Home Assistant creates match `MockGivTCP.entities`. If they differ, the discovery payload names are wrong, not the integration.
5. Turn `dry_run` off on that instance only to exercise the real write path against the recorder. The test instance procedure in the brief (marker file, actuator integrations disabled, read-only broker access, blocked network) still applies if the instance is ever pointed at anything real.
