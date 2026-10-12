# SY0: GivTCP system fixtures

## Question

Which GivTCP system layouts can the integration be tested against, and which of them came from real hardware?

## Result

One fixture comes from real hardware. The rest are built from GivTCP's published datapoint reference and release notes, because the maintainer has one single-phase hybrid and no other GivEnergy system to read an entity list from.

All fixtures are in `tests/fixtures/givtcp_systems/`. The real one is a JSON file taken from a running Home Assistant on GivTCP 3.6.3. The synthetic ones are made by `build.py` in the same folder from the real one, by adding the entity names the datapoint reference gives for a kind and removing the ones it says that kind lacks. A test compares the committed files with what the builder makes, so they cannot drift, and every file says in `provenance` whether it is `real` or `synthetic`.

| Fixture | Provenance | What it proves |
|---|---|---|
| `hybrid_gen3_two_batteries_3_6_3` | **real** | The baseline. `Invertor_Type` is `Hybrid_gen3` and `GivTCP_Version` is `3.6.3`, both readable as sensor states. Two battery modules, each its own device named by the battery serial, and an EM115 meter device. Neither is an inverter |
| `hybrid_custom_prefix_3_6_3` | synthetic | A device prefix changed in GivTCP is found and every derived entity (status, data age, charge rate, daily counters, rates) is read under it |
| `ac_coupled_3_6_3`, `all_in_one_3_6_3`, `three_phase_3_6_3` | synthetic | Each kind is recognised and the screen says it is not tested on real hardware |
| `gateway_parallel_two_aio_3_6_3` | synthetic | A Gateway over parallel units is the device to manage. It has no serial sensor, so it is found by its version sensor and its Gateway values |
| `all_in_one_and_gateway_3_6_3` | synthetic | One All-In-One beside a Gateway that is not parallel: the All-In-One is managed |
| `two_hybrids_3_6_3` | synthetic | Two inverters: the user is asked, and they are never added together |
| `ems_3_6_3` | synthetic | An EMS has no state of charge and no charge controls. Nothing is written |
| `hv_gen3_before_3_6`, `hv_gen3_after_3_6` | synthetic | An HV Gen 3 hybrid changing from the three-phase layout to the single-phase one across the upgrade |
| `hybrid_with_ghost_battery_3_6_3` | synthetic | A battery slot that answers with zeros is not a module |
| `hybrid_with_ev_charger_3_6_3` | synthetic | A GivTCP EV charger device is not an inverter |

## What the real fixture settled

- `Invertor_Type` is an entity state, so it can be used (an open question on the plan). Only the value `Hybrid_gen3` has been seen, so the classifier matches the other kinds by the words GivEnergy uses, loosely, and a datapoint that exists on one kind only decides first.
- A battery module's entities are named by the battery serial, not the inverter's, and carry no GivTCP version sensor. Modules are counted by their serial sensors.
- GivTCP publishes a `select` and a `time` entity for each charge slot on 3.6.3, and the integration still writes the `select` only.

## Not covered

- Entity names for every kind but the single-phase hybrid are a reading of the documentation. A fixture from a real system replaces its synthetic one, and the setup screen's "not tested on real hardware" line is removed for that kind.
- Charge writes through a Gateway or to an EMS have not been seen to take effect. The integration manages the Gateway only and writes nothing to an EMS.
