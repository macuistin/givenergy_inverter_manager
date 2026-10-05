# Upgrade notes: v0.4.x to v0.5.0

v0.5.1 only changes the device manufacturer shown on the device page, from GivEnergy to `macuistin`. The device name, model and entity IDs are unchanged. These notes apply to both versions.

## Before you upgrade

- **Home Assistant 2026.2.0 or later is required.** The new dashboard layout needs it. This is the minimum declared in `hacs.json`.
- **Battery Power changed sign.** The Battery Power sensor is now positive while charging and negative while discharging. In v0.4.x it copied GivTCP's raw sign, where charging is negative. Check any automation, template or card that reads it. The generated dashboard's power flow card is already updated.

## Do this after upgrading

1. Update through HACS and restart Home Assistant.
2. Search your automations, templates and cards for the Battery Power sensor and flip the sign where it matters.
3. Press **Refresh Dashboard** on the device page, or run the `get_dashboard_yaml` action, and paste the new file over the old dashboard. The layout is new, so an old copy does not match it. See [Dashboard](dashboard.md).
4. Open **Settings → System → Repairs**. Clear any "no longer has a state class" repairs in **Developer Tools → Statistics**. See [Troubleshooting](troubleshooting.md#repairs-say-a-sensor-no-longer-has-a-state-class).

Existing setups keep working.

## What changed

| Area | Change |
|---|---|
| Battery Power | Positive while charging. See above |
| Battery energy | Battery charged and discharged energy, round-trip efficiency and self-sufficiency were wrong because the power sign was inverted. They are now correct. The managed immersion switch toggling came from the same cause |
| Dashboard | Rebuilt as sections of tiles with six sub-views: Immersion, EV charger, Cost breakdown, Solar and forecast, Tariff and Battery detail. Phone heights are shorter, labels no longer truncate, and the immersion power chart plots watts as a step line |
| Night survival | Night survival and the overnight charge plan use the same window, and the plan no longer skips a night that survival calls Critical |
| Night Survival Confidence | Its attributes explain the level, and the Battery detail view shows the reason |
| Zappi | A missing Zappi power entity is logged once, not every five minutes |

## State class repairs

Home Assistant raises "no longer has a state class" repairs for the yesterday and trailing 12-month sensors and for the solar forecast sensor. These sensors hold snapshot values, not running totals, so they have no state class. The statistics Home Assistant already holds for them are stale. The repairs have no Fix button. Open **Developer Tools → Statistics**, choose **Fix issue** on each sensor and delete its old statistics. If you already cleared them after v0.4.0, nothing is left to do. See [Long-term statistics](long-term-statistics.md#upgrading-statistics-that-change).

## Upgrading from v0.3.0 or earlier

Read [Upgrade notes for v0.3.0](upgrade-v0.3.0.md) as well.
