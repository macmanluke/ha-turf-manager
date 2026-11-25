"""Config flow: a site (weather sources), plus lawn and product subentries."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ACTIVE_INGREDIENT,
    CONF_ADD_PGR_PRESET,
    CONF_AREA,
    CONF_BASE_TEMP,
    CONF_DENSITY,
    CONF_FALLBACK_SENSOR,
    CONF_GDD_INTERVAL,
    CONF_GDD_TARGET,
    CONF_GRASS_TYPE,
    CONF_HEIGHT_UNIT,
    CONF_HUMIDITY_SENSOR,
    CONF_K,
    CONF_METHOD,
    CONF_MIN_RUN,
    CONF_MOA_GROUP,
    CONF_N,
    CONF_NOTES,
    CONF_P,
    CONF_PGR_MODEL,
    CONF_PGR_PRODUCT,
    CONF_PRESET,
    CONF_PRODUCT_TYPE,
    CONF_RAIN_SENSOR,
    CONF_RATE,
    CONF_RATE_UNIT,
    CONF_SEASON_START_MONTH,
    CONF_TEMP_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    CONF_ZONE_ENTITY,
    CONF_ZONE_LAWN,
    DEFAULT_BASE_TEMPS,
    DEFAULT_GDD_TARGET,
    DEFAULT_METHOD,
    DEFAULT_MIN_RUN,
    DEFAULT_SEASON_START_MONTH,
    DOMAIN,
    GRASS_CUSTOM,
    GRASS_TYPES,
    GRASS_WARM,
    HEIGHT_UNIT_AUTO,
    HEIGHT_UNIT_OPTIONS,
    PGR_MODEL_NONE,
    PGR_MODEL_OPTIONS,
    PRODUCT_PGR,
    PRODUCT_PRESETS,
    PRODUCT_TYPES,
    SUBENTRY_LAWN,
    SUBENTRY_PRODUCT,
    SUBENTRY_ZONE,
)
from .gdd import METHODS
from .units import RATE_UNITS

_SITE_KEYS = (
    CONF_TEMP_SENSOR,
    CONF_FALLBACK_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_METHOD,
    CONF_SEASON_START_MONTH,
    CONF_HEIGHT_UNIT,
    CONF_HUMIDITY_SENSOR,
    CONF_WIND_SENSOR,
    CONF_RAIN_SENSOR,
)


def _select(options: list[str], key: str, *, dropdown: bool = True) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            translation_key=key,
            mode=SelectSelectorMode.DROPDOWN if dropdown else SelectSelectorMode.LIST,
        )
    )


def _sensor(device_class: str | None = None) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="sensor", device_class=device_class))


def _number(
    minimum: float, maximum: float, step: float | str = "any", unit: str | None = None
) -> NumberSelector:
    config = NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX)
    if unit is not None:
        # The selector rejects a None unit, so only set it when there is one.
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _opt(key: str, values: dict[str, Any]) -> vol.Optional:
    """Optional field that keeps its current value as a suggestion (clearable)."""
    if values.get(key) not in (None, ""):
        return vol.Optional(key, description={"suggested_value": values[key]})
    return vol.Optional(key)


def _site_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TEMP_SENSOR, default=values.get(CONF_TEMP_SENSOR, vol.UNDEFINED)): _sensor(
                SensorDeviceClass.TEMPERATURE
            ),
            _opt(CONF_FALLBACK_SENSOR, values): _sensor(SensorDeviceClass.TEMPERATURE),
            _opt(CONF_WEATHER_ENTITY, values): EntitySelector(EntitySelectorConfig(domain="weather")),
            vol.Required(CONF_METHOD, default=values.get(CONF_METHOD, DEFAULT_METHOD)): _select(
                list(METHODS), "gdd_method", dropdown=False
            ),
            vol.Required(
                CONF_SEASON_START_MONTH,
                default=values.get(CONF_SEASON_START_MONTH, DEFAULT_SEASON_START_MONTH),
            ): _select([str(m) for m in range(1, 13)], "month"),
            vol.Required(
                CONF_HEIGHT_UNIT, default=values.get(CONF_HEIGHT_UNIT, HEIGHT_UNIT_AUTO)
            ): _select(HEIGHT_UNIT_OPTIONS, "height_unit"),
            _opt(CONF_HUMIDITY_SENSOR, values): _sensor(SensorDeviceClass.HUMIDITY),
            _opt(CONF_WIND_SENSOR, values): _sensor(SensorDeviceClass.WIND_SPEED),
            _opt(CONF_RAIN_SENSOR, values): _sensor(),
        }
    )


def _validate_site(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if user_input.get(CONF_FALLBACK_SENSOR) == user_input[CONF_TEMP_SENSOR]:
        errors[CONF_FALLBACK_SENSOR] = "same_as_primary"
    return errors


def _lawn_schema(values: dict[str, Any], *, with_name: bool = True) -> vol.Schema:
    schema: dict[Any, Any] = {}
    if with_name:
        schema[vol.Required(CONF_NAME, default=values.get(CONF_NAME, vol.UNDEFINED))] = TextSelector()
    schema.update(
        {
            vol.Required(CONF_GRASS_TYPE, default=values.get(CONF_GRASS_TYPE, GRASS_WARM)): _select(
                GRASS_TYPES, "grass_type", dropdown=False
            ),
            _opt(CONF_AREA, values): _number(1, 1_000_000, 1, "m²"),
            vol.Required(
                CONF_GDD_TARGET, default=values.get(CONF_GDD_TARGET, DEFAULT_GDD_TARGET)
            ): _number(50, 1500, 5, "GDD"),
        }
    )
    return vol.Schema(schema)


def _base_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_BASE_TEMP,
                default=values.get(CONF_BASE_TEMP, DEFAULT_BASE_TEMPS[GRASS_CUSTOM]),
            ): _number(-5, 20, 0.5, "°C"),
        }
    )


def _lawn_data(user_input: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build lawn data; keep a tuned base temperature unless the grass type changed."""
    previous = previous or {}
    grass = user_input[CONF_GRASS_TYPE]
    data = {k: v for k, v in previous.items() if k not in (CONF_NAME,)}
    data.update(
        {
            CONF_GRASS_TYPE: grass,
            CONF_GDD_TARGET: float(user_input[CONF_GDD_TARGET]),
        }
    )
    if user_input.get(CONF_AREA):
        data[CONF_AREA] = float(user_input[CONF_AREA])
    else:
        data.pop(CONF_AREA, None)
    if CONF_BASE_TEMP in user_input:
        data[CONF_BASE_TEMP] = float(user_input[CONF_BASE_TEMP])
    elif grass != previous.get(CONF_GRASS_TYPE) or CONF_BASE_TEMP not in data:
        data[CONF_BASE_TEMP] = DEFAULT_BASE_TEMPS[grass]
    return data


def _preset_product_data(preset: str) -> tuple[str, dict[str, Any]]:
    values = dict(PRODUCT_PRESETS[preset])
    name = values.pop("name")
    return name, values


class TurfManagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a site: weather sources, then the first lawn."""

    VERSION = 1

    def __init__(self) -> None:
        self._site: dict[str, Any] = {}
        self._lawn: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_LAWN: LawnSubentryFlow,
            SUBENTRY_PRODUCT: ProductSubentryFlow,
            SUBENTRY_ZONE: IrrigationZoneSubentryFlow,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TurfManagerOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_site(user_input)
            if not errors:
                self._site = user_input
                return await self.async_step_lawn()
        schema = vol.Schema(
            {vol.Required(CONF_NAME, default="Home"): TextSelector(), **_site_schema(user_input or {}).schema}
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_lawn(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._lawn = user_input
            if user_input[CONF_GRASS_TYPE] == GRASS_CUSTOM:
                return await self.async_step_lawn_base()
            return self._create()
        schema = _lawn_schema({CONF_NAME: "Front lawn"}).extend(
            {vol.Required(CONF_ADD_PGR_PRESET, default=True): BooleanSelector()}
        )
        return self.async_show_form(step_id="lawn", data_schema=schema)

    async def async_step_lawn_base(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._lawn.update(user_input)
            return self._create()
        return self.async_show_form(step_id="lawn_base", data_schema=_base_schema({}))

    def _create(self) -> ConfigFlowResult:
        site = dict(self._site)
        title = site.pop(CONF_NAME)
        subentries: list[dict[str, Any]] = [
            {
                "subentry_type": SUBENTRY_LAWN,
                "title": self._lawn[CONF_NAME],
                "data": _lawn_data(self._lawn),
                "unique_id": None,
            }
        ]
        if self._lawn.get(CONF_ADD_PGR_PRESET):
            name, data = _preset_product_data("trinexapac")
            subentries.append(
                {"subentry_type": SUBENTRY_PRODUCT, "title": name, "data": data, "unique_id": None}
            )
        return self.async_create_entry(title=title, data=site, subentries=subentries)


class TurfManagerOptionsFlow(OptionsFlow):
    """Edit the site's weather sources and preferences."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_site(user_input)
            if not errors:
                # Store every key so clearing an optional sensor overrides the original data.
                return self.async_create_entry(data={k: user_input.get(k) for k in _SITE_KEYS})
        current = {**self.config_entry.data, **self.config_entry.options}
        values = {k: current.get(k) for k in _SITE_KEYS} | (user_input or {})
        return self.async_show_form(step_id="init", data_schema=_site_schema(values), errors=errors)


class LawnSubentryFlow(ConfigSubentryFlow):
    """Add or edit a lawn."""

    def __init__(self) -> None:
        self._input: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._input = user_input
            if user_input[CONF_GRASS_TYPE] == GRASS_CUSTOM:
                return await self.async_step_base()
            return self._finish()
        return self.async_show_form(step_id="user", data_schema=_lawn_schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            self._input = user_input
            if user_input[CONF_GRASS_TYPE] == GRASS_CUSTOM:
                return await self.async_step_base()
            return self._finish()
        values = {CONF_NAME: subentry.title, **subentry.data}
        schema = _lawn_schema(values).extend(
            {_opt(CONF_PGR_PRODUCT, values): self._pgr_product_selector()}
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    async def async_step_base(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._input.update(user_input)
            return self._finish()
        values = self._get_reconfigure_subentry().data if self.source == SOURCE_RECONFIGURE else {}
        return self.async_show_form(step_id="base", data_schema=_base_schema(values))

    def _pgr_product_selector(self) -> SelectSelector:
        entry = self._get_entry()
        options = [
            {"value": sid, "label": sub.title}
            for sid, sub in entry.subentries.items()
            if sub.subentry_type == SUBENTRY_PRODUCT and sub.data.get(CONF_PRODUCT_TYPE) == PRODUCT_PGR
        ]
        return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))

    def _finish(self) -> SubentryFlowResult:
        name = self._input[CONF_NAME]
        if self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            data = _lawn_data(self._input, dict(subentry.data))
            if self._input.get(CONF_PGR_PRODUCT):
                data[CONF_PGR_PRODUCT] = self._input[CONF_PGR_PRODUCT]
            else:
                data.pop(CONF_PGR_PRODUCT, None)
            return self.async_update_and_abort(self._get_entry(), subentry, title=name, data=data)
        return self.async_create_entry(title=name, data=_lawn_data(self._input))


class ProductSubentryFlow(ConfigSubentryFlow):
    """Add or edit a product in the library."""

    def __init__(self) -> None:
        self._defaults: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            if user_input[CONF_PRESET] != "custom":
                name, data = _preset_product_data(user_input[CONF_PRESET])
                self._defaults = {CONF_NAME: name, **data}
            return await self.async_step_details()
        schema = vol.Schema(
            {vol.Required(CONF_PRESET, default="custom"): _select(list(PRODUCT_PRESETS), "product_preset")}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        self._defaults = {CONF_NAME: subentry.title, **subentry.data}
        return await self.async_step_details(user_input)

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input.pop(CONF_NAME).strip()
            if self._name_taken(name):
                errors[CONF_NAME] = "name_exists"
            else:
                data = {k: v for k, v in user_input.items() if v not in (None, "")}
                if data.get(CONF_PGR_MODEL) == PGR_MODEL_NONE:
                    data.pop(CONF_PGR_MODEL)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_and_abort(
                        self._get_entry(), self._get_reconfigure_subentry(), title=name, data=data
                    )
                return self.async_create_entry(title=name, data=data)
            self._defaults = {CONF_NAME: name, **user_input}
        return self.async_show_form(
            step_id="details", data_schema=self._details_schema(self._defaults), errors=errors
        )

    def _name_taken(self, name: str) -> bool:
        current = self._get_reconfigure_subentry().subentry_id if self.source == SOURCE_RECONFIGURE else None
        return any(
            sub.subentry_type == SUBENTRY_PRODUCT
            and sub.subentry_id != current
            and sub.title.casefold() == name.casefold()
            for sub in self._get_entry().subentries.values()
        )

    @staticmethod
    def _details_schema(values: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=values.get(CONF_NAME, vol.UNDEFINED)): TextSelector(),
                vol.Required(
                    CONF_PRODUCT_TYPE, default=values.get(CONF_PRODUCT_TYPE, "fertiliser")
                ): _select(PRODUCT_TYPES, "product_type"),
                _opt(CONF_ACTIVE_INGREDIENT, values): TextSelector(),
                _opt(CONF_RATE, values): _number(0, 100000),
                vol.Required(
                    CONF_RATE_UNIT, default=values.get(CONF_RATE_UNIT, "kg/100m²")
                ): SelectSelector(SelectSelectorConfig(options=RATE_UNITS, mode=SelectSelectorMode.DROPDOWN)),
                _opt(CONF_N, values): _number(0, 100, "any", "%"),
                _opt(CONF_P, values): _number(0, 100, "any", "%"),
                _opt(CONF_K, values): _number(0, 100, "any", "%"),
                _opt(CONF_DENSITY, values): _number(0.1, 5, "any", "kg/L"),
                _opt(CONF_GDD_INTERVAL, values): _number(50, 1500, 5, "GDD"),
                vol.Required(
                    CONF_PGR_MODEL, default=values.get(CONF_PGR_MODEL, PGR_MODEL_NONE)
                ): _select(PGR_MODEL_OPTIONS, "pgr_model"),
                _opt(CONF_MOA_GROUP, values): TextSelector(),
                _opt(CONF_NOTES, values): TextSelector(TextSelectorConfig(multiline=True)),
            }
        )


class IrrigationZoneSubentryFlow(ConfigSubentryFlow):
    """Add or edit a sprinkler zone: its on/off entity and the lawn it waters."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._lawn_options():
            return self.async_abort(reason="no_lawns")
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.pop(CONF_NAME).strip(), data=_zone_data(user_input)
            )
        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input.pop(CONF_NAME).strip(),
                data=_zone_data(user_input),
            )
        values = {CONF_NAME: subentry.title, **subentry.data}
        return self.async_show_form(step_id="reconfigure", data_schema=self._schema(values))

    def _lawn_options(self) -> list[dict[str, str]]:
        return [
            {"value": sid, "label": sub.title}
            for sid, sub in self._get_entry().subentries.items()
            if sub.subentry_type == SUBENTRY_LAWN
        ]

    def _schema(self, values: dict[str, Any]) -> vol.Schema:
        lawns = self._lawn_options()
        return vol.Schema(
            {
                vol.Required(CONF_NAME, default=values.get(CONF_NAME, vol.UNDEFINED)): TextSelector(),
                _opt(CONF_ZONE_ENTITY, values): EntitySelector(
                    EntitySelectorConfig(domain=["switch", "valve", "input_boolean"])
                ),
                vol.Required(
                    CONF_ZONE_LAWN, default=values.get(CONF_ZONE_LAWN, lawns[0]["value"])
                ): SelectSelector(SelectSelectorConfig(options=lawns, mode=SelectSelectorMode.DROPDOWN)),
                vol.Required(
                    CONF_MIN_RUN, default=values.get(CONF_MIN_RUN, DEFAULT_MIN_RUN)
                ): _number(0, 3600, 1, "s"),
            }
        )


def _zone_data(user_input: dict[str, Any]) -> dict[str, Any]:
    data = {
        CONF_ZONE_LAWN: user_input[CONF_ZONE_LAWN],
        CONF_MIN_RUN: int(user_input[CONF_MIN_RUN]),
    }
    if user_input.get(CONF_ZONE_ENTITY):
        data[CONF_ZONE_ENTITY] = user_input[CONF_ZONE_ENTITY]
    return data
