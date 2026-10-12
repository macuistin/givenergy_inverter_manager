# SPEC-009: correcting a solar forecast by matching similar past conditions

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


**Source:** Helios Forecast, `analog.py` and its opening documentation, read October 2026 (only the module's documentation and constants, not all of the code). **Feeds:** the forecast accuracy scaling, a possible new roadmap item (N24). **Nothing here is code.**

#### What it does
It refines a physical solar model with the site's own history. For each hour to forecast, it finds past hours with similar conditions and reads what the installation actually produced then, as a ratio to what the physical model said for those same hours.

#### Behaviour
1. **Features and weights in a distance:** cloud cover weighs most (1.0), sun altitude next (0.7), outdoor temperature (0.3, scaled so a gap of about 15 degrees counts as a full unit), and sun azimuth least (0.3).
2. **A missing temperature** on either side adds a fixed small penalty (worth about a 4 degree gap), chosen so one missing reading does not push every candidate beyond the "close" threshold and switch the correction off.
3. **Use ratios, not watts.** An analog is never at exactly today's sun position, so watts would carry a geometry difference. A ratio lets the physical model own the geometry while the analog says only how the site departs from it. Watts are the fallback only when no physical model exists for the history.
4. **Point forecast** is the median ratio of the closest analogs applied to today's physical value.
5. **Uncertainty** comes from the 10th and 90th percentile ratios, so the band is data-driven.
6. **Graceful degradation.** The result is a blend between the physical value and the analog-corrected value, weighted by a confidence that falls as the number of close analogs falls (cold start, unusual weather).
7. Hours judged implausible, and inverter-capped production, are handled by comparing against the capped model.

#### Not read
The count of analogs used, the close threshold, the confidence formula, how history is stored, and the residual module's treatment of implausible hours.

#### Questions for our code
We correct the daily total using a recent forecast-versus-actual ratio. A condition-matched correction would need hourly production history and a weather source, which we do not hold. Is a simpler version possible: match on forecast cloud or forecast total, and correct the ratio by it?


---

