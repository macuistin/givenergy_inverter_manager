# Tariff setup

The integration needs to know your electricity tariff to calculate overnight charge costs, bill projections, and the value of solar surplus. This page explains every field and shows a complete Electric Ireland Nightboost example.

---

## Rate periods

Most tariffs have a standard daytime rate plus one or more cheaper windows at night. You enter these as named rate periods.

<!-- screenshot: rate period section expanded showing Night and Nightboost slots -->

Each slot has four fields:

| Field | Example |
|---|---|
| **Name** | Nightboost |
| **Rate** | 0.0965 EUR/kWh |
| **Window start** | 02:00 |
| **Window end** | 04:00 |

Leave a slot's name blank and it will be ignored. You can define up to five periods.

The **Base rate** field at the top of the Tariff section is what applies outside any named window. Give it a name too (e.g. "Day") — that name appears in the Current Rate Period sensor on the dashboard.

---

## Electric Ireland Nightboost example

Nightboost has three distinct rates:

| Period | Rate | Window |
|---|---|---|
| Day (base rate) | €0.3334/kWh | All other hours |
| Night | €0.1644/kWh | 23:00 – 08:00 |
| Nightboost | €0.0965/kWh | 02:00 – 04:00 |

Enter this as:

- **Base rate**: 0.3334, name: Day
- **Rate period 1**: Night, 0.1644, 23:00 – 08:00
- **Rate period 2**: Nightboost, 0.0965, 02:00 – 04:00
- Rate periods 3–5: leave blank

The overnight charge calculator will use the Nightboost window (02:00–04:00) as the cheap charging window.

---

## Overlapping windows

When two windows overlap (as Night and Nightboost do), the integration always uses the cheapest rate that applies at any given time. At 03:00, Nightboost (€0.0965) takes precedence over Night (€0.1644).

---

## Other fields

| Field | Notes |
|---|---|
| **Export / CEG rate** | What you get paid per kWh sent to the grid. Electric Ireland Clean Export Guarantee rate is typically around €0.18/kWh — check your most recent bill. |
| **Standing charge** | Daily fixed charge in EUR. Find this on your bill. |
| **PSO levy** | Public Service Obligation levy, charged monthly. Currently around €3–4/month for most Irish households. Set to 0 if you're not in Ireland. |
| **VAT rate** | 9% for electricity in Ireland (reduced rate). |
| **Supplier discount** | Enter your loyalty or online discount as a percentage if you have one. |
| **Bill start day** | The day of the month your billing period starts — check your bill. Affects the accrued bill and projected total sensors. |
| **Currency** | Affects the € symbol shown on sensors. EUR for Ireland. |

---

## Where these numbers come from

Your unit rates, standing charge, and export rate are all on your electricity bill. If you're unsure, the Electric Ireland website shows current Nightboost tariff rates. The PSO levy and VAT rate are set nationally and updated annually — check [energyregulator.ie](https://www.energyregulator.ie) for current figures.