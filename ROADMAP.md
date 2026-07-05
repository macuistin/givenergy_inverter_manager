# GivEnergy Inverter Manager — Roadmap & Future Ideas

This document captures everything that has been considered, partially designed, or
flagged as a future improvement during development. It is organised by theme and
priority. Items marked **[DONE]** are already implemented.

---

## Current State (v0.1.0)

### What is built and working

- **GivTCP auto-discovery** — scans HA for `sensor.givtcp_{SERIAL}_*` entities and
  pre-fills the setup form
- **Multi-brand EV charger discovery** — Zappi (myenergi), Wallbox, OCPP, Ohme, Easee
- **Zappi battery protection** — detects when the Zappi is draining the battery and
  switches it to `Stopped`; resumes `Eco+` when battery recovers and solar surplus
  is available
- **Overnight charge calculator** — uses Forecast.Solar or Solcast (or seasonal
  fallback) to decide how much to charge from grid overnight; skips charging entirely
  when battery is high and forecast is strong
- **Solar surplus → immersion divert** — turns on immersion heater when battery is
  full and solar is generating surplus; respects water temperature limits
- **Appliance run suggestions** — advises when to run high-load appliances based on
  solar surplus and tariff
- **Full financial P&L** — import cost (per rate period), export earnings,
  self-consumption value, per-load cost (EV, immersion, rest of house)
- **Bill prediction** — accrued bill, projected total, days remaining, using
  standing charge, PSO levy, VAT, and supplier discount correctly
- **Battery health tracking** — cycle count, remaining life %, days since full charge,
  estimated years remaining
- **Night survival prediction** — estimates SoC at sunrise and warns if battery may
  run out before solar starts
- **Dynamic multi-rate tariff** — any number of rate periods including overnight
  (e.g. Night 23:00–08:00 with Nightboost 02:00–04:00 override); editable via
  options flow without reinstalling
- **Configurable currency** — EUR, GBP, USD, SEK, NOK, DKK, AUD, CAD, NZD, ZAR
- **Midnight accumulator reset** — daily energy totals reset automatically
- **Options flow tariff updates** — tariff changes apply on next 30s update cycle
  without HA restart
- **Manual overrides** — charge target slider (0=auto), auto-immersion toggle,
  skip-charge-tonight switch
- **Integration icon** — custom PNG icon and logo for HA frontend
- **HACS-ready** — `hacs.json`, `manifest.json`, `strings.json`, `translations/en.json`
- **162 unit tests** — 100% coverage of all pure logic modules

---

## Near-Term (v0.2.0)

### Persistent energy statistics

**Problem:** Daily energy accumulators reset on HA restart, losing data mid-day.

**Solution:** Use HA's `RestoreEntity` pattern or write totals to a JSON file in the
config directory on each update cycle. The simplest approach is to write to
`<config>/.storage/givenergy_inverter_manager_stats.json` on every midnight reset and
restore it on startup.

**Complexity:** Low — 2-3 hours work.

---

### Monthly and annual export volume tracking

The bill already shows 500 kWh exported in one month. The integration should track:
- Export kWh per calendar month (persisted)
- Rolling 12-month export total
- Alert when export volume is high enough to justify renegotiating the CEG rate with
  the supplier (currently €0.195/kWh from Electric Ireland — other suppliers offer more)

**Complexity:** Low — extend the accumulator and add monthly reset logic.

---

### Write overnight charge target to GivTCP

Currently the integration *recommends* a charge target via the
`overnight_charge_target` sensor but does not actually set it on the inverter.
The GivTCP control entity `number.givtcp_{SERIAL}_target_soc` is already discovered
and stored in config as `CONF_TARGET_SOC_ENTITY`.

**What needs doing:**
1. At the start of the cheapest rate window (e.g. 11pm), call
   `number.set_value` on `number.givtcp_{SERIAL}_target_soc` with the recommended value
2. Handle the edge case where GivTCP is offline at that moment (retry logic)
3. Add a "apply charge target" switch so users can enable/disable this automation

**Complexity:** Medium — the entity discovery is done, just need the time-triggered
service call with retry.

---

### Solcast multi-array support

The PVSol report shows 10 panels facing west (272°) and 10 facing east (92°).
Solcast supports registering multiple roof faces as separate rooftop sites, giving
more accurate forecasts than a single-site estimate.

The integration should:
- Accept two forecast entities (east array + west array)
- Sum them for the overnight charge decision
- Track each separately for panel performance monitoring

**Complexity:** Low — config flow already supports one entity; add a second optional one.

---

### Forecast accuracy tracking

After each day, compare:
- What Forecast.Solar/Solcast predicted
- What GivTCP actually recorded

Track mean absolute error (MAE) over 30 days. Surface this as a sensor so users
know how much to trust the forecast. If accuracy is consistently low (>30% error),
fall back to the seasonal estimate automatically.

**Complexity:** Medium.

---

## Medium-Term (v0.3.0)

### Second immersion element / heat pump water cylinder

Some homes have a dual-element cylinder (lower element for solar, upper for backup)
or a heat pump hot water unit. The integration should support:
- Two immersion switches with independent thresholds
- Heat pump water heater as a separate controllable load
- COP-aware cost calculation for heat pump (1 kWh electricity → ~3 kWh heat)

**Complexity:** Medium — extend config flow with a second optional immersion.

---

### Storage heater support

Storage heaters charge overnight on cheap-rate electricity and discharge heat during
the day. They are common in Irish homes. The integration could:
- Track storage heater consumption overnight
- Coordinate charging with the battery — if battery is full, prioritise storage heater
  charging during Nightboost; if battery is low, skip storage heater
- Estimate heat stored and remaining (based on charge time and heater rating)

**Complexity:** Medium — requires a smart plug or CT clamp on the heater circuit.

---

### Year-on-year comparison

Once 12 months of data is collected:
- Compare current month vs same month last year
- Show whether the system is improving or degrading
- Flag if annual consumption is trending above the CRU average

The PVSol report shows 13,219 kWh/year vs CRU average of 4,200 kWh — significantly
above average. The integration should flag whether solar + battery is actually reducing
this over time.

**Complexity:** Medium — requires 12 months of persisted monthly totals.

---

### Multiple EV charger support

Currently only the first discovered charger is used. Homes with two EVs
(or one EV and one e-bike charger) need:
- Discovery of all chargers
- Individual cost tracking per charger
- Coordinated charging priority (e.g. car 1 charges first, car 2 only if surplus)
- Config flow to assign priorities

**Complexity:** Medium.

---

### Tariff comparison tool

Accumulate enough real consumption data to model what the bill would have been on:
- A flat rate (single unit price)
- The current multi-rate tariff
- Other known Irish tariffs (Energia, SSE Airtricity, Pinergy)

This helps users answer "should I switch supplier?" with their own data rather than
generic estimates.

**Complexity:** Medium-high — requires modelling other tariffs and storing hourly
consumption data.

---

## Longer-Term (v1.0+)

### GivEnergy administration resilience

GivEnergy entered administration in April 2026. The integration already uses local
control via GivTCP (no cloud dependency), but:

1. **Export data backup** — periodically export all historical data (energy, cost,
   battery cycles) to a CSV or Home Assistant backup. If GivTCP stops working due to
   firmware issues, users should have their data.

2. **givenergy-local fallback** — the `givenergy-local` HACS integration (by cdpuk)
   also communicates with the inverter via Modbus. The integration should detect
   whichever is installed and use it.

3. **Documentation for migration** — if users need to move to a different inverter
   brand, document how to re-use the tariff and financial data with other integrations.

---

### Heat pump integration

Many GivEnergy users also have or are considering an ASHP. The integration could:
- Track heat pump energy consumption separately
- Model the interaction between battery charging and heat pump demand
- Adjust overnight battery charge target based on whether the heat pump will run
  (cold weather forecast → higher charge target)
- Track CoP over time

**Complexity:** High — requires integrating with Mitsubishi Ecodan, Daikin, or
similar HA heat pump integrations.

---

### Demand response / grid stress events

EirGrid (Ireland's grid operator) occasionally broadcasts demand response signals
during grid stress events. The integration could:
- Monitor EirGrid grid frequency or a demand response signal
- Temporarily halt battery discharge during grid stress (or conversely, export
  more to support the grid if export tariff allows it)
- Integrate with EirGrid's API when/if one becomes available

**Complexity:** High — requires EirGrid API integration.

---

### Carbon intensity optimisation

Although flagged as not relevant for this installation, it may become relevant as
the Irish grid decarbonises. The CO2Signal API provides real-time grid carbon
intensity for Ireland. Future option:
- Prefer grid import during low-carbon periods (high wind generation)
- Export preferentially during high-carbon periods
- Track avoided carbon vs the grid average (currently showing 100kg/month on the bill)

**Complexity:** Low once the decision is made to include it.

---

### Predictive immersion scheduling

Currently the immersion activates reactively when solar surplus is available.
A smarter approach:
- Check the morning weather forecast
- If solar generation is predicted to be low today, run the immersion from grid
  during Nightboost (cheapest rate) to ensure hot water availability
- This prevents scenarios where the water runs cold on a cloudy day

**Complexity:** Medium — requires coordinating immersion with forecast and rate windows.

---

### Multi-inverter support

GivEnergy systems can have multiple inverters (e.g. a gateway + AIO configuration
with two 9.5kWh batteries each). The integration currently uses only the first
discovered GivTCP inverter.

Support needed for:
- Summing solar power across multiple inverters
- Averaging or summing battery SoC
- Aggregate financial tracking
- Config flow to select multiple inverters

**Complexity:** Medium — entity discovery already supports it; coordinator needs
aggregation logic.

---

### HA Energy Dashboard integration

HA's built-in Energy Dashboard requires sensors with specific `device_class` and
`state_class` values:
- `sensor_class: energy` + `state_class: total_increasing` for import/export/solar

The integration already creates these sensors correctly. A setup guide should walk
users through adding the integration's sensors to the Energy Dashboard, which provides
HA's native visualisation without any custom cards.

**Complexity:** Documentation only — the sensors already exist.

---

---

## Visualisation Add-ons (companion HACS repositories)

The integration exposes 80+ sensors and three HTML report sensors, but sensor data
and HTML tables only go so far. A set of purpose-built Lovelace add-ons would let
users see their system at a glance without building dashboards from scratch.

These are planned as **separate HACS repositories** that depend on this integration —
not bundled in — keeping the integration itself lightweight and the cards independently
versioned.

### Power Flow Card

A real-time animated card showing energy flowing between solar panels, battery,
house, grid, immersion heater, and EV charger. Current power values update every
30 seconds alongside the integration.

Inspired by the `power-flow-card-plus` card from HACS, but pre-configured for
GivEnergy Inverter Manager entity IDs — zero setup beyond adding the card. Key
design goals:
- Works out of the box with no entity mapping required
- Shows charge/discharge direction, surplus, and clipping state
- Colour-coded by power source (solar = amber, grid = red, battery = green)

**Likely implementation:** React or Lit custom element registered as
`givenergy-power-flow-card`. Config auto-discovers entities from the integration's
device registry entry.

---

### Energy History Card

An ApexCharts-based card showing daily energy and cost history as a stacked bar
chart. Fetches from HA's long-term statistics database using the `statistics`
WebSocket API. Overlays:
- Solar generated (amber bars)
- Import at cheap vs peak rate (green/red split bars)
- Export earnings (dotted overlay)
- Immersion savings (green line)

The weekly/monthly/yesterday sensors added in v0.2.0 provide the reset-aware totals;
this card renders the full history from HA's statistics store.

**Likely implementation:** Config card wrapping the `custom:apexcharts-card` pattern,
with a pre-built series definition that maps to the integration's sensor keys.

---

### Charge Plan Timeline Card

A compact timeline view of tonight's plan:
- Horizontal time axis covering the cheap-rate window to solar start
- Battery SoC trajectory line
- Rate period bands as coloured background regions (Night, Nightboost, Day)
- Charge target marker
- Forecast solar ramp from sunrise

Useful for a quick sanity check before bed: "is the integration going to charge
tonight, and to what level?"

**Likely implementation:** SVG canvas card, no external chart library dependency.

---

### HTML Report Templates

The three built-in HTML report sensors (`today_summary`, `charge_plan`,
`week_summary`) render in the standard Markdown card. A companion HACS repository
will provide:
- A pre-built dashboard YAML using these sensors as the primary views
- A `custom:givenergy-report-card` wrapper that adds refresh button, last-updated
  timestamp, and card header with the integration logo
- Template snippets for Telegram / mobile notification formatting using the short
  state strings

---

### Status & Versioning

These add-ons do not exist yet. They are planned for development after the
integration reaches a stable v1.0 release with a committed sensor naming convention.
Breaking sensor renames before v1.0 would require parallel updates to all cards.

Timeline: **after v1.0** — exact repository names and URLs to be confirmed.

## Technical Debt & Code Quality

### Coordinator: energy accumulation precision

The current integration-based accumulation (power × elapsed time) introduces small
errors compared to using GivTCP's own energy counters (`pv_energy_today_kwh`,
`import_energy_today_kwh` etc.) which are more accurate as they come from the inverter
itself. A future version should use GivTCP energy sensors directly where available,
falling back to integration only when the sensor is unavailable.

---

### Config flow: multi-step EV charger configuration

The current EV step is a single form. A better UX would be a sub-flow that:
1. Shows discovered chargers
2. Lets the user confirm entity mapping
3. Asks car-specific questions (efficiency, battery size)
4. Tests that the charge mode entity is writable

---

### Translations

Currently only `en.json` exists. The integration is used by people in Ireland,
UK, Sweden, Norway, Denmark, Australia, Canada, New Zealand, and South Africa
(all currency options). Translations for `ga` (Irish), `sv` (Swedish), `nb`
(Norwegian) would be a valuable community contribution.

---

### pytest-homeassistant-custom-component

The test suite uses manual HA stubs in `conftest.py`. The proper approach for
integration tests is `pytest-homeassistant-custom-component`, which provides a
real lightweight HA test environment. This would allow:
- Testing the config flow steps end-to-end
- Testing coordinator setup/teardown
- Testing entity availability and state changes

The pure logic tests would remain as-is; the HA integration tests would supplement them.

**Complexity:** Medium — requires setting up the test environment and rewriting
coordinator/config_flow tests.

---

## Known Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| Energy accumulators reset on HA restart | Daily totals lost | Planned persistence in v0.2.0 |
| Only one EV charger supported | Multi-EV homes | Planned in v0.3.0 |
| Zappi Eco+ competes with battery for solar | Suboptimal solar allocation | Mitigated by pause/resume strategy; full resolution requires real-time power sharing which the Zappi does not support natively |
| Forecast.Solar less accurate for east-west arrays | Overnight charge target may be slightly wrong | Solcast supports multi-array; guide users to set up dual sites |
| GivTCP must be installed and running | Hard dependency | Document clearly; detection in place |
| No write-back to inverter charge target yet | User must manually apply recommendation | Planned v0.2.0 |
| Bill prediction assumes constant daily usage | Inaccurate early in billing period | Improves over time as more data is collected |

---

## Changelog

### v0.1.0 (initial release)
- Full implementation as described in Current State above
- 162 unit tests, 100% coverage of pure logic modules
- HACS-compatible with icon, strings, translations
