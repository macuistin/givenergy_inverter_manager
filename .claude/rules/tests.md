---
description: "Test layout, what each suite proves, and the rules for new and changed tests"
paths:
  - "tests/**"
---

# Tests

## Two suites

- `tests/` (not `tests/ha_e2e`) is the unit suite. `tests/conftest.py` replaces `homeassistant` with
  stubs before collection, so it runs fast and from any directory. Use `ROOT` and `PKG` from
  `tests/helpers.py` for paths, never the working directory.
- `tests/ha_e2e/` runs the integration in a real Home Assistant (`pytest-homeassistant-custom-component`).
  It needs its own virtualenv and `requirements-test-e2e.txt`, and it is run from the repo root.
  Its own `pytest.ini` keeps `tests/conftest.py` from loading. Never run both suites in one process.
- A green unit suite does not prove Home Assistant behaviour. Setup, unload, reload, the registries,
  the config, reconfigure and options flows, state limits and recorder attributes are proved only by
  `tests/ha_e2e/`. Put the test there when the claim is about Home Assistant.
- `tests/test_config_flow_schemas.py` uses the real selector classes. Run it after any schema change.
- Nothing talks to a real inverter. End-to-end tests capture writes with `async_mock_service` or use
  `givtcp_mock` (`tests/ha_e2e/test_write_sequence_e2e.py`).

## Fakes and the backend contract

- `tests/fakes/fake_inverter.py` is a backend that implements only the `InverterBackend`
  interface. Test the coordinator's choices against it, with no GivTCP entity name in the test.
- `tests/backend_contract.py` is what any backend must do: reads in the integration's sign
  convention, the feed states, the charge plan (including the 100% case), the floor, other
  slots and failed writes. Each backend subclasses `BackendContract` with a harness that knows
  its own inverter side. `tests/inverter/test_backend_contract.py` runs it on the fake and the
  GivTCP adapter, and `tests/ha_e2e/test_backend_contract_e2e.py` runs it on the adapter over
  `givtcp_mock`. A new backend starts from a passing contract.
- `packages/givtcp_mock/src/givtcp_mock/systems/` holds the entity states of whole GivTCP systems (hybrid, AC
  coupled, All-In-One, three-phase, Gateway, EMS, a charger on its own and more). Only
  `hybrid_gen3_two_batteries_3_6_3.json` is from real hardware. `build.py` writes the others from
  it and GivTCP's datapoint list, and `tests/lib/givtcp/test_system_fixtures.py` fails when a
  file differs from what `build.py` makes. Change `build.py`, then run
  `python -m givtcp_mock.systems.build`. Do not edit a fixture by hand. Test system
  detection against these files, not a hand-built dict.
- The mock (`givtcp_mock`) adds optional devices with `add_immersion`, `add_zappi` and `add_givevc`.
  It owns only the entities a write may reach, so a write to any other entity lands in
  `other_calls` and the charger tests assert that stays empty.

## Writing tests

- A bug fix has a test that fails without the fix. Revert the fix, run the test, see it fail, then
  restore the fix. Name the test in the PR.
- Test behaviour: call the coordinator, entity, flow or core function and assert on the result.
  Do not read a source file and assert a string is in it. `ROADMAP.md` lists the ones left to replace.
- Never weaken a test to get green. Do not delete it, loosen an assertion, widen a tolerance, add
  `skip`, or add `xfail` for a failure you caused. A test that is wrong gets fixed in its own commit
  with the reason in the message. `xfail(strict=True)` is only for a documented existing defect.
- Do not re-implement production logic in a test body. Call the real function. The flat adapters in
  `tests/core/flat_engine.py` and `flat_rules.py` add no logic.
- Control time. Pass `now`, or freeze the clock in end-to-end tests (`MIDDAY` and `CHEAP_NIGHT` in
  `tests/ha_e2e/conftest.py`). Do not depend on the date the test runs.
- A new sensor, platform, option or form field needs the matching tests. See `/add-sensor`.
- A new option, constant or entity needs a justification in the PR. Search `const.py`, `conf.py`, `defaults.py` and `tuning.py` first.
- Tests with `xfail`, `skip` or a long `sleep` need a one-line reason beside them.

## Before pushing

Run `ruff check custom_components tests scripts packages`, the unit suite and the end-to-end suite. CI
runs the unit and end-to-end suites on Python 3.14 against Home Assistant 2026.5.0 and the latest
release. If you did not run the
end-to-end suite, say so in the PR under "Testing".
