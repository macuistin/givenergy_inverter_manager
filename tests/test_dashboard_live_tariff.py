"""The Tariff section reads the Tariff in use sensor, so a stored copy follows a tariff change."""

from __future__ import annotations

from tests.dashboard_support import (
    FULL_CONFIG,
    FakeRegistry,
    dashboard_dict,
    devices_of,
)

REPORT = "sensor.givenergy_inverter_manager_tariff_in_use"


def _tariff(registry: FakeRegistry | None = None, *, is_admin: bool = True) -> list[dict]:
    """The cards of the Tariff section of the Bill & tariff view."""
    dashboard = dashboard_dict(FULL_CONFIG, registry, is_admin=is_admin)
    view = next(v for v in dashboard["views"] if v["path"] == "bill")
    return next(s for s in view["sections"] if s["cards"][0]["heading"] == "Tariff")["cards"]


def test_the_section_shows_the_report_sensors_html():
    cards = _tariff()

    assert [c["type"] for c in cards] == ["heading", "history-graph", "markdown"]
    assert cards[2]["content"] == f"{{{{ state_attr('{REPORT}', 'html') }}}}"


def test_without_the_sensor_the_section_builds_its_own_tables():
    registry = FakeRegistry(
        enable_all=True, devices=devices_of(FULL_CONFIG, "myenergi"), absent={"tariff_in_use"}
    )

    markdown = [c for c in _tariff(registry) if c["type"] == "markdown"]

    assert "| Period | Window | Rate per kWh | Billed per kWh |" in markdown[0]["content"]
    assert "state_attr" not in markdown[0]["content"]


def test_the_card_holds_no_rate_so_a_change_cannot_leave_it_stale():
    content = _tariff()[2]["content"]

    assert not any(ch.isdigit() for ch in content.replace(REPORT, ""))


def _navigation_paths(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        path = node.get("navigation_path")
        if isinstance(path, str):
            found.add(path)
        for value in node.values():
            found |= _navigation_paths(value)
    elif isinstance(node, list):
        for item in node:
            found |= _navigation_paths(item)
    return found


def test_no_link_in_the_dashboard_points_at_a_view_that_is_not_there():
    """A copy pasted by an administrator keeps Settings, and one for anyone else drops its button."""
    for is_admin in (True, False):
        dashboard = dashboard_dict(FULL_CONFIG, is_admin=is_admin)
        views = {v["path"] for v in dashboard["views"]}
        targets = {p.lstrip("/").split("/")[-1] for p in _navigation_paths(dashboard)}

        assert targets <= views, (is_admin, targets - views)


def test_settings_is_in_an_administrators_dashboard_with_its_button_and_not_otherwise():
    admin = dashboard_dict(FULL_CONFIG, is_admin=True)
    other = dashboard_dict(FULL_CONFIG, is_admin=False)

    assert "settings" in {v["path"] for v in admin["views"]}
    assert "settings" in _navigation_paths(admin)
    assert "settings" not in {v["path"] for v in other["views"]}
    assert "settings" not in _navigation_paths(other)
