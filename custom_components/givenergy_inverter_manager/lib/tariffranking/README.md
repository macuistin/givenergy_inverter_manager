# lib/tariffranking

Prices every plan over the same measured usage and ranks them, cheapest first, with the current
plan's rank always known. It is a re-pricing of past usage, never a forecast, and it writes
nothing. It needs no Home Assistant objects and no network.

## Public names

- `Window`, `Unit`: how far back to look, in weeks or whole bills (`MAX_WEEKS`, `MAX_BILLS`)
- `ranges`, `DayRange`: the day ranges a window covers, ending on a day or the last whole bill
- `Usage`: the slot history, the day ranges and the holiday calendar
- `Candidate`: a plan to price, with the export rate a user typed for a plan that lists none
- `search`, `price_ranges`: price the current plan and every candidate and rank them
- `SearchResult`, `Ranked`: the ranked list, the current rank and what data the window held
- `needs_export_rate`, `with_export_rate`: plans that list no export price
- `rank_sentence`, `TOP`: where the current plan stands, in words

## Allowed dependencies

The standard library and `lib/tariff`. Nothing else.

## Behaviour to know

- A plan with no export price is priced with the rate the user gave, or left out and counted in
  `skipped`.
- The current plan is priced as saved, since an export rate of 0 is a real choice for it.
- Ties go to the current plan, then to the label.
- Every plan is priced over the same days by the same bill engine, so the totals are like for
  like and the difference is down to the rates.

The integration `macuistin/givenergy_inverter_manager` began this code as `core/shadow_search.py`
and it moved here so there is one copy to maintain.
