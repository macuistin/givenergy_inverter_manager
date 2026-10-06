# GivEnergy Inverter Manager

[![GitHub Release](https://img.shields.io/github/release/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/commits/main)
[![License](https://img.shields.io/github/license/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![Tests](https://img.shields.io/github/actions/workflow/status/macuistin/givenergy_inverter_manager/tests.yml?style=for-the-badge&label=Tests)](https://github.com/macuistin/givenergy_inverter_manager/actions/workflows/tests.yml)

A Home Assistant integration for GivEnergy inverters. It sets the overnight charge target, diverts spare solar to an immersion heater, and tracks energy costs across your tariff periods. It reads and writes Home Assistant entities published by GivTCP over MQTT. No cloud account is needed.

Tested on a GivEnergy GIV-HY-5.0 on the Electric Ireland Nightboost tariff. Current version: 0.7.0.

## What it does

- **Overnight charge target.** Works out how much to charge tonight from tomorrow's solar forecast and your usage, and writes it to GivTCP once a day, just before your cheapest rate period.
- **Immersion divert.** Heats water from spare solar, with a minimum temperature, a target and a restart gap.
- **EV signals.** Reports when solar surplus is available and where the car's power comes from. A Zappi is set to Eco+ when there is enough surplus.
- **Cost tracking.** Import cost, export earnings and per-load costs across cheap and base rates, with daily, weekly, monthly and yearly totals.
- **Bill estimate, battery health and ROI figures.** Plus a large set of sensors and six actions.

## Requirements

- Home Assistant 2026.2.0 or later (the minimum declared in `hacs.json`)
- [GivTCP](https://github.com/britkat1980/giv_tcp) publishing your inverter to Home Assistant over MQTT
- A GivEnergy hybrid inverter with a battery

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=macuistin&repository=givenergy_inverter_manager&category=integration)

**HACS:** open HACS, then Integrations, then Custom repositories. Add `https://github.com/macuistin/givenergy_inverter_manager` as an **Integration**, install it, and restart Home Assistant.

**Manual:** download the latest release from [Releases](https://github.com/macuistin/givenergy_inverter_manager/releases), copy `givenergy_inverter_manager/` into `config/custom_components/`, and restart Home Assistant.

## Set up

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=givenergy_inverter_manager)

Go to **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**. The wizard finds your GivTCP inverter and asks for your tariff. Turn on dry run first, so nothing is written to the inverter until you have checked the decisions. The [quick start](docs/quick-start.md) has the steps.

## Documentation

Start at the [documentation index](docs/index.md).

| Page | Contents |
|---|---|
| [Quick start](docs/quick-start.md) | Install, set up and check in ten minutes |
| [Concepts](docs/concepts.md) | Data flow, 30-second cycle, sign conventions, decisions |
| [Configuration](docs/configuration.md) | Every setup step and option |
| [Tariff](docs/tariff.md) | Rate periods, which rate wins, bill line items |
| [Sensors](docs/sensors.md) | Every sensor |
| [Entities](docs/entities.md) | Switches, numbers and the button |
| [Actions](docs/actions.md) | The six actions |
| [Dashboard](docs/dashboard.md) | The generated dashboard |
| [Energy dashboard](docs/energy-dashboard.md) | Sensors for the Home Assistant Energy dashboard |
| [Long-term statistics](docs/long-term-statistics.md) | State classes and midnight reset |
| [Automation examples](docs/automations.md) | Ready-to-use automations |
| [Troubleshooting](docs/troubleshooting.md) | Fixes by symptom |
| [Upgrade to v0.5.0](docs/upgrade-v0.5.0.md) | Battery Power sign change, Home Assistant 2026.2.0, new dashboard |
| [Upgrade to v0.3.0](docs/upgrade-v0.3.0.md) | What changed since v0.2.1 |
| [Uninstall](docs/uninstall.md) | Remove the integration and its files |
| [Roadmap](ROADMAP.md) | Planned work by priority, and what each release shipped |

## Development

```bash
pip install -r requirements-test.txt
python -m pytest tests -q           # stubbed unit suite, about 13 s
ruff check
python scripts/gen_sensor_docs.py   # regenerate docs/sensors.md after changing the sensor descriptions
```

The real Home Assistant suite (`tests/ha_e2e`) needs its own virtualenv. See [Testing](docs/testing.md).

A test fails when `docs/sensors.md` is out of date.

## Acknowledgements

- [GivTCP](https://github.com/britkat1980/giv_tcp), the GivEnergy MQTT bridge this integration builds on
- [Predbat](https://github.com/springfall2008/batpred), inspiration for accumulation and forecast accuracy patterns
- [Octopus Energy integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy), reference for HA quality scale patterns
- [cdpuk/givenergy-local](https://github.com/cdpuk/givenergy-local), structural reference for GivEnergy HA integrations
