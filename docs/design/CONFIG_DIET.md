# Config diet

Every option the wizards still ask for, with one decision each: detect it, make it an entity, make it a fixed assumption, or keep it as a field. Nothing in this review changes code. Each row that moves has a follow-up at the bottom.

The rule is one home per setting. A setting is a wizard field (set once, changes rarely) or a control (a knob you try, watch and adjust), never both. The seven tuning settings are already controls. The immersion target, minimum and restart gap temperatures are number entities. The forecast provider and the charger chooser were stored and never read, so they are gone.

## Decisions

| Setting (key) | Page | Decision | Why |
|---|---|---|---|
| Base rate (`base_rate`) | Tariff | Keep | A price on the bill. The integration cannot read a supplier's price |
| Export rate (`export_rate`) | Tariff | Keep | Same |
| Time-of-day rates (`rate_periods`) | Tariff rows | Keep | Names, rates and windows come from the tariff sheet. The count is not stored, it is the length of the list |
| Dated rate changes (`tariff_changes`) | Schedule a rate change | Keep | A date and a full set of rates, only the user knows them |
| Currency (`currency`) | Bill details | Detect | Starts from the Home Assistant currency, and the field stays so a bill in another currency can be entered. Changing it reloads, because it sets every money unit |
| Base rate name (`base_rate_name`) | Bill details | Keep | A label. Day is the default and most users never change it |
| Bill start day (`bill_start_day`) | Bill details | Keep | On the bill |
| Standing charge (`standing_charge_per_day`) | Bill details | Keep | On the bill |
| Fixed levy (`pso_levy_per_month`) | Bill details | Keep | On the bill. The key name is kept, the screen says per billing period |
| VAT (`vat_rate`) | Bill details | Keep | On the bill |
| Supplier discount (`discount_rate`) | Bill details | Keep | On the bill |
| Battery capacity (`battery_capacity_kwh`) | System, Battery | Detect | GivTCP reports it, so setup asks only when it did not. The field stays in Configure for a battery that grows |
| Inverter maximum output (`inverter_max_output_kw`) | System, Battery | Keep | GivTCP does not report it. The default is 5 kW and the field is always visible |
| Battery minimum charge (`battery_min_soc_pct`) | Charge planning | Keep | A protection level set once. It has a repair when set too high |
| Overnight charge cap (`overnight_charge_target_pct`) | Charge planning | Keep | A ceiling set once. The nightly target is calculated, and the manual override is its own entity |
| Battery cost (`battery_cost_eur`) | Battery | Keep | Not available from any device. A repair asks for it |
| Throughput budget (`battery_throughput_budget_kwh`) | Battery | Keep | Optional and off at 0. A candidate to hide if it stays unused |
| Winter months (`charge_winter_months`) | Charge planning | Keep | Set once. The default comes from the latitude and is not stored until edited. The seasons differ by hemisphere, so it cannot be a fixed assumption |
| Shoulder months (`charge_shoulder_months`) | Charge planning | Keep | Same as the winter months. A month cannot be in both lists |
| Plan winter charges from the forecast (`charge_winter_uses_forecast`) | Charge planning | Keep | Off keeps the 100% winter charge. On is for a home whose winter solar is worth planning around |
| Forecast sensor (`forecast_entity`) | Solar forecast | Detect | Solcast PV Forecast and Forecast.Solar sensors are found and used. The page is offered only when none was found |
| Day after tomorrow forecast (`forecast_entity_d2`) | Solar forecast | Detect | Found with Solcast. Optional otherwise |
| Pessimistic forecast (`forecast_entity_p10`) | Solar forecast | Fixed assumption | Solcast's own sensors carry the P10 in an attribute and the coordinator reads it when the field is empty. The field is only for other services |
| Carbon intensity sensor (`carbon_intensity_entity`) | Solar forecast | Keep | Optional. No single integration to detect |
| Immersion switch (`immersion_switch_entity`) | Hot water | Keep | Candidates with "immersion" in their name are listed, and none is chosen for the user. A wrong guess switches a real heater |
| Hot water temperature sensor (`immersion_temp_sensor_entity`) | Hot water | Keep | No reliable name to detect |
| Immersion element power (`immersion_wattage_w`) | Hot water | Keep | The default is 3000 W. See the follow-ups |
| Ready-by times (`immersion_ready_times`) | Hot water | Keep | Up to four a day. Four time entities cannot be empty, so each would need an enable switch. A field, or a schedule helper, fits better |
| Alternative heating on or off (`alt_heat_enabled`) | Hot water | Keep | Gates the whole feature |
| Alternative heating name, unit, cost, cost sensor (`alt_heat_label`, `alt_heat_cost_unit`, `alt_heat_cost`, `alt_heat_cost_entity`) | Hot water | Keep | The user's own words and prices. The oil efficiency and energy content stay fixed assumptions in the code |
| Car efficiency (`car_efficiency_kwh_per_100km`) | EV charger | Keep | Only used to turn kWh into km. Defaults to 15 and has no setup screen |
| The charger | none | Detect | Found automatically and re-found every few cycles. There is nothing to choose |
| The twelve wiring keys (`inverter_serial` and the eleven entity ids) | System, Reconfigure | Detect | Found by discovery. Reconfigure remaps them |

## Follow-ups

None of these changes anything in 0.18.0. They are candidates for a later release, in the order they save the user a question.

1. **Read the capacity live.** Take the battery capacity from GivTCP on every cycle when it reports one, so adding a module needs no visit to Configure.
2. **Suggest the rates from GivTCP.** GivTCP holds a day, night and export rate that the integration already compares with its own. Offer them as the starting values of the tariff screen.
3. **Learn the element power.** Measure the immersion's power from the house load when the heater switches on, and keep the field as an override.
4. **Drop the P10 field for Solcast users.** Hide it when the forecast sensor carries `estimate10`.
5. **Ready-by times without a field.** A schedule helper or a set of enable switches, so the times can be changed from the dashboard like the other controls.
6. **Hide the throughput budget** under an advanced tick unless it is already set.
