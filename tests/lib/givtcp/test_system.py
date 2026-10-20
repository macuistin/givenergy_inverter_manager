"""Kinds, controller selection and system identity, from plain facts."""

from __future__ import annotations

import pytest

from custom_components.givenergy_inverter_manager.lib.givtcp.system import (
    InverterFacts,
    SystemIdentity,
    SystemKind,
    classify,
    entities_changed,
    identity_of,
    select_controller,
    what_changed,
)

POWER = {"_pv_power", "_soc", "_battery_power", "_grid_power", "_load_power"}


def facts(serial="AA1111A111", kind=SystemKind.HYBRID, *, complete=True, **extra) -> InverterFacts:
    return InverterFacts(
        serial=serial,
        prefix=f"givtcp_{serial.lower()}",
        kind=kind,
        complete=complete,
        can_schedule=complete,
        **extra,
    )


class TestClassify:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Hybrid_gen3", SystemKind.HYBRID),
            ("Hybrid", SystemKind.HYBRID),
            ("AC", SystemKind.AC_COUPLED),
            ("AC_coupled", SystemKind.AC_COUPLED),
            ("All_in_one", SystemKind.ALL_IN_ONE),
            ("AIO", SystemKind.ALL_IN_ONE),
            ("Three_phase", SystemKind.THREE_PHASE),
            ("3ph", SystemKind.THREE_PHASE),
            ("Gateway", SystemKind.GATEWAY),
            ("EMS", SystemKind.EMS),
        ],
    )
    def test_the_type_text_names_the_kind(self, text, kind):
        assert classify(POWER, text).kind is kind

    def test_a_datapoint_only_one_kind_has_decides_over_the_text(self):
        verdict = classify({*POWER, "_gateway_state"}, "Hybrid_gen3")
        assert verdict.kind is SystemKind.GATEWAY
        assert verdict.confidence == "medium"  # the two signals disagree

    def test_a_fingerprint_and_a_text_that_agree_are_high_confidence(self):
        assert classify({*POWER, "_plant_status"}, "EMS").confidence == "high"

    def test_with_no_text_the_usual_entities_make_a_hybrid_with_low_confidence(self):
        verdict = classify(POWER, None)
        assert (verdict.kind, verdict.confidence) == (SystemKind.HYBRID, "low")

    def test_a_text_that_is_not_recognised_falls_back_to_the_entities(self):
        assert classify(POWER, "Something_new").kind is SystemKind.HYBRID

    def test_nothing_to_go_on_is_unknown(self):
        assert classify({"_status"}, None).kind is SystemKind.UNKNOWN

    def test_a_serial_prefix_is_never_used(self):
        # classify takes no serial, so a prefix like "ED" or "SA" cannot decide a kind.
        assert classify(POWER, None).kind is SystemKind.HYBRID


class TestSelectController:
    def test_nothing_found_gives_nothing(self):
        assert select_controller([]).controller is None

    def test_one_device_is_used(self):
        selection = select_controller([facts()])
        assert selection.controller.serial == "AA1111A111"
        assert not selection.ask

    def test_a_gateway_over_parallel_units_is_the_controller_and_they_are_read_only(self):
        gateway = facts("GW0000G000", SystemKind.GATEWAY, parallel_units=2)
        units = [facts("AA1111A111", SystemKind.ALL_IN_ONE), facts("BB2222B222", SystemKind.ALL_IN_ONE)]
        selection = select_controller([*units, gateway])
        assert selection.controller is gateway
        assert set(selection.units) == set(units)
        assert not selection.ask

    def test_a_gateway_with_two_all_in_ones_is_parallel_even_when_it_does_not_say(self):
        gateway = facts("GW0000G000", SystemKind.GATEWAY)
        units = [facts("AA1111A111", SystemKind.ALL_IN_ONE), facts("BB2222B222", SystemKind.ALL_IN_ONE)]
        assert select_controller([gateway, *units]).controller is gateway

    def test_a_gateway_with_one_all_in_one_gives_way_to_it(self):
        gateway = facts("GW0000G000", SystemKind.GATEWAY, parallel_units=1)
        unit = facts("AA1111A111", SystemKind.ALL_IN_ONE)
        selection = select_controller([gateway, unit])
        assert selection.controller is unit
        assert selection.others == (gateway,)

    def test_a_lone_gateway_is_used(self):
        gateway = facts("GW0000G000", SystemKind.GATEWAY)
        assert select_controller([gateway]).controller is gateway

    def test_several_other_devices_ask_and_offer_the_complete_one_first(self):
        incomplete = facts("AA1111A111", complete=False)
        complete = facts("BB2222B222")
        selection = select_controller([incomplete, complete])
        assert selection.ask
        assert selection.controller is complete
        assert selection.others == (incomplete,)

    def test_two_gateways_ask(self):
        selection = select_controller(
            [facts("GW0000G000", SystemKind.GATEWAY), facts("GX0000G000", SystemKind.GATEWAY)]
        )
        assert selection.ask


class TestIdentity:
    OLD = identity_of(facts(version="3.5.68", modules=2, roles=("a", "b")))

    def test_the_same_system_has_the_same_hash_and_no_changes(self):
        same = identity_of(facts(version="3.5.68", modules=2, roles=("b", "a")))
        assert same.hash == self.OLD.hash
        assert what_changed(self.OLD, same) == []

    def test_a_new_version_alone_is_not_a_different_system(self):
        newer = identity_of(facts(version="3.6.3", modules=2, roles=("a", "b")))
        assert what_changed(self.OLD, newer) == []
        assert newer.hash == self.OLD.hash

    def test_a_different_kind_is_named_in_plain_words(self):
        new = identity_of(facts(kind=SystemKind.THREE_PHASE, modules=2, roles=("a", "b")))
        assert what_changed(self.OLD, new) == ["type hybrid inverter to three-phase inverter"]

    def test_a_different_module_count_is_named(self):
        new = identity_of(facts(modules=3, roles=("a", "b")))
        assert what_changed(self.OLD, new) == ["battery modules 2 to 3"]

    def test_a_different_managed_inverter_is_named(self):
        new = identity_of(facts("BB2222B222", modules=2, roles=("a", "b")))
        assert "managed inverter AA1111A111 to BB2222B222" in what_changed(self.OLD, new)

    def test_a_different_set_of_entities_is_seen_but_is_not_a_change_to_confirm(self):
        new = identity_of(facts(version="3.5.68", modules=2, roles=("a", "c")))
        assert entities_changed(self.OLD, new)
        assert what_changed(self.OLD, new) == []

    def test_it_survives_storage(self):
        assert SystemIdentity.from_dict(self.OLD.as_dict()) == self.OLD

    @pytest.mark.parametrize("bad", [None, "x", {}, {"kind": "hybrid"}, {"controller": "A"}])
    def test_damaged_storage_is_no_identity(self, bad):
        assert SystemIdentity.from_dict(bad) is None
