"""
Only administrators see the Settings view and the button that opens it.

Home Assistant has no admin flag for a dashboard. The generator is given the administrators'
user IDs and writes them into the view's `visible` list and the user condition of the button
and of the Settings shortcut.
These tests pin that, and that the rest of the dashboard only shows state.
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.givenergy_inverter_manager.dashboard.registry import async_admin_user_ids
from tests.dashboard_support import (
    ADMIN_ID,
    MINIMAL_CONFIG,
    dashboard_dict,
    default_entity_ids,
    view_cards,
)

OTHER_ADMIN_ID = "b1c2d3e4f5061728394a5b6c7d8e9f0a"
CONTROL_DOMAINS = {"switch", "number", "button"}
CONTROL_FEATURES = {"toggle", "numeric-input"}
INSTALLS = {
    "full": {},
    "minimal": {"config": MINIMAL_CONFIG, "ev_brand": None},
    "no_admin": {"admin_ids": ()},
}


def _view(dashboard: dict, path: str) -> dict | None:
    return next((v for v in dashboard["views"] if v["path"] == path), None)


def _shown_to_everyone(view: dict) -> bool:
    return view.get("visible", True) is True


def _everyones_views(dashboard: dict) -> list[dict]:
    return [v for v in dashboard["views"] if _shown_to_everyone(v)]


def _button_badges(dashboard: dict) -> list[dict]:
    return [
        badge
        for view in dashboard["views"]
        for card in view_cards(view)
        for badge in card.get("badges", [])
        if badge["type"] == "button"
    ]


def _settings_buttons(dashboard: dict) -> list[dict]:
    return [b for b in _button_badges(dashboard) if b["tap_action"]["navigation_path"] == "settings"]


def _settings_shortcuts(dashboard: dict) -> list[dict]:
    return [
        card
        for view in dashboard["views"]
        for card in view_cards(view)
        if card["type"] == "shortcut" and card["tap_action"]["navigation_path"] == "settings"
    ]


class TestAdminsPresent:
    def test_settings_is_a_sub_view_of_power_flow_visible_to_the_administrators(self):
        dashboard = dashboard_dict(admin_ids=(ADMIN_ID, OTHER_ADMIN_ID))
        settings = _view(dashboard, "settings")
        assert settings["subview"] is True
        assert settings["back_path"] == "power-flow"
        assert settings["visible"] == [{"user": ADMIN_ID}, {"user": OTHER_ADMIN_ID}]

    def test_the_button_is_in_the_power_flow_heading_and_is_for_the_administrators(self):
        dashboard = dashboard_dict(admin_ids=(ADMIN_ID, OTHER_ADMIN_ID))
        [button] = _settings_buttons(dashboard)
        assert button == {
            "type": "button",
            "icon": "mdi:tune",
            "text": "Settings",
            "tap_action": {"action": "navigate", "navigation_path": "settings"},
            "visibility": [{"condition": "user", "users": [ADMIN_ID, OTHER_ADMIN_ID]}],
        }
        (flow,) = [
            c for c in view_cards(_view(dashboard, "power-flow")) if c.get("heading") == "Live power flow"
        ]
        assert button in flow["badges"]

    def test_the_settings_shortcut_under_more_is_for_the_administrators(self):
        dashboard = dashboard_dict(admin_ids=(ADMIN_ID, OTHER_ADMIN_ID))
        [shortcut] = _settings_shortcuts(dashboard)
        assert shortcut["visibility"] == [
            {"condition": "user", "users": [ADMIN_ID, OTHER_ADMIN_ID]}
        ]

    def test_settings_holds_every_switch_and_slider(self):
        ids = default_entity_ids()
        controls = {
            ids[key]
            for key in (
                "charge_target_override",
                "charge_target_override_enabled",
                "skip_charge_override",
                "auto_immersion",
                "immersion_managed",
                "immersion_schedule",
                "immersion_target_temp",
                "immersion_min_temp",
                "immersion_hysteresis",
                "dry_run",
                "verbose_logging",
                "charge_replan",
                "cheap_rate_floor_soc",
                "skip_charge_soc_threshold_pct",
                "forecast_conservatism",
                "surplus_divert_soc_pct",
                "surplus_divert_min_power_w",
            )
        }
        tiles = [c for c in view_cards(_view(dashboard_dict(), "settings")) if c["type"] == "tile"]
        assert {t["entity"] for t in tiles} == controls
        for tile in tiles:
            if tile["entity"].startswith("number."):
                assert tile["features"] == [{"type": "numeric-input", "style": "buttons"}]
            else:
                assert tile["tap_action"] == tile["icon_tap_action"] == {"action": "toggle"}

    def test_the_settings_view_is_not_a_tab(self):
        tabs = [v["path"] for v in dashboard_dict()["views"] if not v.get("subview")]
        assert tabs == ["power-flow"]


class TestAdminsAbsent:
    def test_without_an_administrator_id_the_view_and_the_button_are_left_out(self):
        dashboard = dashboard_dict(admin_ids=())
        assert _view(dashboard, "settings") is None
        assert _settings_buttons(dashboard) == []
        assert _settings_shortcuts(dashboard) == []
        assert "'navigation_path': 'settings'" not in str(dashboard)

    def test_a_viewer_who_is_not_an_administrator_gets_neither_the_view_nor_the_button(self):
        dashboard = dashboard_dict(admin_ids=(ADMIN_ID,), is_admin=False)
        assert _view(dashboard, "settings") is None
        assert _settings_buttons(dashboard) == []
        assert "'navigation_path': 'settings'" not in str(dashboard)

    def test_the_repairs_banner_is_only_in_an_administrators_dashboard(self):
        def headings(dashboard: dict) -> list[str]:
            view = _view(dashboard, "power-flow")
            return [s["cards"][0].get("heading") for s in view["sections"]]

        assert "Needs your attention" in headings(dashboard_dict())
        assert "Needs your attention" not in headings(dashboard_dict(admin_ids=()))
        assert "Needs your attention" not in headings(dashboard_dict(is_admin=False))

    def test_the_administrator_ids_are_not_written_for_a_viewer_who_is_not_one(self):
        assert ADMIN_ID not in str(dashboard_dict(admin_ids=(ADMIN_ID,), is_admin=False))

    def test_a_non_administrator_id_is_never_written_when_it_is_not_passed(self):
        assert "child-user-id" not in str(dashboard_dict(admin_ids=(ADMIN_ID,)))

    def test_the_rest_of_the_dashboard_is_the_same_with_or_without_administrators(self):
        with_admin = dashboard_dict()["views"]
        without = dashboard_dict(admin_ids=())["views"]
        shared = [v for v in with_admin if v["path"] != "settings"]
        assert [v["path"] for v in without] == [v["path"] for v in shared]
        for view, bare in zip(shared, without, strict=True):
            assert _without_settings_button(view) == _without_settings_button(bare)


def _without_settings_button(view: dict) -> dict:
    """A copy of the view without the Settings button, the Settings shortcut and the repairs.

    Only an admin dashboard has them: only an administrator can open Settings or act on a repair.
    """
    stripped = copy.deepcopy(view)
    stripped["sections"] = [
        s for s in stripped["sections"] if s["cards"][0].get("heading") != "Needs your attention"
    ]
    for section in stripped["sections"]:
        section["cards"] = [
            c
            for c in section["cards"]
            if c.get("tap_action") != {"action": "navigate", "navigation_path": "settings"}
        ]
    for card in (c for section in stripped["sections"] for c in section["cards"]):
        if "badges" in card:
            del card["badges"]
    return stripped


class TestOnlyStateIsShownToEveryone:
    @pytest.mark.parametrize("install", INSTALLS)
    def test_no_view_shown_to_everyone_holds_an_editable_control(self, install):
        dashboard = dashboard_dict(**INSTALLS[install])
        for view in _everyones_views(dashboard):
            for card in view_cards(view):
                assert not _editable(card), (view["path"], card)

    @pytest.mark.parametrize("install", INSTALLS)
    def test_the_only_view_hidden_from_anyone_is_settings(self, install):
        dashboard = dashboard_dict(**INSTALLS[install])
        hidden = [v["path"] for v in dashboard["views"] if not _shown_to_everyone(v)]
        assert hidden in ([], ["settings"])

    def test_no_card_but_the_button_and_the_shortcut_opens_settings(self):
        """Both carry the administrators' user condition."""
        dashboard = dashboard_dict()
        for view in _everyones_views(dashboard):
            for card in view_cards(view):
                if card in _settings_shortcuts(dashboard):
                    continue
                for action in (card.get("tap_action"), card.get("icon_tap_action")):
                    assert (action or {}).get("navigation_path") != "settings"
        for opener in [*_settings_buttons(dashboard), *_settings_shortcuts(dashboard)]:
            assert opener["visibility"] == [{"condition": "user", "users": [ADMIN_ID]}]


def _editable(card: dict) -> bool:
    """True for a card that lets a viewer change something."""
    if card["type"] != "tile":
        return card["type"] in {"button", "light", "thermostat"}
    if {f["type"] for f in card.get("features", [])} & CONTROL_FEATURES:
        return True
    if card["entity"].split(".")[0] not in CONTROL_DOMAINS:
        return False
    return not (
        card.get("tap_action") == {"action": "none"}
        and card.get("icon_tap_action") == {"action": "none"}
    )


class TestStateStaysOnTheMainDashboard:
    """What the Settings view changes can still be read by everyone."""

    def _read_only_tiles(self) -> dict[str, dict]:
        tiles = {}
        for view in _everyones_views(dashboard_dict()):
            for card in view_cards(view):
                if card["type"] == "tile":
                    tiles[card["entity"]] = card
        return tiles

    def _figures(self) -> set[str]:
        """The entities shown in a row of figures, which cannot be changed from there."""
        return {
            row["entity"]
            for view in _everyones_views(dashboard_dict())
            for card in view_cards(view)
            if card["type"] == "glance"
            for row in card["entities"]
        }

    @pytest.mark.parametrize(
        "key",
        [
            "charge_target_override",
            "charge_target_override_enabled",
            "skip_charge_override",
            "dry_run_active",
        ],
    )
    def test_the_setting_is_shown_as_a_tile(self, key):
        assert default_entity_ids()[key] in self._read_only_tiles()

    @pytest.mark.parametrize(
        "key",
        ["auto_immersion", "immersion_schedule", "immersion_target_temp", "immersion_min_temp"],
    )
    def test_the_heater_setting_is_shown_as_a_figure(self, key):
        assert default_entity_ids()[key] in self._figures()

    def test_the_charge_settings_are_on_the_battery_tab(self):
        ids = default_entity_ids()
        battery = {c["entity"] for c in view_cards(_view(dashboard_dict(), "plan")) if "entity" in c}
        assert {ids[k] for k in ("charge_target_override", "skip_charge_override")} <= battery

    def test_the_immersion_settings_are_on_the_immersion_sub_view(self):
        ids = default_entity_ids()
        cards = view_cards(_view(dashboard_dict(), "immersion"))
        shown = {r["entity"] for c in cards if c["type"] == "glance" for r in c["entities"]}
        assert {ids[k] for k in ("auto_immersion", "immersion_target_temp")} <= shown

    def test_the_dry_run_banner_is_on_power_flow(self):
        headings = [c.get("heading") for c in view_cards(_view(dashboard_dict(), "power-flow"))]
        assert "Dry run is on" in headings

    def test_the_tariff_is_still_readable_by_everyone(self):
        assert _shown_to_everyone(_view(dashboard_dict(), "plan"))

    def test_tiles_of_a_setting_do_nothing_when_tapped(self):
        ids = default_entity_ids()
        tile = self._read_only_tiles()[ids["charge_target_override_enabled"]]
        assert tile["tap_action"] == tile["icon_tap_action"] == {"action": "none"}
        assert "features" not in tile


class TestAdminUserIds:
    def _ids(self, users):
        hass = SimpleNamespace(auth=SimpleNamespace(async_get_users=AsyncMock(return_value=users)))
        return asyncio.run(async_admin_user_ids(hass))

    @staticmethod
    def _user(user_id, *, admin, system=False):
        return SimpleNamespace(id=user_id, is_admin=admin, system_generated=system)

    def test_an_active_administrator_is_listed(self):
        assert self._ids([self._user("a", admin=True)]) == ("a",)

    def test_a_user_who_is_not_an_administrator_is_left_out(self):
        users = [self._user("a", admin=True), self._user("b", admin=False)]
        assert self._ids(users) == ("a",)

    def test_a_system_user_is_left_out(self):
        assert self._ids([self._user("supervisor", admin=True, system=True)]) == ()

    def test_no_users_gives_no_ids(self):
        assert self._ids([]) == ()
