"""The live ranking: what is shown of a search result, and the attributes of the sensor."""

from __future__ import annotations

from custom_components.givenergy_inverter_manager.core.shadow_ranking import (
    LISTED,
    attributes,
    summarise,
)
from custom_components.givenergy_inverter_manager.lib.tariffranking import (
    Unit,
    Usage,
    Window,
    search,
)
from tests.core.shadow_helpers import THROUGH, _candidate, _usage


def _result(rates: dict[str, float]):  # type: ignore[no-untyped-def]
    usage: Usage = _usage(Window(Unit.WEEKS, 4), THROUGH)
    others = [_candidate(name, base_rate=rate) for name, rate in rates.items()]
    return search(usage, _candidate("current"), others)


def test_the_cheapest_few_and_your_plan_are_listed_wherever_it_stands() -> None:
    rates = {f"p{i}": 0.01 * i for i in range(1, 9)} | {"dear": 2.0}
    ranking = summarise(_result(rates), left_out=2, assumed_export=1)
    assert ranking.compared == 10
    assert [p.rank for p in ranking.plans][:LISTED] == list(range(1, LISTED + 1))
    assert sum(p.yours for p in ranking.plans) == 1
    yours = next(p for p in ranking.plans if p.yours)
    assert yours.name == "Your plan" and yours.rank == ranking.current_rank
    assert ranking.cheapest == "P1"
    assert ranking.saving > 0
    assert ranking.left_out == 2 and ranking.assumed_export == 1
    assert "The last bill would have been cheapest on P1," in ranking.sentence
    assert f"{ranking.saving:.2f} less." in ranking.sentence


def test_when_yours_is_the_cheapest_there_is_no_saving() -> None:
    ranking = summarise(_result({"dear": 2.0}), 0, 0)
    assert ranking.current_rank == 1
    assert ranking.cheapest == ""
    assert ranking.saving == 0
    assert "cheapest on" not in ranking.sentence
    assert ranking.sentence.startswith("Your plan is the cheapest")
    assert attributes(ranking)["cheapest_plan"] is None


def test_the_attributes_say_what_was_priced() -> None:
    ranking = summarise(_result({"dear": 2.0, "cheap": 0.001}), 0, 0)
    attrs = attributes(ranking)
    assert attrs["plans_compared"] == 3
    assert attrs["in_top"] is True
    assert attrs["window_end"] == ranking.last_day.isoformat()
    assert attrs["ranking"][0] == {
        "rank": 1, "name": "Cheap", "bill": attrs["ranking"][0]["bill"], "yours": False,
    }
