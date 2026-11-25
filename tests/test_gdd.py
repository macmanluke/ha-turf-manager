"""Tests for the pure GDD and unit maths.

Golden values come from the reference workbooks (UNL PGR GDD Tracker v2.0,
Lawn Addicts edit, Syngenta GDD workbook). These modules don't import Home
Assistant, so they're loaded by file path and run even without HA installed.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from math import isclose
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent / "custom_components" / "turf_manager"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"turf_manager_{name}", _PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gdd = _load("gdd")
units = _load("units")

TE = gdd.PGR_MODELS["trinexapac"]


def test_unl_hi_lo_rows() -> None:
    """UNL 'High-Low Temp Option' sample rows (°C, base 0, min floored at 0)."""
    rows = [(7.4, 26.0), (9.0, 27.0), (12.0, 27.0)]
    daily = [
        gdd.daily_gdd(gdd.daily_temperature(None, lo, hi, gdd.METHOD_MINMAX_FLOOR, 0), 0)
        for lo, hi in rows
    ]
    assert [round(v, 2) for v in daily] == [16.7, 18.0, 19.5]
    assert [round(v, 2) for v in gdd.cumulative(daily)] == [16.7, 34.7, 54.2]


def test_unl_relative_growth_model() -> None:
    """UNL relative clipping yield for trinexapac-ethyl at the sample cumulative GDD."""
    assert isclose(gdd.relative_growth(16.7, TE), 0.93528278936644205, rel_tol=1e-9)
    assert isclose(gdd.relative_growth(34.7, TE), 0.89365477432333185, rel_tol=1e-9)
    assert isclose(gdd.relative_growth(54.2, TE), 0.86110301087796637, rel_tol=1e-9)
    assert gdd.relative_growth(801, TE) == 1.0
    assert gdd.relative_growth(0, TE) == 1.0


def test_lawn_addicts_warm_season_row() -> None:
    """Lawn Addicts edit: min 13, max 27.5, warm season base 10 -> 10.25 GDD."""
    t_day = gdd.daily_temperature(None, 13.0, 27.5, gdd.METHOD_MINMAX, 10)
    assert t_day == 20.25
    assert gdd.daily_gdd(t_day, 10) == 10.25


def test_syngenta_warm_season_subtracts_ten() -> None:
    """Warm season: daily GDD = average temp - 10."""
    assert gdd.daily_gdd(24.0, 10) == 14.0
    assert gdd.daily_gdd(24.0, 0) == 24.0


def test_cold_day_clamps_to_zero() -> None:
    """The spreadsheets let cold days go negative; we don't."""
    assert gdd.daily_gdd(6.0, 10) == 0.0
    assert gdd.daily_gdd(-3.0, 0) == 0.0
    assert gdd.daily_gdd(None, 0) == 0.0


def test_mean_method_prefers_true_mean() -> None:
    assert gdd.daily_temperature(18.3, 10.0, 30.0, gdd.METHOD_MEAN, 0) == 18.3
    assert gdd.daily_temperature(None, 10.0, 30.0, gdd.METHOD_MEAN, 0) == 20.0
    assert gdd.daily_temperature(None, None, None, gdd.METHOD_MEAN, 0) is None


def test_minmax_floor_uses_base() -> None:
    # Warm season: lows below 10 are floored at 10.
    assert gdd.daily_temperature(None, 4.0, 26.0, gdd.METHOD_MINMAX_FLOOR, 10) == 18.0
    assert gdd.daily_temperature(None, 4.0, 26.0, gdd.METHOD_MINMAX, 10) == 15.0


def test_paclobutrazol_interval() -> None:
    """UNL: Trimmit 2SC at 5.5 fl oz/acre -> ~250 GDD interval."""
    assert round(gdd.paclobutrazol_interval(5.5)) == 250


def test_projection_reached() -> None:
    today = date(2026, 11, 25)
    result = gdd.project_due_date(
        completed_gdd=195, target=200, today=today, today_partial_gdd=6,
        forecast_gdd={}, fallback_daily_gdd=None,
    )
    assert result.due_date == today
    assert result.method == "reached"


def test_projection_uses_forecast_then_estimate() -> None:
    today = date(2026, 11, 25)
    forecast = {today + timedelta(days=i): 10.0 for i in range(3)}
    # 150 done + 3 forecast days of 10 = 180, then estimated 5/day -> 200 after 4 more.
    result = gdd.project_due_date(
        completed_gdd=150, target=200, today=today, today_partial_gdd=2,
        forecast_gdd=forecast, fallback_daily_gdd=5.0,
    )
    assert result.due_date == today + timedelta(days=6)
    assert result.method == "estimated"

    result = gdd.project_due_date(
        completed_gdd=180, target=200, today=today, today_partial_gdd=2,
        forecast_gdd=forecast, fallback_daily_gdd=None,
    )
    assert result.due_date == today + timedelta(days=1)
    assert result.method == "forecast"


def test_projection_unknown_without_growth() -> None:
    result = gdd.project_due_date(
        completed_gdd=10, target=200, today=date(2026, 7, 1), today_partial_gdd=0,
        forecast_gdd={}, fallback_daily_gdd=0.0,
    )
    assert result.due_date is None
    assert result.method == "unknown"


def test_time_weighted_stats() -> None:
    # 10 °C for 6 h, then 20 °C for 18 h -> mean 17.5 over 24 h.
    start = 1_000_000.0
    samples = [(start - 600, 10.0), (start + 6 * 3600, 20.0)]
    stats = gdd.time_weighted_stats(samples, start, start + 24 * 3600, max_gap_s=86400)
    assert isclose(stats.mean, 17.5)
    assert stats.minimum == 10.0
    assert stats.maximum == 20.0
    assert isclose(stats.hours, 24.0)


def test_time_weighted_stats_outage() -> None:
    # One sample then silence: only max_gap_s counts as covered.
    start = 0.0
    stats = gdd.time_weighted_stats([(start, 15.0)], start, start + 86400, max_gap_s=3600)
    assert stats.mean == 15.0
    assert isclose(stats.hours, 1.0)


def test_height_round_trip() -> None:
    assert isclose(units.unit_to_mm(1, units.HEIGHT_UNIT_IN), 25.4)
    assert isclose(units.mm_to_unit(25.4, units.HEIGHT_UNIT_IN), 1.0)
    assert units.mm_to_unit(30, units.HEIGHT_UNIT_MM) == 30


def test_rate_conversions() -> None:
    # 1 kg/100m² = 10 g/m²
    assert units.to_base_rate(1, "kg/100m²") == 10.0
    # 5.5 fl oz/acre is about 4.02 mL/100m²
    assert isclose(units.convert_rate(5.5, "fl oz/acre", "mL/100m²"), 4.019, rel_tol=1e-3)
    amount, unit = units.total_product(2, "kg/100m²", 150)
    assert (amount, unit) == (3000.0, "g")


def test_nitrogen_from_granular_and_liquid() -> None:
    # 2.5 kg/100m² of a 20% N product = 25 g/m² * 0.2 = 5 g N/m²
    assert isclose(units.nutrient_g_per_m2(2.5, "kg/100m²", 20), 5.0)
    # 1 L/100m² of liquid at 1.2 kg/L, 10% N = 10 mL/m² * 1.2 * 0.1 = 1.2 g N/m²
    assert isclose(units.nutrient_g_per_m2(1, "L/100m²", 10, 1.2), 1.2)
    assert units.nutrient_g_per_m2(1, "L/100m²", None) == 0.0
