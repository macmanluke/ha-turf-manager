"""End-to-end tests for Turf Manager inside a test Home Assistant instance."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.turf_manager.const import (
    CONF_ADD_PGR_PRESET,
    CONF_BASE_TEMP,
    CONF_GDD_TARGET,
    CONF_GRASS_TYPE,
    CONF_HEIGHT_UNIT,
    CONF_METHOD,
    CONF_SEASON_START_MONTH,
    CONF_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)

TEMP_SENSOR = "sensor.outdoor_temperature"
LAWN = "front_lawn"


def _set_sensor(hass: HomeAssistant, value: str = "21.5") -> None:
    hass.states.async_set(
        TEMP_SENSOR,
        value,
        {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"},
    )


async def _setup(hass: HomeAssistant, site: dict[str, Any] | None = None) -> MockConfigEntry:
    _set_sensor(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        data={
            CONF_TEMP_SENSOR: TEMP_SENSOR,
            CONF_METHOD: "mean",
            CONF_SEASON_START_MONTH: "7",
            CONF_HEIGHT_UNIT: "auto",
            **(site or {}),
        },
        subentries_data=[
            ConfigSubentryData(
                subentry_type="lawn",
                title="Front lawn",
                data={CONF_GRASS_TYPE: "warm", CONF_BASE_TEMP: 10.0, CONF_GDD_TARGET: 200.0},
                unique_id=None,
            ),
            ConfigSubentryData(
                subentry_type="product",
                title="Primo Maxx",
                data={
                    "product_type": "pgr",
                    "gdd_interval": 200.0,
                    "pgr_model": "trinexapac",
                    "rate_unit": "mL/100m²",
                },
                unique_id=None,
            ),
            ConfigSubentryData(
                subentry_type="product",
                title="Lawn food",
                data={"product_type": "fertiliser", "rate": 2.5, "rate_unit": "kg/100m²", "n_percent": 20},
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _lawn_device_id(hass: HomeAssistant) -> str:
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get(f"sensor.{LAWN}_gdd_since_pgr").device_id


async def test_config_flow_creates_site_lawn_and_preset(recorder_mock: Any, hass: HomeAssistant) -> None:
    _set_sensor(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Home",
            CONF_TEMP_SENSOR: TEMP_SENSOR,
            CONF_METHOD: "mean",
            CONF_SEASON_START_MONTH: "7",
            CONF_HEIGHT_UNIT: "auto",
        },
    )
    assert result["step_id"] == "lawn"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Front lawn", CONF_GRASS_TYPE: "warm", CONF_GDD_TARGET: 200, CONF_ADD_PGR_PRESET: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    types = sorted(sub.subentry_type for sub in entry.subentries.values())
    assert types == ["lawn", "product"]
    lawn = next(s for s in entry.subentries.values() if s.subentry_type == "lawn")
    assert lawn.data[CONF_BASE_TEMP] == 10.0
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{LAWN}_gdd_since_pgr") is not None


async def test_backdated_pgr_uses_manual_temperatures(recorder_mock: Any, hass: HomeAssistant) -> None:
    await _setup(hass)
    today = dt_util.now().date()
    # Warm season, base 10: means of 30, 32 and 34 give 20 + 22 + 24 = 66 GDD.
    for offset, mean in ((3, 30.0), (2, 32.0), (1, 34.0)):
        await hass.services.async_call(
            DOMAIN,
            "set_daily_temperature",
            {"date": (today - timedelta(days=offset)).isoformat(), "mean": mean},
            blocking=True,
        )
    # A cold day is 0, not negative.
    await hass.services.async_call(
        DOMAIN,
        "set_daily_temperature",
        {"date": (today - timedelta(days=4)).isoformat(), "min": 2.0, "max": 12.0},
        blocking=True,
    )
    await hass.services.async_call(
        "date",
        "set_value",
        {"entity_id": f"date.{LAWN}_last_pgr_application", "date": (today - timedelta(days=4)).isoformat()},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get(f"sensor.{LAWN}_gdd_since_pgr")
    assert float(state.state) == pytest.approx(66.0)
    assert state.attributes["days_since_application"] == 4
    assert hass.states.get(f"binary_sensor.{LAWN}_pgr_due").state == "off"

    # Lowering the target below the total makes it due and fires the event.
    due_events = async_capture_events(hass, "turf_manager_pgr_due")
    await hass.services.async_call(
        "number", "set_value", {"entity_id": f"number.{LAWN}_pgr_gdd_target", "value": 60}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(f"binary_sensor.{LAWN}_pgr_due").state == "on"
    assert hass.states.get(f"binary_sensor.{LAWN}_pgr_due").attributes["overdue_gdd"] == 6.0
    assert len(due_events) == 1


async def test_button_resets_count_and_blocks_duplicates(recorder_mock: Any, hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_log_pgr_applied_today"}, blocking=True
    )
    await hass.async_block_till_done()
    state = hass.states.get(f"sensor.{LAWN}_gdd_since_pgr")
    assert state.attributes["days_since_application"] == 0
    assert state.attributes["product"] == "Primo Maxx"
    assert hass.states.get(f"date.{LAWN}_last_pgr_application").state == dt_util.now().date().isoformat()

    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": f"button.{LAWN}_log_pgr_applied_today"}, blocking=True
        )


async def test_projection_from_forecast(recorder_mock: Any, hass: HomeAssistant) -> None:
    hass.states.async_set("weather.home", "sunny", {"temperature_unit": "°C"})
    today = dt_util.now().date()

    async def get_forecasts(call: ServiceCall) -> dict[str, Any]:
        forecast = [
            {
                "datetime": dt_util.start_of_local_day(today + timedelta(days=i)).isoformat(),
                "temperature": 25.0,
                "templow": 15.0,
            }
            for i in range(30)
        ]
        return {"weather.home": {"forecast": forecast}}

    hass.services.async_register(
        "weather", "get_forecasts", get_forecasts, supports_response=SupportsResponse.ONLY
    )
    await _setup(hass, {CONF_WEATHER_ENTITY: "weather.home"})
    await hass.services.async_call(
        DOMAIN,
        "set_daily_temperature",
        {"date": (today - timedelta(days=1)).isoformat(), "mean": 20.0},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "log_pgr_application",
        {"device_id": _lawn_device_id(hass), "date": (today - timedelta(days=1)).isoformat()},
        blocking=True,
    )
    await hass.async_block_till_done()
    # 10 GDD yesterday, then (25 + 15) / 2 - 10 = 10 GDD a day: 200 reached on day 18 from today.
    due = hass.states.get(f"sensor.{LAWN}_pgr_next_due")
    assert due.state == (today + timedelta(days=18)).isoformat()
    assert due.attributes["projection_method"] == "forecast"


async def test_mow_application_activity_calendar_and_history(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    await _setup(hass)
    device_id = _lawn_device_id(hass)

    await hass.services.async_call(
        DOMAIN,
        "log_mow",
        {"device_id": device_id, "mower_type": "cylinder", "height": 1, "height_unit": "in", "clippings": 12},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "log_application",
        {"device_id": device_id, "product": "lawn food", "area": 100},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "log_activity", {"device_id": device_id, "activity": "top_dress", "details": "5 mm sand"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert float(hass.states.get(f"sensor.{LAWN}_last_cut_height").state) == pytest.approx(25.4)
    assert hass.states.get(f"sensor.{LAWN}_last_mowed").attributes["mower_type"] == "cylinder"
    # 2.5 kg/100m² of a 20% N product = 5 g N/m².
    assert float(hass.states.get(f"sensor.{LAWN}_nitrogen_this_season").state) == pytest.approx(5.0)
    assert hass.states.get(f"sensor.{LAWN}_last_top_dressed").state not in ("unknown", "unavailable")

    now = dt_util.now()
    events = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": f"calendar.{LAWN}",
            "start_date_time": (now - timedelta(days=1)).isoformat(),
            "end_date_time": (now + timedelta(days=1)).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    summaries = [e["summary"] for e in events[f"calendar.{LAWN}"]["events"]]
    assert "Mow 25.4 mm (cylinder)" in summaries
    assert "Lawn food 2.5 kg/100m²" in summaries
    assert "Top dress: 5 mm sand" in summaries

    history = await hass.services.async_call(
        DOMAIN, "get_history", {"kind": ["mow"]}, blocking=True, return_response=True
    )
    assert len(history["entries"]) == 1
    mow_id = history["entries"][0]["id"]

    log_sensor = f"sensor.{LAWN}_log_entries"
    assert hass.states.get(log_sensor).state == "3"
    before = hass.states.get(log_sensor).attributes["last_modified"]

    await hass.services.async_call(DOMAIN, "delete_entry", {"entry_id": mow_id}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.{LAWN}_last_mowed").state == "unknown"
    # The history card reloads when this sensor changes.
    assert hass.states.get(log_sensor).state == "2"
    assert hass.states.get(log_sensor).attributes["last_modified"] != before


async def test_lawn_added_from_integration_page_has_all_controls(
    recorder_mock: Any, hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: in HA 2026.11 the staged controls failed to be created for a new lawn."""
    entry = await _setup(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "lawn"), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Back lawn", CONF_GRASS_TYPE: "cool", CONF_GDD_TARGET: 200},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    for entity_id in (
        "select.back_lawn_mower_type",
        "number.back_lawn_cut_height",
        "select.back_lawn_product",
        "number.back_lawn_application_rate",
        "select.back_lawn_activity",
        "date.back_lawn_last_pgr_application",
        "calendar.back_lawn",
    ):
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert state.state != "unavailable", entity_id

    assert hass.states.get("select.back_lawn_mower_type").attributes["options"] == [
        "rotary", "cylinder", "robotic", "other"
    ]
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.back_lawn_mower_type", "option": "cylinder"}, blocking=True,
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.back_lawn_cut_height", "value": 12.5}, blocking=True
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.back_lawn_log_mow"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("sensor.back_lawn_last_mowed").attributes["mower_type"] == "cylinder"
    assert float(hass.states.get("sensor.back_lawn_last_cut_height").state) == pytest.approx(12.5)

    # Deprecated device registry use is a warning in 2026.10 and an error in 2026.11+.
    assert "deprecated" not in caplog.text


async def test_rate_step_follows_product_unit(recorder_mock: Any, hass: HomeAssistant) -> None:
    """mL/100m² rates step by 1; kg/100m² by 0.1. Typed decimals are still accepted."""
    await _setup(hass)
    rate = f"number.{LAWN}_application_rate"

    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{LAWN}_product", "option": "Primo Maxx"},
        blocking=True,
    )
    state = hass.states.get(rate)
    assert state.attributes["unit_of_measurement"] == "mL/100m²"
    assert state.attributes["step"] == 1
    assert state.attributes["mode"] == "box"

    await hass.services.async_call("number", "set_value", {"entity_id": rate, "value": 4.5}, blocking=True)
    assert float(hass.states.get(rate).state) == 4.5

    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{LAWN}_product", "option": "Lawn food"},
        blocking=True,
    )
    state = hass.states.get(rate)
    assert state.attributes["unit_of_measurement"] == "kg/100m²"
    assert state.attributes["step"] == 0.1
    assert float(state.state) == 2.5  # the product's default rate


def _render(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize a flow form exactly as Home Assistant does for the browser."""
    import probatio
    from homeassistant.helpers import config_validation as cv

    assert result["type"] is FlowResultType.FORM, result
    return probatio.to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)


async def test_every_form_renders_and_products_can_be_added_and_edited(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    """Regression: the product form failed to render ("Unknown error occurred")."""
    _set_sensor(hass)
    flows = hass.config_entries.flow
    result = await flows.async_init(DOMAIN, context={"source": "user"})
    _render(result)
    result = await flows.async_configure(
        result["flow_id"],
        {CONF_NAME: "Home", CONF_TEMP_SENSOR: TEMP_SENSOR, CONF_METHOD: "mean",
         CONF_SEASON_START_MONTH: "7", CONF_HEIGHT_UNIT: "auto"},
    )
    _render(result)  # first lawn
    result = await flows.async_configure(
        result["flow_id"],
        {CONF_NAME: "Front lawn", CONF_GRASS_TYPE: "custom", CONF_GDD_TARGET: 200, CONF_ADD_PGR_PRESET: False},
    )
    _render(result)  # custom base temperature
    result = await flows.async_configure(result["flow_id"], {CONF_BASE_TEMP: 8.0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()

    _render(await hass.config_entries.options.async_init(entry.entry_id))

    subflows = hass.config_entries.subentries
    _render(await subflows.async_init((entry.entry_id, "lawn"), context={"source": "user"}))

    # Every product preset's form renders.
    from custom_components.turf_manager.const import PRODUCT_PRESETS

    for preset in PRODUCT_PRESETS:
        result = await subflows.async_init((entry.entry_id, "product"), context={"source": "user"})
        _render(result)
        result = await subflows.async_configure(result["flow_id"], {"preset": preset})
        fields = [field["name"] for field in _render(result)]
        assert "rate" in fields and "rate_unit" in fields, preset

    # Add a product.
    result = await subflows.async_init((entry.entry_id, "product"), context={"source": "user"})
    result = await subflows.async_configure(result["flow_id"], {"preset": "granular_fertiliser"})
    details = {
        CONF_NAME: "Lawn food", "product_type": "fertiliser", "rate": 2.5,
        "rate_unit": "kg/100m²", "n_percent": 20, "pgr_model": "none",
    }
    result = await subflows.async_configure(result["flow_id"], dict(details))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    product = next(s for s in entry.subentries.values() if s.title == "Lawn food")
    assert dict(product.data) == {
        "product_type": "fertiliser", "rate": 2.5, "rate_unit": "kg/100m²", "n_percent": 20,
    }

    # The same name again is refused, and the form still renders with the error.
    result = await subflows.async_init((entry.entry_id, "product"), context={"source": "user"})
    result = await subflows.async_configure(result["flow_id"], {"preset": "custom"})
    result = await subflows.async_configure(result["flow_id"], {**details, CONF_NAME: "lawn FOOD"})
    assert result["errors"] == {CONF_NAME: "name_exists"}
    _render(result)

    # Edit it.
    result = await subflows.async_init(
        (entry.entry_id, "product"), context={"source": "reconfigure", "subentry_id": product.subentry_id}
    )
    _render(result)
    result = await subflows.async_configure(result["flow_id"], {**details, "rate": 3.0})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[product.subentry_id].data["rate"] == 3.0

    # Lawn edit form renders too (it lists PGR products).
    lawn = next(s for s in entry.subentries.values() if s.subentry_type == "lawn")
    _render(
        await subflows.async_init(
            (entry.entry_id, "lawn"), context={"source": "reconfigure", "subentry_id": lawn.subentry_id}
        )
    )


async def test_projection_beyond_short_forecast_without_history(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    """A new install has no recent days; the forecast average carries the projection."""
    hass.states.async_set("weather.home", "sunny", {"temperature_unit": "°C"})
    today = dt_util.now().date()

    async def get_forecasts(call: ServiceCall) -> dict[str, Any]:
        days = [
            {
                "datetime": dt_util.start_of_local_day(today + timedelta(days=i)).isoformat(),
                "temperature": 28.0,
                "templow": 16.0,
            }
            for i in range(5)
        ]
        return {"weather.home": {"forecast": days}}

    hass.services.async_register(
        "weather", "get_forecasts", get_forecasts, supports_response=SupportsResponse.ONLY
    )
    await _setup(hass, {CONF_WEATHER_ENTITY: "weather.home"})
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_log_pgr_applied_today"}, blocking=True
    )
    await hass.async_block_till_done()
    # (28 + 16) / 2 - 10 = 12 GDD a day, from today: 200 is reached on day 17 (index 16).
    due = hass.states.get(f"sensor.{LAWN}_pgr_next_due")
    assert due.state == (today + timedelta(days=16)).isoformat()
    assert due.attributes["projection_method"] == "estimated"


async def test_every_device_belongs_to_a_lawn_and_old_site_device_is_removed(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    """Nothing should appear under "Devices that don't belong to a sub-entry"."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entry = await _setup(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    # Early versions had a site device with the temperature sensors on it.
    legacy = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)}, name="Home"
    )
    entities.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_mean_temperature_today",
        config_entry=entry, device_id=legacy.id,
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert devices.async_get(legacy.id) is None
    assert entities.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_mean_temperature_today") is None
    ours = dr.async_entries_for_config_entry(devices, entry.entry_id)
    assert ours
    assert all(device.config_subentry_id is not None for device in ours)

    # The temperatures are on the lawn now.
    state = hass.states.get(f"sensor.{LAWN}_mean_temperature_today")
    assert state is not None
    assert state.attributes["temperature_sensor"] == TEMP_SENSOR


async def test_log_a_mix_with_the_action(recorder_mock: Any, hass: HomeAssistant) -> None:
    """A PGR + fertiliser tank mix is one application: PGR count restarts, N is counted."""
    await _setup(hass)
    result = await hass.services.async_call(
        DOMAIN,
        "log_application",
        {
            "device_id": _lawn_device_id(hass),
            "products": [
                {"product": "Primo Maxx", "rate": 4},
                {"product": "Lawn food"},  # default rate 2.5 kg/100m²
            ],
            "area": 100,
        },
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    assert len(result["entries"]) == 1

    history = await hass.services.async_call(
        DOMAIN, "get_history", {"kind": ["application"]}, blocking=True, return_response=True
    )
    (entry,) = history["entries"]
    assert entry["summary"] == "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²"
    assert entry["is_pgr"] is True
    assert entry["product_type"] == "mix"
    assert [p["product_name"] for p in entry["products"]] == ["Primo Maxx", "Lawn food"]
    assert entry["products"][1]["total_amount"] == 2500.0  # 2.5 kg/100m² over 100 m²
    assert entry["n_g_m2"] == 5.0

    gdd = hass.states.get(f"sensor.{LAWN}_gdd_since_pgr")
    assert gdd.attributes["days_since_application"] == 0
    assert gdd.attributes["product"] == "Primo Maxx"
    assert float(hass.states.get(f"sensor.{LAWN}_nitrogen_this_season").state) == pytest.approx(5.0)
    assert hass.states.get(f"sensor.{LAWN}_last_application").attributes["products"] == [
        "Primo Maxx 4 mL/100m²", "Lawn food 2.5 kg/100m²",
    ]

    # Rates in a mix can't be edited (which product?), but notes can.
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "update_entry", {"entry_id": entry["id"], "rate": 3}, blocking=True
        )
    await hass.services.async_call(
        DOMAIN, "update_entry", {"entry_id": entry["id"], "notes": "Watered in"}, blocking=True
    )


async def test_mix_input_is_checked(recorder_mock: Any, hass: HomeAssistant) -> None:
    import voluptuous as vol

    await _setup(hass)
    device_id = _lawn_device_id(hass)
    for bad in (
        {},  # neither product nor products
        {"product": "Lawn food", "products": [{"product": "Primo Maxx"}]},  # both
        {"products": [{"product": "Lawn food"}], "rate": 2},  # rate outside the list
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN, "log_application", {"device_id": device_id, **bad}, blocking=True
            )


async def test_build_a_mix_on_the_dashboard(recorder_mock: Any, hass: HomeAssistant) -> None:
    await _setup(hass)
    mix = f"sensor.{LAWN}_application_mix"
    assert hass.states.get(mix).state == "0"

    async def choose(product: str, rate: float | None = None) -> None:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": f"select.{LAWN}_product", "option": product},
            blocking=True,
        )
        if rate is not None:
            await hass.services.async_call(
                "number", "set_value", {"entity_id": f"number.{LAWN}_application_rate", "value": rate},
                blocking=True,
            )
        await hass.services.async_call(
            "button", "press", {"entity_id": f"button.{LAWN}_add_to_mix"}, blocking=True
        )

    await choose("Lawn food")  # its default rate, 2.5
    await choose("Primo Maxx", 4)
    state = hass.states.get(mix)
    assert state.state == "2"
    assert [(p["product"], p["rate"], p["unit"]) for p in state.attributes["products"]] == [
        ("Lawn food", 2.5, "kg/100m²"),
        ("Primo Maxx", 4.0, "mL/100m²"),
    ]

    # Adding a product again replaces it rather than duplicating it.
    await choose("Lawn food", 3)
    assert [(p["product"], p["rate"]) for p in hass.states.get(mix).attributes["products"]] == [
        ("Primo Maxx", 4.0), ("Lawn food", 3.0),
    ]

    # Remove one with the action, put it back, then log the mix as one application.
    await hass.services.async_call(
        DOMAIN, "mix_remove", {"device_id": _lawn_device_id(hass), "product": "Lawn food"},
        blocking=True,
    )
    assert hass.states.get(mix).state == "1"
    await choose("Lawn food", 2.5)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_log_application"}, blocking=True
    )
    await hass.async_block_till_done()

    history = await hass.services.async_call(
        DOMAIN, "get_history", {"kind": ["application"]}, blocking=True, return_response=True
    )
    (entry,) = history["entries"]
    assert entry["summary"] == "PGR mix: Primo Maxx 4 mL/100m² + Lawn food 2.5 kg/100m²"
    assert hass.states.get(mix).state == "0", "the mix is cleared once logged"

    # With an empty mix, Log logs just the selected product.
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_log_application"}, blocking=True
    )
    history = await hass.services.async_call(
        DOMAIN, "get_history", {"kind": ["application"]}, blocking=True, return_response=True
    )
    assert history["entries"][-1]["summary"] == "Lawn food 2.5 kg/100m²"

    # Clear mix empties it.
    await choose("Primo Maxx", 4)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_clear_mix"}, blocking=True
    )
    assert hass.states.get(mix).state == "0"


async def test_save_rate_as_product_default(recorder_mock: Any, hass: HomeAssistant) -> None:
    """The rate typed on the dashboard can become the product's default."""
    entry = await _setup(hass)
    rate = f"number.{LAWN}_application_rate"

    async def select(product: str) -> None:
        await hass.services.async_call(
            "select", "select_option", {"entity_id": f"select.{LAWN}_product", "option": product},
            blocking=True,
        )
        await hass.async_block_till_done()

    await select("Primo Maxx")
    await hass.services.async_call("number", "set_value", {"entity_id": rate, "value": 4.5}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{LAWN}_save_rate_as_product_default"}, blocking=True
    )
    await hass.async_block_till_done()

    primo = next(s for s in entry.subentries.values() if s.title == "Primo Maxx")
    assert primo.data["rate"] == 4.5
    assert primo.data["rate_unit"] == "mL/100m²", "other product settings are kept"

    # Choosing the product again fills in the saved rate.
    await select("Lawn food")
    assert float(hass.states.get(rate).state) == 2.5
    await select("Primo Maxx")
    assert float(hass.states.get(rate).state) == 4.5


async def test_log_date_back_dates_dashboard_logging(recorder_mock: Any, hass: HomeAssistant) -> None:
    """Set the Log date to catch up; it applies until midnight, never in the future."""
    from homeassistant.exceptions import HomeAssistantError

    entry = await _setup(hass)
    log_date = f"date.{LAWN}_log_date"
    today = dt_util.now().date()
    yesterday = today - timedelta(days=1)
    assert hass.states.get(log_date).state == today.isoformat()

    async def press(button: str) -> None:
        await hass.services.async_call("button", "press", {"entity_id": f"button.{LAWN}_{button}"}, blocking=True)
        await hass.async_block_till_done()

    async def entries() -> list[dict[str, Any]]:
        result = await hass.services.async_call(
            DOMAIN, "get_history", {}, blocking=True, return_response=True
        )
        return result["entries"]

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "date", "set_value",
            {"entity_id": log_date, "date": (today + timedelta(days=1)).isoformat()}, blocking=True,
        )

    await hass.services.async_call(
        "date", "set_value", {"entity_id": log_date, "date": yesterday.isoformat()}, blocking=True
    )
    await press("log_mow")
    await press("log_application")
    await press("log_activity")
    logged = await entries()
    assert [(e["kind"], e["date"], e["all_day"]) for e in logged] == [
        ("mow", yesterday.isoformat(), True),
        ("application", yesterday.isoformat(), True),
        ("activity", yesterday.isoformat(), True),
    ]
    assert all("weather" not in e for e in logged), "no weather snapshot for back-dated entries"
    assert hass.states.get(log_date).state == yesterday.isoformat(), "kept for catching up"

    # Midnight puts it back to today; today logs "now", with the time.
    await entry.runtime_data.coordinator._async_midnight(dt_util.now())
    await hass.async_block_till_done()
    assert hass.states.get(log_date).state == today.isoformat()
    await press("log_mow")
    newest = (await entries())[-1]
    assert newest["date"] == today.isoformat()
    assert newest["all_day"] is False


async def test_fallback_sensor_gdd_for_comparison(recorder_mock: Any, hass: HomeAssistant) -> None:
    """With a fallback sensor, each lawn also counts GDD from it alone, from recorder statistics."""
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_import_statistics
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    fallback = "sensor.bom_temperature"
    _set_sensor(hass)
    hass.states.async_set(
        fallback, "22",
        {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"},
    )
    today = dt_util.now().date()
    for statistic_id, mean in ((TEMP_SENSOR, 20.0), (fallback, 22.0)):
        rows = []
        for offset in (3, 2, 1):
            midnight = dt_util.start_of_local_day(today - timedelta(days=offset))
            rows += [
                {"start": dt_util.as_utc(midnight + timedelta(hours=h)), "mean": mean,
                 "min": mean - 5, "max": mean + 5}
                for h in range(24)
            ]
        async_import_statistics(
            hass,
            {
                "mean_type": StatisticMeanType.ARITHMETIC,
                "has_sum": False,
                "name": None,
                "source": "recorder",
                "statistic_id": statistic_id,
                "unit_class": "temperature",
                "unit_of_measurement": "°C",
            },
            rows,
        )
    await async_wait_recording_done(hass)

    await _setup(hass, {"fallback_temperature_sensor": fallback})
    await hass.services.async_call(
        "date", "set_value",
        {"entity_id": f"date.{LAWN}_last_pgr_application", "date": (today - timedelta(days=3)).isoformat()},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Warm season, base 10: main 3 x (20 - 10) = 30; fallback 3 x (22 - 10) = 36 (plus today so far).
    main = hass.states.get(f"sensor.{LAWN}_gdd_since_pgr")
    assert main.attributes["gdd_completed_days"] == pytest.approx(30.0)
    assert main.attributes["missing_days"] == []
    compare = hass.states.get(f"sensor.{LAWN}_gdd_since_pgr_fallback_sensor")
    assert compare is not None
    # No statistics for today yet, so today adds 0 to both.
    assert float(main.state) == pytest.approx(30.0)
    assert float(compare.state) == pytest.approx(36.0)
    assert compare.attributes["difference"] == pytest.approx(6.0)
    assert compare.attributes["difference_percent"] == pytest.approx(20.0)
    assert compare.attributes["fallback_sensor"] == fallback
    assert compare.attributes["missing_days"] == []


async def test_no_fallback_comparison_without_a_fallback_sensor(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    await _setup(hass)
    assert hass.states.get(f"sensor.{LAWN}_gdd_since_pgr_fallback_sensor") is None
