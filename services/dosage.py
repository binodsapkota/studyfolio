from __future__ import annotations

from dataclasses import dataclass


class DosageError(ValueError):
    """The dosage problem is missing data or uses an unsupported unit."""


@dataclass
class DosageResult:
    formula: str
    formula_shown: str
    substitution: str
    value: float
    unit: str
    details: list[str]


MASS_TO_MG = {"mcg": 0.001, "ug": 0.001, "mg": 1.0, "g": 1000.0}
WEIGHT_TO_KG = {
    "kg": 1.0,
    "lb": 0.45359237,
    "lbs": 0.45359237,
    "pound": 0.45359237,
    "pounds": 0.45359237,
}
VOLUME_TO_ML = {"ml": 1.0, "l": 1000.0, "liter": 1000.0, "liters": 1000.0}

_FORMULAS = {
    "tablet": "tablets",
    "tablets": "tablets",
    "weight": "weight_based",
    "weight_based": "weight_based",
    "iv_rate": "iv_rate",
    "iv_ml_hr": "iv_rate",
    "ml_hr": "iv_rate",
    "drip_rate": "drip_rate",
    "gtt": "drip_rate",
    "gtt_min": "drip_rate",
    "reconstitution": "reconstitution",
    "draw": "reconstitution",
}


def normalize_unit(unit: str) -> str:
    text = unit.strip().lower().replace("μ", "u").replace("µ", "u").replace(" ", "")
    aliases = {
        "microgram": "mcg",
        "micrograms": "mcg",
        "milligram": "mg",
        "milligrams": "mg",
        "gram": "g",
        "grams": "g",
        "milliliter": "ml",
        "milliliters": "ml",
        "cc": "ml",
        "kilogram": "kg",
        "kilograms": "kg",
        "litre": "l",
        "litres": "l",
    }
    return aliases.get(text, text)


def format_number(value: float) -> str:
    rounded = round(value, 4)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.4f}".rstrip("0").rstrip(".")


def _require(value: float | None, label: str) -> float:
    if value is None:
        raise DosageError(f"Missing {label}. No dose was calculated.")
    return value


def _to_mg(value: float, unit: str) -> tuple[float, str]:
    key = normalize_unit(unit.split("/")[0] if unit else "")
    if key not in MASS_TO_MG:
        raise DosageError(f"Mass unit '{unit or '(blank)'}' is not supported. Use mcg, mg, or g.")
    return value * MASS_TO_MG[key], key


def _to_ml(value: float, unit: str) -> float:
    key = normalize_unit(unit or "ml")
    if key not in VOLUME_TO_ML:
        raise DosageError(f"Volume unit '{unit}' is not supported. Use mL or L.")
    return value * VOLUME_TO_ML[key]


def _concentration_mg_per_ml(amount: float, unit: str) -> float:
    raw = (unit or "mg/ml").strip().lower().replace(" ", "")
    if "/" not in raw:
        mg, _ = _to_mg(amount, raw)
        return mg
    mass, volume = raw.split("/", 1)
    mg, _ = _to_mg(amount, mass)
    return mg / _to_ml(1, volume)


def compute_dosage(
    formula: str,
    *,
    desired_dose: float | None = None,
    desired_unit: str = "",
    have_dose: float | None = None,
    have_unit: str = "",
    weight: float | None = None,
    weight_unit: str = "",
    dose_per_kg: float | None = None,
    dose_per_kg_unit: str = "",
    volume_ml: float | None = None,
    volume_unit: str = "mL",
    hours: float | None = None,
    minutes: float | None = None,
    drop_factor: float | None = None,
    concentration: float | None = None,
    concentration_unit: str = "",
) -> DosageResult:
    key = _FORMULAS.get(formula.strip().lower())
    if key is None:
        raise DosageError(f"No dosage formula named '{formula}'.")
    if key == "tablets":
        return _tablets(desired_dose, desired_unit, have_dose, have_unit)
    if key == "weight_based":
        return _weight_based(
            weight, weight_unit, dose_per_kg, dose_per_kg_unit, have_dose, have_unit
        )
    if key == "iv_rate":
        return _iv_rate(volume_ml, volume_unit, hours, minutes)
    if key == "drip_rate":
        return _drip_rate(volume_ml, volume_unit, drop_factor, hours, minutes)
    return _reconstitution(desired_dose, desired_unit, concentration, concentration_unit)


def _tablets(
    desired_dose: float | None,
    desired_unit: str,
    have_dose: float | None,
    have_unit: str,
) -> DosageResult:
    desired_mg, desired_name = _to_mg(_require(desired_dose, "ordered dose"), desired_unit or "mg")
    have_mg, have_name = _to_mg(
        _require(have_dose, "amount on hand"), have_unit or desired_unit or "mg"
    )
    if have_mg == 0:
        raise DosageError("Amount on hand cannot be zero.")
    count = desired_mg / have_mg
    return DosageResult(
        formula="tablets",
        formula_shown="tablets = ordered dose / dose on hand",
        substitution=(
            f"{format_number(desired_dose or 0)} {desired_name} / "
            f"{format_number(have_dose or 0)} {have_name}"
        ),
        value=count,
        unit="tablet(s)",
        details=["Round using your course rule before you write the final answer."],
    )


def _weight_based(
    weight: float | None,
    weight_unit: str,
    dose_per_kg: float | None,
    dose_per_kg_unit: str,
    have_dose: float | None,
    have_unit: str,
) -> DosageResult:
    unit_key = normalize_unit(weight_unit or "kg")
    if unit_key not in WEIGHT_TO_KG:
        raise DosageError(f"Weight unit '{weight_unit or '(blank)'}' is not supported. Use kg or lb.")
    kilograms = _require(weight, "patient weight") * WEIGHT_TO_KG[unit_key]
    per_kg = _require(dose_per_kg, "ordered dose per kg")
    mass_name = normalize_unit((dose_per_kg_unit or "mg").split("/")[0])
    if mass_name not in MASS_TO_MG:
        raise DosageError(
            f"Dose unit '{dose_per_kg_unit or '(blank)'}' is not supported. Use mcg, mg, or g."
        )
    total = kilograms * per_kg
    details = [f"Weight in kg: {format_number(kilograms)}."]
    if have_dose is not None:
        total_mg, _ = _to_mg(total, mass_name)
        have_mg, have_name = _to_mg(have_dose, have_unit or mass_name)
        if have_mg == 0:
            raise DosageError("Amount on hand cannot be zero.")
        details.append(
            f"Amount to give from what is on hand: {format_number(total_mg / have_mg)} "
            f"of the {format_number(have_dose)} {have_name} units."
        )
    details.append("Round using your course rule before you write the final answer.")
    return DosageResult(
        formula="weight_based",
        formula_shown="total dose = weight (kg) x ordered dose per kg",
        substitution=f"{format_number(kilograms)} kg x {format_number(per_kg)} {mass_name}/kg",
        value=total,
        unit=mass_name,
        details=details,
    )


def _iv_rate(
    volume_ml: float | None,
    volume_unit: str,
    hours: float | None,
    minutes: float | None,
) -> DosageResult:
    volume = _to_ml(_require(volume_ml, "volume"), volume_unit)
    if hours is not None:
        duration_hours = hours
    elif minutes is not None:
        duration_hours = minutes / 60
    else:
        raise DosageError("Missing hours or minutes. No rate was calculated.")
    if duration_hours == 0:
        raise DosageError("Time cannot be zero.")
    return DosageResult(
        formula="iv_rate",
        formula_shown="mL/hr = volume (mL) / hours",
        substitution=f"{format_number(volume)} mL / {format_number(duration_hours)} hr",
        value=volume / duration_hours,
        unit="mL/hr",
        details=["Round using your course rule before you write the final answer."],
    )


def _drip_rate(
    volume_ml: float | None,
    volume_unit: str,
    drop_factor: float | None,
    hours: float | None,
    minutes: float | None,
) -> DosageResult:
    volume = _to_ml(_require(volume_ml, "volume"), volume_unit)
    factor = _require(drop_factor, "drop factor")
    if minutes is not None:
        duration = minutes
    elif hours is not None:
        duration = hours * 60
    else:
        raise DosageError("Missing minutes or hours. No drip rate was calculated.")
    if duration == 0:
        raise DosageError("Time cannot be zero.")
    return DosageResult(
        formula="drip_rate",
        formula_shown="gtt/min = (volume mL x drop factor) / minutes",
        substitution=f"({format_number(volume)} x {format_number(factor)}) / {format_number(duration)}",
        value=(volume * factor) / duration,
        unit="gtt/min",
        details=["Round using your course rule before you write the final answer."],
    )


def _reconstitution(
    desired_dose: float | None,
    desired_unit: str,
    concentration: float | None,
    concentration_unit: str,
) -> DosageResult:
    desired_mg, desired_name = _to_mg(_require(desired_dose, "ordered dose"), desired_unit or "mg")
    per_ml = _concentration_mg_per_ml(_require(concentration, "concentration"), concentration_unit)
    if per_ml == 0:
        raise DosageError("Concentration cannot be zero.")
    return DosageResult(
        formula="reconstitution",
        formula_shown="mL to draw = ordered dose / concentration",
        substitution=(
            f"{format_number(desired_dose or 0)} {desired_name} / "
            f"{format_number(concentration or 0)} {concentration_unit or 'mg/mL'}"
        ),
        value=desired_mg / per_ml,
        unit="mL",
        details=["Round using your course rule before you write the final answer."],
    )
