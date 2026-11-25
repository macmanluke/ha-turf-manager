"""Constants for Turf Manager."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Final

from homeassistant.const import Platform

from .gdd import METHOD_MEAN

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "turf_manager"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.DATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

# --- Site (config entry) options -------------------------------------------
CONF_TEMP_SENSOR: Final = "temperature_sensor"
CONF_FALLBACK_SENSOR: Final = "fallback_temperature_sensor"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_METHOD: Final = "gdd_method"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_WIND_SENSOR: Final = "wind_sensor"
CONF_RAIN_SENSOR: Final = "rain_sensor"
CONF_SEASON_START_MONTH: Final = "season_start_month"
CONF_HEIGHT_UNIT: Final = "height_unit"
CONF_ADD_PGR_PRESET: Final = "add_pgr_preset"

DEFAULT_METHOD: Final = METHOD_MEAN
DEFAULT_SEASON_START_MONTH: Final = "7"
HEIGHT_UNIT_AUTO: Final = "auto"
HEIGHT_UNIT_OPTIONS: Final = [HEIGHT_UNIT_AUTO, "mm", "in"]

# --- Subentries ------------------------------------------------------------
SUBENTRY_LAWN: Final = "lawn"
SUBENTRY_PRODUCT: Final = "product"
SUBENTRY_ZONE: Final = "irrigation_zone"

# Irrigation zone
CONF_ZONE_ENTITY: Final = "switch_entity"
CONF_ZONE_LAWN: Final = "lawn"
CONF_MIN_RUN: Final = "min_run_seconds"
DEFAULT_MIN_RUN: Final = 60

# Lawn
CONF_GRASS_TYPE: Final = "grass_type"
CONF_BASE_TEMP: Final = "base_temperature"
CONF_AREA: Final = "area"
CONF_GDD_TARGET: Final = "gdd_target"
CONF_PGR_PRODUCT: Final = "pgr_product"

GRASS_COOL: Final = "cool"
GRASS_WARM: Final = "warm"
GRASS_CUSTOM: Final = "custom"
GRASS_TYPES: Final = [GRASS_WARM, GRASS_COOL, GRASS_CUSTOM]
DEFAULT_BASE_TEMPS: Final = {GRASS_COOL: 0.0, GRASS_WARM: 10.0, GRASS_CUSTOM: 10.0}
DEFAULT_GDD_TARGET: Final = 200.0

# Product
CONF_PRESET: Final = "preset"
CONF_PRODUCT_TYPE: Final = "product_type"
CONF_ACTIVE_INGREDIENT: Final = "active_ingredient"
CONF_RATE: Final = "rate"
CONF_RATE_UNIT: Final = "rate_unit"
CONF_N: Final = "n_percent"
CONF_P: Final = "p_percent"
CONF_K: Final = "k_percent"
CONF_DENSITY: Final = "density"
CONF_GDD_INTERVAL: Final = "gdd_interval"
CONF_PGR_MODEL: Final = "pgr_model"
CONF_MOA_GROUP: Final = "moa_group"
CONF_NOTES: Final = "notes"

PRODUCT_PGR: Final = "pgr"
PRODUCT_TYPES: Final = [
    "fertiliser",
    "herbicide",
    "insecticide",
    "fungicide",
    PRODUCT_PGR,
    "wetting_agent",
    "biostimulant",
    "other",
]
PGR_MODEL_NONE: Final = "none"
PGR_MODEL_OPTIONS: Final = [PGR_MODEL_NONE, "trinexapac", "paclobutrazol", "prohexadione"]

# Presets prefill the product form. Rates are deliberately left blank: always use
# the label rate for your product, turf species and region.
PRODUCT_PRESETS: Final[dict[str, dict[str, Any]]] = {
    "custom": {},
    "trinexapac": {
        "name": "Primo Maxx",
        CONF_PRODUCT_TYPE: PRODUCT_PGR,
        CONF_ACTIVE_INGREDIENT: "Trinexapac-ethyl",
        CONF_RATE_UNIT: "mL/100m²",
        CONF_GDD_INTERVAL: 200.0,
        CONF_PGR_MODEL: "trinexapac",
    },
    "paclobutrazol": {
        "name": "Paclobutrazol",
        CONF_PRODUCT_TYPE: PRODUCT_PGR,
        CONF_ACTIVE_INGREDIENT: "Paclobutrazol",
        CONF_RATE_UNIT: "mL/100m²",
        CONF_GDD_INTERVAL: 250.0,
        CONF_PGR_MODEL: "paclobutrazol",
    },
    "prohexadione": {
        "name": "Anuew",
        CONF_PRODUCT_TYPE: PRODUCT_PGR,
        CONF_ACTIVE_INGREDIENT: "Prohexadione-calcium",
        CONF_RATE_UNIT: "g/100m²",
        CONF_GDD_INTERVAL: 300.0,
        CONF_PGR_MODEL: "prohexadione",
    },
    "granular_fertiliser": {
        "name": "Granular fertiliser",
        CONF_PRODUCT_TYPE: "fertiliser",
        CONF_RATE_UNIT: "kg/100m²",
    },
    "liquid_fertiliser": {
        "name": "Liquid fertiliser",
        CONF_PRODUCT_TYPE: "fertiliser",
        CONF_RATE_UNIT: "mL/100m²",
        CONF_DENSITY: 1.0,
    },
    "herbicide": {
        "name": "Herbicide",
        CONF_PRODUCT_TYPE: "herbicide",
        CONF_RATE_UNIT: "mL/100m²",
    },
}

# --- Log entries -----------------------------------------------------------
KIND_APPLICATION: Final = "application"
KIND_MOW: Final = "mow"
KIND_ACTIVITY: Final = "activity"
KIND_IRRIGATION: Final = "irrigation"
ENTRY_KINDS: Final = [KIND_APPLICATION, KIND_MOW, KIND_ACTIVITY, KIND_IRRIGATION]
IRRIGATION_AUTO: Final = "auto"
IRRIGATION_MANUAL: Final = "manual"

MOWER_TYPES: Final = ["rotary", "cylinder", "robotic", "other"]
ACTIVITY_TYPES: Final = [
    "scarify",
    "core",
    "aerate",
    "top_dress",
    "level",
    "overseed",
    "soil_test",
    "other",
]
ACTIVITIES_ENABLED_BY_DEFAULT: Final = {"scarify", "core", "top_dress"}

# --- Weather / ledger ------------------------------------------------------
MIN_HOURS_COMPLETE: Final = 18.0
"""A day with less recorded data than this is 'incomplete'."""
FINALISE_DELAY: Final = timedelta(minutes=20)
"""Wait after local midnight before treating yesterday's statistics as final."""
DEFAULT_LOOKBACK_DAYS: Final = 14
MAX_BACKFILL_DAYS: Final = 400
LEDGER_KEEP_DAYS: Final = 3 * 366
UPDATE_INTERVAL: Final = timedelta(minutes=15)
FORECAST_INTERVAL: Final = timedelta(hours=1)

SOURCE_PRIMARY: Final = "primary"
SOURCE_FALLBACK: Final = "fallback"
SOURCE_MANUAL: Final = "manual"
SOURCE_NONE: Final = "none"

# --- Events ----------------------------------------------------------------
EVENT_ENTRY_LOGGED: Final = f"{DOMAIN}_entry_logged"
EVENT_PGR_DUE: Final = f"{DOMAIN}_pgr_due"

STORAGE_VERSION: Final = 1
