"""Number entities: PGR settings and staged values for dashboard logging."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TurfConfigEntry
from .const import CONF_BASE_TEMP, CONF_GDD_TARGET, SUBENTRY_LAWN
from .coordinator import TurfCoordinator
from .entity import TurfLawnEntity
from .units import HEIGHT_UNIT_IN, mm_to_unit, rate_step, unit_to_mm

DEFAULT_CUT_HEIGHT_MM = 25.0
DEFAULT_WATERING_MINUTES = 15


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TurfConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_LAWN:
            continue
        async_add_entities(
            [
                LawnSettingNumber(
                    coordinator, subentry_id, "gdd_target", CONF_GDD_TARGET, 50, 1500, 5, "GDD"
                ),
                LawnSettingNumber(
                    coordinator,
                    subentry_id,
                    "base_temperature",
                    CONF_BASE_TEMP,
                    -5,
                    20,
                    0.5,
                    UnitOfTemperature.CELSIUS,
                    NumberDeviceClass.TEMPERATURE,
                ),
                CutHeightNumber(coordinator, subentry_id),
                ApplicationRateNumber(coordinator, subentry_id),
                WateringMinutesNumber(coordinator, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )


class LawnSettingNumber(TurfLawnEntity, NumberEntity):
    """A lawn setting stored in the lawn's configuration."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: TurfCoordinator,
        lawn_id: str,
        key: str,
        conf_key: str,
        minimum: float,
        maximum: float,
        step: float,
        unit: str,
        device_class: NumberDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, lawn_id, key)
        self._conf_key = conf_key
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def native_value(self) -> float:
        lawn = self.lawn
        return lawn.gdd_target if self._conf_key == CONF_GDD_TARGET else lawn.base_temp

    async def async_set_native_value(self, value: float) -> None:
        entry = self.coordinator.config_entry
        subentry = entry.subentries[self._lawn_id]
        self.hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, self._conf_key: value}
        )


class CutHeightNumber(TurfLawnEntity, RestoreNumber):
    """Cut height staged for the 'Log mow' button (shown in mm or inches)."""

    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.DISTANCE

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "cut_height")
        self._unit = coordinator.height_unit
        if self._unit == HEIGHT_UNIT_IN:
            self._attr_native_unit_of_measurement = UnitOfLength.INCHES
            self._attr_native_min_value = 0.1
            self._attr_native_max_value = 6
            self._attr_native_step = 0.05
        else:
            self._attr_native_unit_of_measurement = UnitOfLength.MILLIMETERS
            self._attr_native_min_value = 2
            self._attr_native_max_value = 150
            self._attr_native_step = 0.5

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        height_mm = DEFAULT_CUT_HEIGHT_MM
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            restored_unit = last.native_unit_of_measurement
            height_mm = unit_to_mm(
                last.native_value, HEIGHT_UNIT_IN if restored_unit == UnitOfLength.INCHES else "mm"
            )
        elif self.lawn_state and self.lawn_state.last_mow and self.lawn_state.last_mow.get("height_mm"):
            height_mm = self.lawn_state.last_mow["height_mm"]
        self.staged["height_mm"] = height_mm

    @property
    def native_value(self) -> float | None:
        height_mm = self.staged.get("height_mm")
        if height_mm is None:
            return None
        return round(mm_to_unit(height_mm, self._unit), 2)

    async def async_set_native_value(self, value: float) -> None:
        self.staged["height_mm"] = unit_to_mm(value, self._unit)
        self.async_write_ha_state()


class ApplicationRateNumber(TurfLawnEntity, RestoreNumber):
    """Rate staged for the 'Log application' button, in the selected product's unit."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100000

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "application_rate")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self.staged.setdefault("rate", last.native_value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        product = self.coordinator.products().get(self.staged.get("product_id") or "")
        return product.rate_unit if product else None

    @property
    def native_step(self) -> float:
        return rate_step(self.native_unit_of_measurement)

    @property
    def native_value(self) -> float | None:
        return self.staged.get("rate")

    async def async_set_native_value(self, value: float) -> None:
        self.staged["rate"] = value
        self.async_write_ha_state()


class WateringMinutesNumber(TurfLawnEntity, RestoreNumber):
    """Minutes staged for the 'Log watering' button (watering by hand)."""

    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 600
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator: TurfCoordinator, lawn_id: str) -> None:
        super().__init__(coordinator, lawn_id, "watering_minutes")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self.staged.setdefault("watering_minutes", last.native_value)
        self.staged.setdefault("watering_minutes", DEFAULT_WATERING_MINUTES)

    @property
    def native_value(self) -> float | None:
        return self.staged.get("watering_minutes")

    async def async_set_native_value(self, value: float) -> None:
        self.staged["watering_minutes"] = value
        self.async_write_ha_state()
