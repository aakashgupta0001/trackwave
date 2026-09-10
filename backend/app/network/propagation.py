"""Delay propagation model (modules 8-10, 47).

`NetworkPropagationModel` is the interface; `DeterministicPropagationModel` is the only
implementation for now — a transparent, configurable formula, not a GNN. Swapping in a
learned model later (gradient boosting, temporal GNN, ...) means implementing this same
interface and changing which instance `app/network/impact.py` constructs; nothing about
the graph, conflict detection, or API layer needs to change.

    propagated_delay = source_delay × overlap_factor × decay^depth

- `overlap_factor` captures "how exposed is this train to the delay right now": strong
  when the two trains' windows actually overlap, weaker (and confidence-downgraded) when
  they're merely scheduled close together, zero otherwise (module 9).
- `decay^depth` makes delay weaker the further it propagates (module 10) — depth 0 is a
  direct effect on an immediately-conflicting train, depth 1 is that train's own
  downstream trains, and so on up to NETWORK_MAX_PROPAGATION_DEPTH.

These are RAILCAST model assumptions for a first deterministic version, not measured
railway operating statistics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.network.schemas import ConfidenceLevel, PropagationResult

# An overlap at or beyond this many minutes is treated as "full" exposure (factor 1.0) —
# a RAILCAST modeling choice, not a measured railway constant.
_FULL_OVERLAP_MINUTES = 20.0
# Scheduled-separation conflicts propagate at most this fraction as strongly as an actual
# overlap of the same size would, reflecting their lower certainty.
_SEPARATION_WEIGHT = 0.4


class NetworkPropagationModel(ABC):
    @abstractmethod
    def propagate(
        self,
        *,
        source_delay_minutes: float,
        overlap_minutes: float,
        separation_minutes: float,
        depth: int,
    ) -> PropagationResult | None:
        """Return the estimated propagated delay for one hop, or None when nothing
        should propagate (no overlap and ample separation, depth exceeded, or the result
        would fall below the configured minimum).
        """


class DeterministicPropagationModel(NetworkPropagationModel):
    def __init__(self) -> None:
        self._settings = get_settings()

    def _overlap_factor(self, overlap_minutes: float, separation_minutes: float) -> tuple[float, ConfidenceLevel]:
        if overlap_minutes > 0:
            factor = min(1.0, overlap_minutes / _FULL_OVERLAP_MINUTES)
            confidence = (
                ConfidenceLevel.HIGH if factor >= 0.66 else ConfidenceLevel.MEDIUM if factor >= 0.33 else ConfidenceLevel.LOW
            )
            return factor, confidence

        buffer = self._settings.NETWORK_MIN_SAFE_SEPARATION_MINUTES
        if separation_minutes < buffer:
            # Linearly shrinks from _SEPARATION_WEIGHT (separation=0) to 0 (separation=buffer).
            closeness = 1.0 - (separation_minutes / buffer)
            return closeness * _SEPARATION_WEIGHT, ConfidenceLevel.LOW

        return 0.0, ConfidenceLevel.LOW

    def propagate(
        self,
        *,
        source_delay_minutes: float,
        overlap_minutes: float,
        separation_minutes: float,
        depth: int,
    ) -> PropagationResult | None:
        settings = self._settings
        if depth > settings.NETWORK_MAX_PROPAGATION_DEPTH:
            return None
        if source_delay_minutes <= 0:
            return None

        factor, confidence = self._overlap_factor(overlap_minutes, separation_minutes)
        if factor <= 0:
            return None

        decay = settings.NETWORK_PROPAGATION_DECAY**depth
        estimated = source_delay_minutes * factor * decay
        if estimated < settings.NETWORK_MIN_PROPAGATED_DELAY_MINUTES:
            return None

        return PropagationResult(
            estimated_delay_minutes=round(estimated, 1),
            propagation_factor=round(factor * decay, 4),
            confidence=confidence,
            depth=depth,
        )
