# GivEnergy Inverter Manager

Home Assistant integration for GivEnergy inverters. It reads inverter data from GivTCP over MQTT, sets the overnight charge target, diverts spare solar to an immersion heater, and tracks energy costs across your tariff periods. Nothing leaves your network: the integration only reads and writes Home Assistant entities.

This documentation matches version 0.16.0.

## Start here

| Page | Use it to |
|---|---|
| [Quick start](quick-start.md) | Install, set up and check the integration in ten minutes |
| [Concepts](concepts.md) | Understand the data flow, the 30-second cycle, sign conventions and how decisions are made |
| [Configuration](configuration.md) | Look up every setup step and option |
| [Tariff](tariff.md) | Enter rate periods, see which rate wins, and see how bill figures are built |

## Reference

| Page | Contents |
|---|---|
| [Sensors](sensors.md) | Every sensor with unit, state class and enabled-by-default (generated from the code) |
| [Entities](entities.md) | Switches, numbers and the button |
| [Actions](actions.md) | The six actions the integration registers |
| [Dashboard](dashboard.md) | The generated Lovelace dashboard and the HTML report cards |
| [Energy dashboard](energy-dashboard.md) | Which sensors to pick in Home Assistant's Energy dashboard |
| [Long-term statistics](long-term-statistics.md) | Why daily sensors use state class `total` and reset at midnight |
| [Automation examples](automations.md) | Ready-to-use automations |

## Operate

| Page | Contents |
|---|---|
| [Troubleshooting](troubleshooting.md) | Fixes listed by symptom |
| [Upgrade notes for v0.5.0](upgrade-v0.5.0.md) | Battery Power sign change, Home Assistant 2026.2.0 minimum, new dashboard and state class repairs |
| [Upgrade notes for v0.3.0](upgrade-v0.3.0.md) | What changed since v0.2.1 and what to check |
| [Uninstall](uninstall.md) | Remove the integration and its files |
| [Roadmap](../ROADMAP.md) | Planned work by priority |
| [Changelog](../CHANGELOG.md) | What each release shipped |
| [Testing](testing.md) | Run the stubbed and the real Home Assistant test suites (for contributors) |

## Diagrams

Mermaid sources. GitHub renders them, or paste one into the [Mermaid live editor](https://mermaid.live).

| Diagram | Shows |
|---|---|
| [Module architecture](architecture.mermaid) | Which module calls which, and the line between the Home Assistant layer and the pure logic in `core/` |
| [30-second update cycle](update-cycle.mermaid) | One coordinator cycle and the nightly charge target write |
| [Tariff rate precedence](tariff-precedence.mermaid) | How the current rate is chosen |
| [Immersion decision](immersion-logic.mermaid) | The divert rules, the cooldown and manual overrides |
| [EV charger decision](ev-charger-logic.mermaid) | When the integration selects Eco+ |

The charge target rules are in [Concepts](concepts.md#overnight-charge-target). A flowchart of them would only duplicate that list.

## Requirements

- Home Assistant 2026.2.0 or later. This is the minimum declared in `hacs.json`.
- [GivTCP](https://github.com/britkat1980/giv_tcp) publishing your inverter to Home Assistant over MQTT. Discovery accepts the GivTCP v3 and v2 battery SoC entity names.
- A GivEnergy hybrid inverter with a battery.

Charge targets can only be written when GivTCP exposes its charge control entities. See [Configuration](configuration.md#step-1-inverter).
