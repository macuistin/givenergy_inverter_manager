# Testing

There are two test suites. They need different virtualenvs because one stubs Home Assistant and the other runs the real thing.

| Suite | Path | What it covers | Time |
| --- | --- | --- | --- |
| Stubbed unit suite | `tests/` (excluding `tests/ha_e2e`) | Core logic, sensors, coordinator and config flow against `MagicMock` stubs of `homeassistant` | about 3 s |
| Real Home Assistant suite | `tests/ha_e2e/` | Setting up, reloading and unloading the integration in a real `hass`, the entity registry, and the config and options flows | about 4 s |

## Stubbed suite

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests -q
```

`tests/conftest.py` replaces `homeassistant` in `sys.modules` before collection. `pyproject.toml` adds `--ignore=tests/ha_e2e` so this suite never imports the real Home Assistant tests.

`tests/test_dashboard_example.py` is a golden test for `docs/dashboard-example.yaml`. After an intended change to the dashboard generator, regenerate the file with `UPDATE_DASHBOARD_EXAMPLE=1 python -m pytest tests/test_dashboard_example.py` and review the diff.

## Real Home Assistant suite

Use a separate virtualenv. The plugin pins `homeassistant`, `pytest` and `pytest-asyncio`, and Home Assistant 2026.9 needs Python 3.14.2 or newer.

```bash
python3 -m venv .venv-e2e
.venv-e2e/bin/pip install -r requirements-test-e2e.txt
.venv-e2e/bin/python -m pytest tests/ha_e2e -q
```

Run it from the repository root. `tests/ha_e2e/pytest.ini` is picked up because it is the closest ini file to the test path. That keeps `tests/conftest.py` (the stubs) from loading, which would otherwise overwrite attributes on the real `homeassistant` modules.

If you run `pytest tests/ha_e2e` in the stubbed suite's virtualenv, it reports one skip that points back to this page.

### What the suite does

- Publishes GivTCP-style states with `hass.states.async_set` (solar, SoC, battery, grid, load, daily counters, charge control entities, forecast and carbon sensors).
- Sets up a `MockConfigEntry` with every option filled in and asserts the entry is `LOADED`.
- Runs each scenario at two frozen times: a June afternoon with surplus solar, and a December night inside the cheap-rate window.
- Checks the log for duplicate unique ID errors and `ValueError` raised from sensor state attributes.
- Enables every sensor that is disabled by default, reloads, and checks each one has a state.
- Drives the options flow with the payload the frontend would send, including an empty forecast and carbon selection, and serialises the form schema the way the frontend API does.
- Walks the config flow for the manual path (no discovered inverters) and the discovered path.
- Checks that every field in the setup, reconfigure and options forms has a label and help text in `strings.json` and `translations/en.json`.
- Moves the immersion temperature numbers and checks the integration is not reloaded.
- Unloads, reloads and removes the entry.

Writes to GivTCP are captured with `async_mock_service` for `number.set_value`, `switch.turn_on`, `switch.turn_off` and `select.select_option`. Nothing talks to a real inverter. The 2 s retry sleep in the coordinator is patched to 0.

### Known bugs

Tests marked `xfail(strict=True)` document real defects in the integration. When the bug is fixed the test starts to pass, strict mode turns that into a failure, and you remove the marker.

### Updating Home Assistant

`requirements-test-e2e.txt` pins one plugin release. Each release pins one `homeassistant` version, so bumping the plugin bumps Home Assistant. Check the plugin's `Requires-Dist` before changing it.

## CI

`.github/workflows/tests.yml` has two jobs: `tests` for the stubbed suite and `e2e` for the real Home Assistant suite.
