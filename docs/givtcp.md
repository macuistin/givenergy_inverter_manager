# What we know about GivTCP

This integration does not talk to the inverter. [GivTCP](https://github.com/britkat1980/giv_tcp) does, and this integration reads and writes the Home Assistant entities GivTCP creates. So most reports of the form "the integration did not do X" end with something GivTCP did or did not publish. This page is what we have learned about that layer: how to find the inverter and its entities, how to read and write them safely, and what each kind of GivEnergy system publishes. It is for the people who maintain this integration.

It is checked against the GivTCP 3.6.4 source and its own test results (October 2026). A line says so when a fact comes from somewhere else or has not been seen on real hardware. Only a single-phase hybrid has been tested on a real install. The other kinds come from GivTCP's own captures of real devices, which show what it publishes but not that this integration works on them.

## How it fits together

- GivTCP polls the inverter over Modbus TCP, through the Wi-Fi or Ethernet dongle, using the `givenergy-modbus` library. It publishes what it reads over MQTT, creates Home Assistant entities from MQTT discovery messages, and has a REST API.
- A change from Home Assistant, REST or MQTT goes on a queue. The read loop sends it to the inverter between polls.
- **Real Time Control** is a GivTCP setting. With it off, GivTCP accepts a change from Home Assistant and does not send it to the inverter. An upgrade can reset it. The repair **GivTCP's Real Time Control is off** appears when the switch reads off. See [Real Time Control is off](troubleshooting.md#real-time-control-is-off).
- The integration only reads and writes Home Assistant entities. It never opens its own connection to the inverter or to MQTT.

## Supported versions

- The integration is tested on GivTCP 3.6.3. It needs **3.6.2 or later** when GivTCP is a 3.6 release.
- GivTCP 3.6 and 3.6.1 delete and recreate an entity when its discovery settings change, so Home Assistant gives it the default entity id again. The repair **This GivTCP release resets entity ids** appears on those two. Releases before 3.6 do not do this and raise nothing.
- Read the version from `sensor.<prefix>_givtcp_version`. A version that cannot be read raises nothing. The rule is in `core/givtcp_version.py`.
- When GivTCP releases, read its release notes for entities the integration uses (the table below) and run the fixtures. See [How to check a change](#how-to-check-a-change).

## Finding the inverter and its entities

GivTCP lets the user change the entity prefix for each inverter (`HADEVICEPREFIX`), and a user can run several inverters. So the integration never assumes `givtcp_`. It finds a device by what it publishes (`lib/givtcp/discovery.py`).

1. **Find the devices.** A device is a prefix that has a `sensor.<prefix>_invertor_serial_number`. A device with no serial sensor, as a Gateway or an EMS may be, is also found when it publishes `_givtcp_version` and a state of charge, a Gateway value or an EMS value.
2. **Give each device its entities.** An entity belongs to the longest prefix that matches, so a battery module or a meter (which carry their own serial) does not count as part of the inverter.
3. **Classify the kind.** First by entities only one kind has, then by the text in `sensor.<prefix>_invertor_type` (`lib/givtcp/system.py`). Each kind comes with the evidence used and a confidence.
4. **Choose which device to manage** (`select_controller`). One device is managed. A Gateway over two or more All-In-Ones is managed instead of the units. A Gateway with one All-In-One gives way to the All-In-One. Two or more other inverters are never added together: the user is asked. Units behind a Gateway are read only.
5. **Count the battery modules.** A battery module is a `_battery_serial_number` sensor that reads a real serial. A slot that answers with zeros is not a module.
6. **Find the device prefix later.** The prefix is read back from the entities the wiring already names (`device_prefix`). It is trusted when it carries the inverter's serial or two wired entities agree on it. Otherwise it is `givtcp_` and the serial.
7. **Find an entity again after GivTCP renames it.** Each wired entity is remembered by its registry id as well (`core/entity_refs.py`), so an entity GivTCP reset to a default id is found again without a repair. One that cannot be found by either id raises **GivTCP entities not found** after about five minutes.

The system is looked at again at start-up, every ten cycles and when GivTCP's version changes. A change of kind, controller or module count raises **The system looks different** and keeps the stored identity. Nothing is switched silently.

## The entities we use

Entity ids are `<domain>.<prefix>_<item>`, for example `sensor.givtcp_ab1234g567_pv_power`.

| Role | Entity item | Domain | Notes |
| --- | --- | --- | --- |
| Solar power | `pv_power` | sensor | Always positive |
| Battery state of charge | `soc` | sensor | `battery_soc` on GivTCP 2 |
| Battery power | `battery_power` | sensor | **Positive for discharge**, negative for charge. We negate it |
| Grid power | `grid_power` | sensor | **Positive for export**, negative for import. We negate it |
| House load | `load_power` | sensor | The inverter-side load only. Loads wired to the consumer unit directly are not in it |
| Inverter temperature | `invertor_temperature` | sensor | Spelled `inverter_temperature` on three-phase. We try both |
| Battery capacity | `battery_capacity_kwh` | sensor | Read once at setup |
| Charge target | `target_soc` | number | 4 to 100 |
| Enable charge target | `enable_charge_target` | switch | The inverter ignores the target while this is off |
| Enable charge schedule | `enable_charge_schedule` | switch | |
| Charge window | `charge_start_time_slot_1`, `charge_end_time_slot_1` | select | Up to ten slots. We write slot 1 and the `select`, never the `time` entity beside it. Time is `HH:MM:SS` |
| Charge rate | `battery_charge_rate` | number | Watts. Used to size the window |
| Battery pause | `battery_pause_mode`, `battery_pause_start_time_slot`, `battery_pause_end_time_slot` | select (the times may be `time` entities) | Read only, and looked for on every cycle, so none is stored in the config. The mode options are `Disabled`, `PauseCharge`, `PauseDischarge` and `PauseBoth`. `Disabled` gives no pause, `PauseCharge` stops charging only and `PauseDischarge` stops discharging only. See [Battery pause](concepts.md#battery-pause) |
| Daily counters | `pv_energy_today_kwh`, `import_energy_today_kwh`, `export_energy_today_kwh`, `battery_charge_energy_today_kwh`, `battery_discharge_energy_today_kwh`, `load_energy_today_kwh`, `ac_charge_energy_today_kwh` | sensor | The source for today's figures. The integration's own accumulation fills in when one is missing |
| Battery cycles | `<battery serial>_battery_cycles` | sensor | One per pack, each counts its own. We take the highest, never the sum |
| Status and freshness | `status`, `data_age`, `last_updated_time` | sensor | See [Health and freshness](#health-and-freshness) |
| Type and version | `invertor_type`, `givtcp_version` | sensor | |
| Real Time Control | `real_time_control` | switch | Read only |
| Rates | `day_rate`, `night_rate`, `export_rate` | sensor | Offered as starting values on the tariff screen and nothing else. GivTCP's shipped values (0.395, 0.155 and 0.04) are skipped, because they mean the user never set them |

An item that is missing, `unavailable` or `unknown` reads as no value. A required one that is missing is listed in the integration's unavailable inputs. An optional one changes nothing.

### Published but not used

GivTCP publishes far more than we read. Seen in its own results for real devices, and not read by the integration: per-battery and per-stack state of health, cell temperatures, stack charge and discharge MOS state, battery calibration status, battery pack current, per-phase import, export, load and EPS power on three-phase, meter power on each phase, the energy flows (`battery_to_house`, `battery_to_grid`, `grid_to_battery`) and the inverter's force charge and discharge enables. Some are candidates for the roadmap.

## What each kind of system publishes

The table is from GivTCP's own test results on a real, serial-redacted capture of each kind (`packages/givtcp_mock/src/givtcp_mock/systems/harness_*.json`, built by `from_harness.py`). It records what GivTCP creates on its first read. Battery modules and the units behind a Gateway appear after the second.

| Kind | `Invertor_Type` as published | What differs |
| --- | --- | --- |
| Hybrid Gen 1 and Gen 2 | `Hybrid_gen1`, `Hybrid_gen2` | One charge slot. Everything above is present under the names above |
| Hybrid Gen 3 | `Hybrid_gen3` | Single-phase entity set. Seen on a real install, not in a capture |
| Hybrid HV Gen 3 | `Hybrid_hv_gen3` | Single-phase entity set. The capture has no battery, so battery power and charge level are absent from it. A real one with a battery has not been seen in a fixture |
| Three-phase hybrid | `Gen 3 - Hybrid_3ph` | No `grid_power` and no `battery_power`. It publishes `import_power` and `export_power`, and `battery_charge_power` and `battery_discharge_power`. Setup finds no grid or battery power on this kind. Ten charge slots. Force charge and discharge enables |
| AC-coupled | `Ac` | One charge slot. No PV string values, only the total |
| All-In-One | `All_in_one` | Ten charge slots. No PV string values |
| Gateway | `Gateway` | The units behind it are entries of the Gateway device. It may publish no serial sensor. Ten charge slots. No inverter temperature. |
| EMS | `Ems` | No solar, house load, charge controls or state of charge of its own. It publishes `battery_power`, `grid_power`, per-meter power, and a `soc` for each module under that module's serial |

The text is the library's model name with GivTCP's capitalisation, so compare it without regard to case.

A GivEnergy EV charger is published as a separate device (GivEVC), with `charging_state`, `connection_status`, `active_power`, `charge_session_energy` and a `charging_mode` select that offers Grid, Hybrid and Solar. The state strings are in GivTCP's `evc.py`. It has not been seen on real hardware here.

## Reading

- One read per cycle, in the integration's own sign convention (`lib/givtcp/reader.py`). GivTCP's grid power and battery power both have the opposite sign to Home Assistant's and to ours, so the reader negates them. Without that, every export is counted as import.
- **Battery power's sign was only confirmed on one hybrid.** Another model could be the opposite.
- The daily counters are the source for today's figures. The integration's own accumulation is the fallback.
- A Gateway that shows the battery charging while it discharges has its sign inverted. Its All-In-One powers follow the single-phase convention.
- A GivTCP upgrade can change a total's unit or value. Home Assistant's Energy dashboard then shows one large step, which the user corrects in **Developer Tools → Statistics**. See [Energy totals jumped after a GivTCP upgrade](troubleshooting.md#energy-totals-jumped-after-a-givtcp-upgrade).

## Health and freshness

- GivTCP publishes `status` (`online`, or `paused` while it recovers), `data_age` (seconds since it last read the inverter, -1 for never) and `last_updated_time`.
- Every entity names `Stats/status` as its availability topic. **Nothing ever publishes `offline` when GivTCP stops or crashes.** The only last-will message is set on the short-lived client that sends the discovery messages and then disconnects cleanly. The long-lived publishing connection sets none. So when GivTCP stops, its entities keep their last values and stay available, and Home Assistant shows a stale value as live.
- The integration therefore judges it itself (`feed_status`), in this order: **silent** (solar and battery entities both missing or unavailable), **frozen** (no entity reported for ten minutes, judged on when it was last reported and never on its value), **paused**, **stale** (`data_age` over ten minutes, or -1), then **publishing**. A frozen feed stops planning and writing and raises **GivTCP data is frozen**. GivTCP running but unable to read the inverter raises **GivTCP is not getting data from the inverter**.
- GivTCP can fail to start when its day rate, night rate or tariff type is empty, and that looks the same as a crash. Check them first.

## Writing

The inverter has about a million lifetime register writes, so every write goes through one path (`lib/givtcp/writer.py`):

1. Read the entity first and skip the write when it is already at the value.
2. Skip a value written in the last five minutes.
3. Call the Home Assistant service, read the state back, and try again up to three times, two seconds apart.
4. Count each accepted call. The integration logs a warning at 500,000.

All writes are serialised, so two callers never interleave. A write the integration did not make is told apart from its own by a write log, which feeds **Charge Target Conflict**. In dry run, nothing is sent and the decision is logged as `Would set ...`.

**The order of a charge write matters** (`lib/givtcp/sequence.py`). It is the sequence Predbat and givenergy-local both identify as necessary:

1. Enable the charge schedule.
2. Set the window start.
3. Set the window end.
4. Set the target, clamped to 4 to 100.
5. Enable the charge target, last. With it off, the inverter ignores the target. It is not turned on when the target could not be written, so the inverter never limits charging to an old target.

The cheap-rate floor only raises the target and keeps a higher one already on the inverter. Clearing another active slot writes `00:00:00` to its start and end.

What this integration never writes: Charge Control or Plug and Go on a GivEnergy charger, any export or discharge window, or a battery mode that exports. The client library can write them for another host, see below.

**Other settings the client can write.** `lib/givtcp/controls.py` can pause charging or discharging for a window, select a battery mode, set the reserve and set the charge and discharge rates. Nothing in the coordinator calls these yet, so a user sees no change. Each goes through the same verified writer, so it is read first, held to the cooldown and read back. The client has no policy about what to write. Four rules hold in it:

- A pause writes its start and end before its mode, so it never starts on an old window. Ending a pause writes the mode only.
- A select is written with the option the entity lists. GivTCP and other projects spell the pause options differently (`PauseDischarge`, `Pause Discharge`, `Not Paused`), so the wanted option is matched without case, spaces, underscores or hyphens. An option the entity does not offer is refused, not sent.
- The reserve, the rates and the discharge target are kept inside the `min` and `max` the entity publishes. The reserve never goes below 4.

`lib/givtcp/schedules.py` and `force.py` can also write the discharge (export) schedule, charge slots 2 to 10 and a timed force charge or export. A discharge plan writes its target and window first and switches the schedule on last, and stops at the first failed write. Nothing in the coordinator calls them, and `InverterExport` in `inverter/backend.py` is kept apart from the interfaces the coordinator uses. `lib/givtcp/README.md` documents the whole client.

The client also reads the inverter's clock (`invertor_time`) and reports how far it is from the host's (`clock_skew_s`). A drifted clock moves the charge window. Nothing warns on it yet.

**Results.** GivTCP builds a result such as `Setting Charge Target 85 was a success` or `... failed: <reason>` for every write. Only a REST caller gets it. A write from Home Assistant, which goes over MQTT, gets nothing and the result is only in GivTCP's log. And an accepted write is not a write that took: with Real Time Control off, the inverter acknowledges a write and ignores it. So the integration reads each setting back, and raises **The inverter did not take a charge setting** when it still shows the old value.

Set Charge Target writes the target only. It does not turn the schedule on, and a 100% target does not turn the target off. Charge slot 2 on a ten-slot inverter is at registers 243 and 244.

A parallel All-In-One behind a Gateway is a child inverter that may accept a write and ignore it. An EMS plant reasserts its settings. The integration therefore controls the Gateway or the plant device and never the units.

## How to check a change

- The fixtures are in `packages/givtcp_mock/src/givtcp_mock/systems/`: one from a real install, eight from GivTCP's own test results (`from_harness.py`, which says how to rebuild them from a GivTCP checkout), and the rest built from GivTCP's datapoint reference (`build.py`). Each file says which it is.
- `givtcp_mock` is the fake GivTCP the write tests use. See [the design note](design/mock_givtcp.md).
- When GivTCP releases, run the harness fixtures through discovery and compare. A kind that stops being classified, or a role that loses its entity, shows in `tests/lib/givtcp/test_system_fixtures.py`.

## GivTCP's own tests, and what would help upstream

GivTCP has a test harness that runs its real code over eight real captures and records what it publishes in `tests/golden/<model>.json`. A change is a small pull request that explains the cause, adds a test, updates the golden files, adds a `CHANGELOG.md` entry and says what was checked on hardware. Large or mixed ones have been closed.

Changes that would help us, none sent:

1. **A last will on the long-lived connection**, and an `offline` message on a clean stop. Entities would then go unavailable when GivTCP stops. This is the one that matters most.
2. **A `Last Write Result` sensor**, so a write from Home Assistant gets the result text too. It tells us a write was rejected, not that it was ignored, so the read-back stays.
3. **The device type values and what each kind publishes**, in GivTCP's `docs/DATAPOINTS.md`, which says only "Model (Hybrid, AC, AIO...)".
4. **Renamed and removed entities** listed in each release's notes.

## Where it is in the code

| Topic | Code |
| --- | --- |
| Finding the inverter, its prefix and its entities | `lib/givtcp/discovery.py`, `core/entity_refs.py` |
| Classifying the system and choosing the controller | `lib/givtcp/system.py`, `core/system_text.py` |
| Reading | `lib/givtcp/reader.py` |
| Writing, the order and the read-back | `lib/givtcp/writer.py`, `lib/givtcp/sequence.py`, `lib/givtcp/adapter.py` |
| Version and Real Time Control repairs | `core/givtcp_version.py`, `core/real_time_control.py`, `repairs.py` |
| Test fixtures | `packages/givtcp_mock/src/givtcp_mock/systems/` |
