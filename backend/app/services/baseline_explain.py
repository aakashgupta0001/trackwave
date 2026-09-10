"""Deterministic BASELINE explanations (Phase 7) — no SHAP required.

The baseline engine already publishes, per station, the provenance of its calculation
(EtaCalculationDetails: speed/running-time source, distance source, delay input,
recovery applied, halt). This module turns those into user-facing factors so that even
in baseline-only mode (no ML model) the ETA answer includes "why". Fully deterministic
and traceable to the baseline engine's own numbers — nothing is invented here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.eta import EtaCalculationDetails


@dataclass
class BaselineFactor:
    factor: str
    display_name: str
    effect: str  # LATER / EARLIER / NEUTRAL
    value: float | None = None

    def as_dict(self) -> dict:
        payload = {"factor": self.factor, "display_name": self.display_name, "effect": self.effect}
        if self.value is not None:
            payload["value"] = self.value
        return payload


def baseline_factors(details: EtaCalculationDetails | None) -> list[BaselineFactor]:
    """Translate the baseline engine's per-station calculation metadata into factors.

    Effects are read directly off the engine's own arithmetic:
    - CURRENT_DELAY: LATER when the delay input is positive, else NEUTRAL.
    - DELAY_RECOVERY: EARLIER when recovery was applied, else NEUTRAL.
    - SECTION_RUNNING_TIME: which data quality tier fed the estimate.
    - STATION_HALT: NEUTRAL by definition (scheduled dwell, always included).
    - SECTION_DATA: known railway section vs approximated distance.
    """
    if details is None:
        return []

    factors: list[BaselineFactor] = []

    delay_input = details.delay_input_minutes
    if delay_input is not None:
        factors.append(
            BaselineFactor(
                factor="CURRENT_DELAY",
                display_name="Current train delay",
                effect="LATER" if delay_input > 0 else "NEUTRAL",
                value=delay_input,
            )
        )

    recovery = details.recovery_applied_minutes
    if recovery is not None and recovery > 0:
        factors.append(
            BaselineFactor(
                factor="DELAY_RECOVERY",
                display_name="Expected delay recovery",
                effect="EARLIER",
                value=recovery,
            )
        )

    if details.speed_source:
        factors.append(
            BaselineFactor(
                factor="SECTION_RUNNING_TIME",
                display_name="Expected section travel time",
                effect="NEUTRAL",
            )
        )

    if details.estimated_halt_minutes:
        factors.append(
            BaselineFactor(
                factor="STATION_HALT",
                display_name="Scheduled station halt",
                effect="NEUTRAL",
                value=details.estimated_halt_minutes,
            )
        )

    distance_source = details.distance_source or ""
    if distance_source in ("RAILWAY_SECTION", "ROUTE_DISTANCE_METADATA"):
        factors.append(BaselineFactor(factor="SECTION_DATA", display_name="Known railway section data", effect="NEUTRAL"))
    elif distance_source in ("GEOGRAPHIC_APPROXIMATION", "UNAVAILABLE"):
        factors.append(BaselineFactor(factor="SECTION_DATA", display_name="Approximated section distance", effect="NEUTRAL"))

    return factors
