"""Finding a GivTCP entity again after Home Assistant's id for it changed."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.const import (
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_SOLAR_POWER,
)
from custom_components.givenergy_inverter_manager.core.entity_refs import (
    REFERENCE_KEYS,
    Registry,
    clean_remembered,
    resolve,
)
from custom_components.givenergy_inverter_manager.wizard.wiring import WIRING_KEYS

OLD = "sensor.givtcp_ab1234g567_pv_power"
NEW = "sensor.pv_power_default"
REMEMBERED = {CONF_SOLAR_POWER: {"entity_id": OLD, "platform": "mqtt", "unique_id": "ab_pv"}}


def registry(
    present: set[str], identities: dict[str, tuple[str, str]] | None = None
) -> Registry:
    identities = identities or {}
    by_unique = {v: k for k, v in identities.items()}
    return Registry(
        exists=lambda eid: eid in present,
        identity_of=lambda eid: identities.get(eid),
        entity_id_for=lambda domain, platform, uid: by_unique.get((platform, uid)),
    )


def test_the_reference_keys_are_the_wiring_keys():
    assert set(REFERENCE_KEYS) == set(WIRING_KEYS)


class TestResolve:
    def test_an_id_that_exists_is_used_and_its_unique_id_is_learned(self):
        result = resolve(
            {CONF_SOLAR_POWER: OLD}, {}, registry({OLD}, {OLD: ("mqtt", "ab_pv")})
        )
        assert result.cfg[CONF_SOLAR_POWER] == OLD
        assert result.learned == {
            CONF_SOLAR_POWER: {"entity_id": OLD, "platform": "mqtt", "unique_id": "ab_pv"}
        }
        assert result.missing == [] and result.renamed == {}

    def test_an_id_that_is_already_remembered_is_not_learned_again(self):
        result = resolve({CONF_SOLAR_POWER: OLD}, REMEMBERED, registry({OLD}, {OLD: ("mqtt", "ab_pv")}))
        assert result.learned == {}

    def test_an_entity_with_no_registry_entry_is_used_and_nothing_is_learned(self):
        result = resolve({CONF_SOLAR_POWER: OLD}, {}, registry({OLD}))
        assert result.cfg[CONF_SOLAR_POWER] == OLD
        assert result.learned == {} and result.missing == []

    def test_an_id_that_went_is_found_by_its_unique_id(self):
        result = resolve(
            {CONF_SOLAR_POWER: OLD}, REMEMBERED, registry({NEW}, {NEW: ("mqtt", "ab_pv")})
        )
        assert result.cfg[CONF_SOLAR_POWER] == NEW
        assert result.renamed == {CONF_SOLAR_POWER: (OLD, NEW)}
        assert result.missing == []

    def test_the_config_passed_in_is_not_changed(self):
        cfg = {CONF_SOLAR_POWER: OLD}
        resolve(cfg, REMEMBERED, registry({NEW}, {NEW: ("mqtt", "ab_pv")}))
        assert cfg == {CONF_SOLAR_POWER: OLD}

    def test_an_id_that_went_with_nothing_remembered_is_missing(self):
        result = resolve({CONF_SOLAR_POWER: OLD}, {}, registry(set()))
        assert result.missing == [CONF_SOLAR_POWER]
        assert result.cfg[CONF_SOLAR_POWER] == OLD

    def test_a_remembered_id_the_registry_no_longer_knows_is_missing(self):
        result = resolve({CONF_SOLAR_POWER: OLD}, REMEMBERED, registry(set()))
        assert result.missing == [CONF_SOLAR_POWER]

    def test_a_unique_id_that_points_at_an_id_with_no_state_or_entry_is_missing(self):
        result = resolve(
            {CONF_SOLAR_POWER: OLD}, REMEMBERED, registry(set(), {NEW: ("mqtt", "ab_pv")})
        )
        assert result.missing == [CONF_SOLAR_POWER]

    def test_each_key_is_resolved_on_its_own(self):
        cfg = {CONF_SOLAR_POWER: OLD, CONF_BATTERY_SOC: "sensor.soc", CONF_BATTERY_POWER: "sensor.gone"}
        result = resolve(
            cfg, REMEMBERED, registry({NEW, "sensor.soc"}, {NEW: ("mqtt", "ab_pv")})
        )
        assert result.cfg[CONF_SOLAR_POWER] == NEW
        assert result.cfg[CONF_BATTERY_SOC] == "sensor.soc"
        assert result.missing == [CONF_BATTERY_POWER]

    def test_an_empty_optional_entity_is_not_a_missing_one(self):
        result = resolve({CONF_SOLAR_POWER: ""}, {}, registry(set()))
        assert result.missing == []


class TestCleanRemembered:
    def test_a_good_store_survives(self):
        assert clean_remembered(REMEMBERED) == REMEMBERED

    @pytest.mark.parametrize(
        "bad",
        [None, "x", [], {"k": "v"}, {"k": {"entity_id": "a"}}, {"k": {"entity_id": "", "platform": "m", "unique_id": "u"}}],
    )
    def test_anything_else_is_dropped(self, bad):
        assert clean_remembered(bad) == {}
