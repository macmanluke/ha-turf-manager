"""Shared fixtures for Turf Manager tests."""

from __future__ import annotations

from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock: Any, enable_custom_integrations: Any) -> None:
    """Allow loading custom_components/turf_manager.

    Turf Manager depends on the recorder, which must start before the test
    Home Assistant instance, so recorder_mock comes first.
    """
    return
