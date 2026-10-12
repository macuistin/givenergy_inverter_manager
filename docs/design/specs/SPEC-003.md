# SPEC-003: load history, weighting and away mode

> **Where the parts of the 0.19 plan are.** This plan was written as one file in four parts. References such as "Part A" or "Part B section 1.5" mean:
> 
> | Part | File |
> |---|---|
> | Part 0 (instructions for the agent) | [RELEASE_0.19_AGENT_NOTES.md](RELEASE_0.19_AGENT_NOTES.md) |
> | Part A (the release brief) | [RELEASE_0.19_BRIEF.md](RELEASE_0.19_BRIEF.md) |
> | Part B (design pack for the roadmap features) | [FEATURE_DESIGNS.md](FEATURE_DESIGNS.md) |
> | Part C (specifications extracted from other projects) | [specs/](specs/README.md) |
> | Part D (gap analysis) | [GAP_ANALYSIS.md](GAP_ANALYSIS.md) |
> 


**Source:** Predbat, `fetch.py` (the weighted-bucket load forecast and the holiday history helper) and `docs/customisation.md`, read October 2026 from a shallow clone. **Nothing here is code.** **Feeds:** C28 (away mode), S5, the learned load profile.

#### What it does
It predicts the house's energy for each future five-minute step from earlier days at the same time of day, weighting each earlier day by how alike it is, and treating "away" days as a separate population.

#### Inputs
- The household load history, as energy per five-minute step, for up to a configured number of past days (bounded by what history exists).
- The number of away days left (a whole number, counted including today, reduced by one at midnight). Zero means at home.
- A recorded history of that away-days value, so that each past sample knows whether the household was away when it was recorded.
- An assumed away load as a fraction of normal (clamped to 0.1 to 1.0).

#### Behaviour
1. **Window.** Use the smaller of the days of history available and one less than the configured maximum number of days. If less than one day exists, return nothing.
2. **Weight of one past day** is `weekday factor x age factor`:
   - weekday factor 1.0 if the past day is the same weekday as today; 0.7 if both are weekdays or both are weekend days; 0.5 if one is a weekday and the other a weekend day. Between two away days it is held at 1.0, because away load has no weekday pattern and throwing weight away from a small pool only adds noise;
   - age factor 0.9 for yesterday, reduced by 0.03 for each earlier day, never below 0.1.
3. **For each future five-minute step**, look at the sample taken a whole number of days earlier at the same time of day. **Skip any sample that is zero or missing**, so gaps in the history do not pull the estimate down.
4. **Away state per sample.** A step is "away" if the away days left exceed the number of whole days between today and the step's day. So the day you travel home, and every day after it, is planned as at home while you are still away. The past sample's away state is the value recorded at the moment it was taken. A sample older than the recorded away history counts as at home, because otherwise the pre-holiday days that away mode exists to discount would get full weight.
5. **Match.** Average only the past samples whose away state equals the step's away state, using the weights in step 2 (age only between two away days). That weighted average is the step's estimate.
6. **Fallback when nothing matches** (the first day of a holiday, or a return after a holiday longer than the window): take the weighted average of all days and **multiply it by the assumed away fraction while away, or divide it by the fraction when home and the whole window was away**. Away mode therefore acts at once, without waiting a day for away history.
7. **Output** is energy per step, accumulated from midnight, covering the planning horizon.
8. **Low-day filter** (the docs): when more than one day is in the list, the lowest-consumption day is dropped before averaging, on by default, to ignore a single unusually quiet day. Expert option.
9. **After a long trip**, the docs suggest keeping away mode on for about seven further days after returning if the trip was longer than the history window.

#### Failure behaviour
No load history, or less than a day: no forecast. No recorded away history: every sample counts as at home.

#### Quirks
Away days are matched per sample, not per whole day, so switching away mode on or off part-way through a day is handled. The window includes one extra day of away history so the oldest day stays readable for every time of day.

#### Test vectors
Reference model written from the text above, not a run of Predbat. Today is a Wednesday. Weights for the past eight days, `weekday x age = weight`: Tue 0.7x0.90=0.630; Mon 0.7x0.87=0.609; Sun 0.5x0.84=0.420; Sat 0.5x0.81=0.405; Fri 0.7x0.78=0.546; Thu 0.7x0.75=0.525; last Wed 1.0x0.72=0.720; Tue 0.7x0.69=0.483.
For one step with samples of 0.05, 0.06, 0.04, 0.05 and 0.30 kWh from days 1 to 5 (the last a Friday that was unusually busy), the weighted average is **0.103 kWh**. If every sample is away-state mismatched and the assumed fraction is 0.5: away fallback **0.0515**, return-home fallback **0.206**.

#### Questions for our code
How does our learned profile weight past days (same weekday, newer days heavier)? Does it skip zero samples? Does a week away lower our profile for days after the return (it should be asked, not assumed)? We have no away state at all.


---

