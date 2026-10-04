"""Reports one clear skip when the end-to-end plugin is not installed."""

import pytest


def test_plugin_is_installed():
    pytest.importorskip(
        "pytest_homeassistant_custom_component",
        reason=(
            "pytest-homeassistant-custom-component is not installed. "
            "Install requirements-test-e2e.txt in a separate virtualenv (see docs/testing.md)."
        ),
    )
