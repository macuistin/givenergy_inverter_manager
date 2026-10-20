# GivEnergy Inverter Manager

[![GitHub Release](https://img.shields.io/github/release/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/commits/main)
[![License](https://img.shields.io/github/license/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![Tests](https://img.shields.io/github/actions/workflow/status/macuistin/givenergy_inverter_manager/tests.yml?style=for-the-badge&label=Tests)](https://github.com/macuistin/givenergy_inverter_manager/actions/workflows/tests.yml)

A Home Assistant integration for GivEnergy inverters. It sets the overnight charge target, diverts spare solar to an immersion heater, and tracks energy costs across your tariff periods. It reads and writes Home Assistant entities published by GivTCP over MQTT. No cloud account is needed.

Works with a flat rate, a day and night rate, or up to five timed rates, from any supplier. It does not support dynamic or half-hourly tariffs. The bill estimate assumes monthly bill periods, one supplier discount, one VAT rate and one flat levy per period. Tested on real hardware on one GivEnergy GIV-HY-5.0 (a single-phase hybrid) with the Electric Ireland Nightboost tariff. Other GivTCP system types are recognised and tested against entity lists only. See [Which serial do I use?](docs/quick-start.md#which-serial-do-i-use). Current version: 0.19.13b1.

![The Home energy page of the dashboard: the live power flow, what the house runs on now, today so far and buttons for the detail pages.](https://raw.githubusercontent.com/macuistin/givenergy_inverter_manager/main/docs/images/dashboard-home-energy.png)

## What it does

- **Overnight charge target.** Works out how much to charge tonight from tomorrow's solar forecast and your usage, and writes it to GivTCP once a day, just before your cheapest rate period.
- **Immersion divert.** Heats water from spare solar, with a minimum temperature, a target and a restart gap.
- **EV signals.** Reports when solar surplus is available and where the car's power comes from. A Zappi is set to Eco+, and a GivEnergy charger to Solar, when there is enough surplus. The GivEnergy charger has not been tested on real hardware.
- **Cost tracking.** Import cost, export earnings and per-load costs across your timed and base rates, with daily, weekly, monthly and yearly totals.
- **Bill estimate, battery health and ROI figures.** Plus a large set of sensors and five actions.

## Requirements

- Home Assistant 2026.5.0 or later (the minimum declared in `hacs.json`). Home Assistant 2026.5 itself needs Python 3.14.2 or newer
- [GivTCP](https://github.com/britkat1980/giv_tcp) publishing your inverter to Home Assistant over MQTT
- A GivEnergy inverter with a battery. A single-phase hybrid is the only type tested on real hardware. AC-coupled, All-In-One, three-phase, Gateway and EMS systems are recognised, and the setup screen says which are not tested. On a three-phase hybrid, setup does not find the grid and battery power entities, because GivTCP publishes each as a pair

## Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=macuistin&repository=givenergy_inverter_manager&category=integration)

**HACS:** open HACS, then Integrations, then Custom repositories. Add `https://github.com/macuistin/givenergy_inverter_manager` as an **Integration**, install it, and restart Home Assistant.

**Manual:** download the latest release from [Releases](https://github.com/macuistin/givenergy_inverter_manager/releases), copy `givenergy_inverter_manager/` into `config/custom_components/`, and restart Home Assistant.

## Set up

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=givenergy_inverter_manager)

Go to **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**. The wizard finds your GivTCP inverter, and an EV charger and a solar forecast sensor if you have them. It then asks what to set up now, and for your tariff, taken from your bill. A flat-rate home with nothing else is three screens. A new install starts in dry run, so nothing is written to the inverter until you have checked the decisions and turned the Dry run switch off. The [quick start](docs/quick-start.md) has the steps.

## Documentation

Start at the [documentation index](docs/index.md).

| Page | Contents |
|---|---|
| [Quick start](docs/quick-start.md) | Install, set up and check in ten minutes |
| [Concepts](docs/concepts.md) | Data flow, 30-second cycle, sign conventions, decisions |
| [Configuration](docs/configuration.md) | Every setup screen and option |
| [Tariff](docs/tariff.md) | Rate periods, which rate wins, bill line items |
| [Sensors](docs/sensors.md) | Every sensor |
| [Entities](docs/entities.md) | Switches and numbers |
| [What we know about GivTCP](docs/givtcp.md) | For maintainers: how we find, read and write the inverter through GivTCP |
| [Actions](docs/actions.md) | The five actions |
| [Dashboard](docs/dashboard.md) | The dashboard that builds itself, and how to add it |
| [Energy dashboard](docs/energy-dashboard.md) | Sensors for the Home Assistant Energy dashboard |
| [Long-term statistics](docs/long-term-statistics.md) | State classes and midnight reset |
| [Automation examples](docs/automations.md) | Ready-to-use automations |
| [Troubleshooting](docs/troubleshooting.md) | Fixes by symptom |
| [Upgrade to v0.5.0](docs/upgrade-v0.5.0.md) | Battery Power sign change, Home Assistant 2026.2.0, new dashboard |
| [Upgrade to v0.3.0](docs/upgrade-v0.3.0.md) | What changed since v0.2.1 |
| [Uninstall](docs/uninstall.md) | Remove the integration and its files |
| [Roadmap](ROADMAP.md) | Planned work by priority |
| [Changelog](CHANGELOG.md) | What each release shipped |

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
