"""Growing degree day (GDD) maths for Turf Manager.

Pure Python with no Home Assistant imports, so it can be unit tested on its own.

The models follow the UNL PGR GDD Tracker v2.0 (Kreuser, University of
Nebraska-Lincoln) and the Syngenta Grow Degree Days workbook, with one deliberate
change: a day's GDD is never negative (the warm-season spreadsheet edits let cold
days subtract from the running total).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

METHOD_MEAN = "mean"
"""Time-weighted daily mean temperature (preferred)."""
METHOD_MINMAX = "minmax"
"""(Tmax + Tmin) / 2."""
METHOD_MINMAX_FLOOR = "minmax_floor"
"""(Tmax + max(Tmin, base)) / 2, the UNL 'High-Low Temp Option'."""

METHODS = (METHOD_MEAN, METHOD_MINMAX, METHOD_MINMAX_FLOOR)


@dataclass(frozen=True, slots=True)
class PgrModel:
    """UNL relative clipping yield model coefficients for a PGR active ingredient.

    RY = 1 + A * sin(2*pi * GDD^C / B - pi), and RY = 1 once GDD exceeds ``range``.
    Fitted on cool-season putting greens with GDD in base 0 °C.
    """

    a: float
    b: float
    c: float
    range: float


PGR_MODELS: dict[str, PgrModel] = {
    "trinexapac": PgrModel(a=0.183, b=138.828, c=0.738, range=800),
    "paclobutrazol": PgrModel(a=0.454, b=966.112, c=1.01, range=885),
    "prohexadione": PgrModel(a=0.205, b=191.5, c=0.7587, range=1000),
}


def daily_temperature(
    mean: float | None,
    t_min: float | None,
    t_max: float | None,
    method: str,
    base: float,
) -> float | None:
    """Return the temperature used for a day's GDD, or None if there is no data.

    ``mean`` falls back to the min/max average when no true mean is available.
    """
    if method == METHOD_MEAN:
        if mean is not None:
            return mean
        if t_min is not None and t_max is not None:
            return (t_min + t_max) / 2
        return None
    if t_min is None or t_max is None:
        return mean
    if method == METHOD_MINMAX_FLOOR:
        return (t_max + max(t_min, base)) / 2
    return (t_max + t_min) / 2


def daily_gdd(t_day: float | None, base: float) -> float:
    """GDD for one day: degrees above base, never negative. Missing data gives 0."""
    if t_day is None:
        return 0.0
    return max(0.0, t_day - base)


def cumulative(values: Iterable[float]) -> list[float]:
    """Running total of daily GDD values."""
    total = 0.0
    out: list[float] = []
    for value in values:
        total += value
        out.append(total)
    return out


def relative_growth(gdd: float, model: PgrModel) -> float:
    """UNL relative clipping yield (1.0 = untreated growth, <1 suppressed, >1 rebound)."""
    if gdd <= 0:
        return 1.0
    if gdd > model.range:
        return 1.0
    return 1 + model.a * math.sin(2 * math.pi * gdd**model.c / model.b - math.pi)


def paclobutrazol_interval(rate_fl_oz_per_acre: float) -> float:
    """UNL re-application interval for paclobutrazol (Trimmit 2SC) from its rate."""
    return rate_fl_oz_per_acre * 18.182 + 150


@dataclass(frozen=True, slots=True)
class Projection:
    """Result of projecting when the GDD target will be reached."""

    due_date: date | None
    method: str  # "reached", "forecast", "estimated" or "unknown"
    days: list[tuple[date, float, str]]  # (day, gdd, source) used for the projection


def project_due_date(
    *,
    completed_gdd: float,
    target: float,
    today: date,
    today_partial_gdd: float,
    forecast_gdd: Mapping[date, float],
    fallback_daily_gdd: float | None,
    max_days: int = 180,
) -> Projection:
    """Project the date cumulative GDD reaches ``target``.

    ``completed_gdd`` covers finished days since application. Today uses the
    forecast's full-day value when available (never less than what has already
    accrued), and later days use the forecast, then ``fallback_daily_gdd``
    (typically the trailing 7-day average).
    """
    if completed_gdd + today_partial_gdd >= target:
        return Projection(today, "reached", [])

    total = completed_gdd
    used: list[tuple[date, float, str]] = []
    estimated = False
    for offset in range(max_days):
        day = today + timedelta(days=offset)
        if day in forecast_gdd:
            gdd = forecast_gdd[day]
            source = "forecast"
        elif fallback_daily_gdd is not None and fallback_daily_gdd > 0:
            gdd = fallback_daily_gdd
            source = "estimated"
            estimated = True
        else:
            return Projection(None, "unknown", used)
        if offset == 0:
            gdd = max(gdd, today_partial_gdd)
        total += gdd
        used.append((day, round(gdd, 2), source))
        if total >= target:
            return Projection(day, "estimated" if estimated else "forecast", used)
    return Projection(None, "unknown", used)


@dataclass(frozen=True, slots=True)
class WindowStats:
    """Time-weighted statistics for a window of samples."""

    mean: float | None
    minimum: float | None
    maximum: float | None
    hours: float


def time_weighted_stats(
    samples: Sequence[tuple[float, float]],
    start_ts: float,
    end_ts: float,
    max_gap_s: float = 3 * 3600,
) -> WindowStats:
    """Time-weighted mean/min/max over [start_ts, end_ts).

    ``samples`` are (unix timestamp, value) pairs sorted by time; each value holds
    until the next sample. A sample before ``start_ts`` carries into the window.
    Values held longer than ``max_gap_s`` are treated as a sensor outage after
    that point, so they don't count towards coverage.
    """
    if end_ts <= start_ts or not samples:
        return WindowStats(None, None, None, 0.0)

    weighted = 0.0
    covered = 0.0
    minimum: float | None = None
    maximum: float | None = None
    for idx, (ts, value) in enumerate(samples):
        next_ts = samples[idx + 1][0] if idx + 1 < len(samples) else end_ts
        seg_start = max(ts, start_ts)
        seg_end = min(next_ts, end_ts, ts + max_gap_s)
        if seg_end <= seg_start:
            continue
        duration = seg_end - seg_start
        weighted += value * duration
        covered += duration
        minimum = value if minimum is None else min(minimum, value)
        maximum = value if maximum is None else max(maximum, value)

    if covered == 0:
        return WindowStats(None, None, None, 0.0)
    return WindowStats(weighted / covered, minimum, maximum, covered / 3600)


def trailing_average(values: Sequence[float], days: int = 7) -> float | None:
    """Average of the last ``days`` values, or None when there are none."""
    window = list(values)[-days:]
    if not window:
        return None
    return sum(window) / len(window)
