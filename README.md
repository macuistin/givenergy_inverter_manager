# GivEnergy Inverter Manager

[![GitHub Release](https://img.shields.io/github/release/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/releases)
[![GitHub Activity](https://img.shields.io/github/commit-activity/y/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](https://github.com/macuistin/givenergy_inverter_manager/commits/main)
[![License](https://img.shields.io/github/license/macuistin/givenergy_inverter_manager.svg?style=for-the-badge)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![Tests](https://img.shields.io/github/actions/workflow/status/macuistin/givenergy_inverter_manager/tests.yml?style=for-the-badge&label=Tests)](https://github.com/macuistin/givenergy_inverter_manager/actions/workflows/tests.yml)

A Home Assistant integration for GivEnergy inverters. It works out how much to charge overnight, diverts spare solar to your immersion heater and EV charger, and tracks your energy costs across multiple tariff periods. Everything runs locally via GivTCP over MQTT — no cloud account needed.

Tested on a GivEnergy GIV-HY-5.0 with a 19kWh battery on the Electric Ireland Nightboost tariff.

<!-- screenshot: dashboard overview showing all four tabs -->

---

## What it does

- **Overnight charge optimisation** — calculates the minimum charge target for the night based on tomorrow's solar forecast and your usage history. Avoids overcharging when the sun is going to do the work anyway.
- **Solar surplus diversion** — turns on your immersion heater and/or EV charger when the battery is full and solar is generating more than the house needs.
- **Cost tracking** — tracks import cost, export earnings, and per-load costs (EV, immersion, rest of house) across cheap and peak rate periods, with daily, weekly, and monthly totals.
- **Charge plan reporting** — generates a readable summary of tonight's charge plan and today's energy flows, viewable directly in a dashboard Markdown card.

---

## Requirements

- Home Assistant 2024.1.0 or later
- [GivTCP](https://github.com/britkat1980/giv_tcp) v3 running as a Home Assistant add-on, publishing inverter data over MQTT
- A GivEnergy hybrid inverter with battery storage

---

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=macuistin&repository=givenergy_inverter_manager&category=integration)

**Via HACS:**
1. Open HACS → Integrations → Custom repositories
2. Add `https://github.com/macuistin/givenergy_inverter_manager`, category **Integration**
3. Install **GivEnergy Inverter Manager** and restart Home Assistant

**Manual:**
1. Download the latest release zip from [Releases](https://github.com/macuistin/givenergy_inverter_manager/releases)
2. Extract `givenergy_inverter_manager/` into `config/custom_components/`
3. Restart Home Assistant

---

## Setup

[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=givenergy_inverter_manager)

Go to **Settings → Devices & Services → Add Integration** and search for **GivEnergy Inverter Manager**. The setup wizard will auto-discover your inverter via GivTCP and walk you through tariff configuration.

See [docs/configuration.md](docs/configuration.md) for a full walkthrough.

---

## Documentation

| | |
|---|---|
| [Configuration](docs/configuration.md) | Setup wizard walkthrough, all options explained |
| [Tariff setup](docs/tariff.md) | Rate periods, Nightboost, PSO levy, VAT |
| [How it works](docs/how-it-works.md) | Charge logic, immersion divert, EV protection |
| [Entities](docs/entities.md) | Every sensor, switch, and number entity |
| [Dashboard](docs/dashboard.md) | Setting up the built-in dashboard |
| [Troubleshooting](docs/troubleshooting.md) | Common problems and fixes |
| [Automation examples](docs/automations.md) | Ready-to-use HA automations |

---

## Development

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -q
ruff check custom_components/givenergy_inverter_manager/ tests/
```

---

## Acknowledgements

- [GivTCP](https://github.com/britkat1980/giv_tcp) — the GivEnergy MQTT bridge this integration builds on
- [Predbat](https://github.com/springfall2008/batpred) — inspiration for accumulation and forecast accuracy patterns
- [Octopus Energy integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy) — reference for HA quality scale patterns
- [cdpuk/givenergy-local](https://github.com/cdpuk/givenergy-local) — structural reference for GivEnergy HA integrations