# Reference models

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


These small programs produced the test vectors in this part. They were written from the specification text, not from any other project's source. Put them in `tests/reference/`, outside the package, and use them to generate expected values for tests. They are scaffolding for tests, not production code.

```python
# SPEC-001: overnight charge target reference model
def blend_weights(w):
    w = min(max(w, 10), 90)
    return max(0, 50 - w), (90 - w) if w > 50 else (w - 10), max(0, w - 50)

def target(cap, reserve_pct, hold_until, rate_kw, load, p10, p50, p90, weight, floor, shoulder_floor=None, shoulder=False):
    w10, w50, w90 = blend_weights(weight); tot = w10 + w50 + w90
    reserve_e = cap * reserve_pct / 100; cap_slot = rate_kw * 0.5
    raw, mx, mn = [[], []], [0, 0], [0, 0]
    for d in range(2):
        c = peak = low = prev = reserve_e
        for i in range(48):
            if i <= hold_until:
                c = reserve_e
            else:
                gen = (p10[d*48+i]*w10 + p50[d*48+i]*w50 + p90[d*48+i]*w90) / tot
                c = prev + max(-cap_slot, min(cap_slot, gen - load[i]))
                if c < prev and peak <= reserve_e: low = min(low, c)
                else: peak = max(peak, c)
            raw[d].append(int(100*c/cap)); prev = c
        mx[d] = int(100*peak/cap); mn[d] = int(100*low/cap)
        last = max((i for i, v in enumerate(raw[d]) if v == mx[d]), default=47)
        mn[d] = min(mn[d], min(raw[d][:last+1]))
    top = mx[0] + (int((mx[1]-100)/2) if mx[1] > 100 and mx[0] < 100 else 0)
    f = shoulder_floor if shoulder else floor
    return min(int(max(100 - top, f - mn[0], f)), 100)
```

```python
# SPEC-003: weight of one past day, and SPEC-006: cheapest-slot selection (reference models)
import math
def day_weight(hist_dow, today_dow, days_ago):
    wk = 1.0 if hist_dow == today_dow else (0.7 if (hist_dow >= 5) == (today_dow >= 5) else 0.5)
    return wk * max(0.1, 0.9 - (days_ago - 1) * 0.03)

def select_continuous(values, hours, lo=None, hi=None, latest=False, highest=False):
    n = math.ceil(hours * 2); best = None
    for i in range(len(values) - n + 1):
        blk = values[i:i+n]
        if any((lo is not None and v < lo) or (hi is not None and v > hi) for v in blk): continue
        t = sum(blk)
        better = best is None or ((t >= best[1] if latest else t > best[1]) if highest else (t <= best[1] if latest else t < best[1]))
        if better: best = ((i, i+n), t)
    return best

def select_separate(values, hours, hi=None, latest=False):
    n = math.ceil(hours * 2)
    order = sorted((i for i in range(len(values)) if hi is None or values[i] <= hi), key=lambda i: (values[i], -i if latest else i))
    return sorted(order[:n]) if len(order) >= n else []
```

Check values: with the SPEC-001 setup the reference model returns the table in section 2.9; `select_continuous` on the SPEC-006 values returns slots 3 to 6 with total 39; `day_weight` for a Tuesday against a Wednesday, one day ago, returns 0.63.

---
