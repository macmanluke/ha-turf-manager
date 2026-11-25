"""Unit helpers for application rates, nutrients and cut heights (pure Python)."""

from __future__ import annotations

MM_PER_INCH = 25.4

HEIGHT_UNIT_MM = "mm"
HEIGHT_UNIT_IN = "in"

# Application rate units. Mass rates convert to g/m², volume rates to mL/m².
MASS_RATE_UNITS: dict[str, float] = {
    "g/m²": 1.0,
    "g/100m²": 0.01,
    "kg/100m²": 10.0,
    "kg/ha": 0.1,
    "lb/1000ft²": 453.59237 / 92.90304,
    "oz/1000ft²": 28.349523125 / 92.90304,
}
VOLUME_RATE_UNITS: dict[str, float] = {
    "mL/m²": 1.0,
    "mL/100m²": 0.01,
    "L/100m²": 10.0,
    "L/ha": 0.1,
    "fl oz/1000ft²": 29.5735295625 / 92.90304,
    "fl oz/acre": 29.5735295625 / 4046.8564224,
}
RATE_UNITS: list[str] = [*MASS_RATE_UNITS, *VOLUME_RATE_UNITS]

# Units whose typical label rates are whole numbers get a step of 1; the rest 0.1.
# The step only affects +/- buttons and sliders: a typed value is accepted as is.
_WHOLE_NUMBER_RATE_UNITS = {"g/m²", "kg/ha", "mL/100m²", "fl oz/acre"}


def rate_step(unit: str | None) -> float:
    """Sensible increment for a rate in ``unit``."""
    return 1.0 if unit in _WHOLE_NUMBER_RATE_UNITS else 0.1


def is_mass_unit(unit: str) -> bool:
    """Whether a rate unit is mass per area."""
    return unit in MASS_RATE_UNITS


def to_base_rate(rate: float, unit: str) -> float:
    """Convert a rate to g/m² (mass units) or mL/m² (volume units)."""
    if unit in MASS_RATE_UNITS:
        return rate * MASS_RATE_UNITS[unit]
    if unit in VOLUME_RATE_UNITS:
        return rate * VOLUME_RATE_UNITS[unit]
    raise ValueError(f"Unknown rate unit: {unit}")


def convert_rate(rate: float, from_unit: str, to_unit: str) -> float:
    """Convert between two rate units of the same kind (mass or volume)."""
    if is_mass_unit(from_unit) != is_mass_unit(to_unit):
        raise ValueError(f"Cannot convert {from_unit} to {to_unit}")
    table = MASS_RATE_UNITS if is_mass_unit(from_unit) else VOLUME_RATE_UNITS
    return to_base_rate(rate, from_unit) / table[to_unit]


def total_product(rate: float, unit: str, area_m2: float) -> tuple[float, str]:
    """Total product needed for an area: (amount, 'g' or 'mL')."""
    base = to_base_rate(rate, unit) * area_m2
    return base, ("g" if is_mass_unit(unit) else "mL")


def nutrient_g_per_m2(
    rate: float,
    unit: str,
    percent: float | None,
    density_kg_per_l: float | None = None,
) -> float:
    """Grams of a nutrient per m² from a product rate and its analysis (% w/w).

    Volume rates are converted to mass with the product density (kg/L, default 1.0).
    """
    if not percent:
        return 0.0
    base = to_base_rate(rate, unit)
    if not is_mass_unit(unit):
        base *= density_kg_per_l or 1.0  # mL * g/mL = g
    return base * percent / 100


def mm_to_unit(value_mm: float, unit: str) -> float:
    """Convert a height in mm to ``unit`` (mm or in)."""
    return value_mm / MM_PER_INCH if unit == HEIGHT_UNIT_IN else value_mm


def unit_to_mm(value: float, unit: str) -> float:
    """Convert a height in ``unit`` (mm or in) to mm."""
    return value * MM_PER_INCH if unit == HEIGHT_UNIT_IN else value
