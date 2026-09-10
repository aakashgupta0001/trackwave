"""Pure unit tests for the deterministic delay-propagation model (Phase 8, module 40).
No database needed — DeterministicPropagationModel is a pure function of its inputs.
"""

from app.core.config import get_settings
from app.network.propagation import DeterministicPropagationModel
from app.network.schemas import ConfidenceLevel


def _model() -> DeterministicPropagationModel:
    return DeterministicPropagationModel()


def test_source_delay_propagates_when_overlap_exists() -> None:
    result = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=0)
    assert result is not None
    assert result.estimated_delay_minutes > 0
    assert result.depth == 0


def test_stronger_overlap_propagates_more_delay() -> None:
    weak = _model().propagate(source_delay_minutes=20.0, overlap_minutes=2.0, separation_minutes=0.0, depth=0)
    strong = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=0)
    assert weak is not None and strong is not None
    assert strong.estimated_delay_minutes > weak.estimated_delay_minutes


def test_no_overlap_and_ample_separation_yields_no_propagation() -> None:
    settings = get_settings()
    result = _model().propagate(
        source_delay_minutes=20.0, overlap_minutes=0.0,
        separation_minutes=settings.NETWORK_MIN_SAFE_SEPARATION_MINUTES * 5, depth=0,
    )
    assert result is None


def test_small_separation_propagates_weakly() -> None:
    result = _model().propagate(source_delay_minutes=20.0, overlap_minutes=0.0, separation_minutes=1.0, depth=0)
    assert result is not None
    assert result.confidence == ConfidenceLevel.LOW


def test_propagation_decay_reduces_delay_with_depth() -> None:
    depth0 = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=0)
    depth1 = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=1)
    depth2 = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=2)
    assert depth0 is not None and depth1 is not None and depth2 is not None
    assert depth0.estimated_delay_minutes > depth1.estimated_delay_minutes > depth2.estimated_delay_minutes


def test_propagation_stops_beyond_max_depth() -> None:
    settings = get_settings()
    result = _model().propagate(
        source_delay_minutes=100.0, overlap_minutes=20.0, separation_minutes=0.0,
        depth=settings.NETWORK_MAX_PROPAGATION_DEPTH + 1,
    )
    assert result is None


def test_propagation_stops_below_minimum_delay_threshold() -> None:
    # A tiny source delay with weak exposure should fall below the configured floor.
    result = _model().propagate(source_delay_minutes=1.0, overlap_minutes=1.0, separation_minutes=0.0, depth=0)
    assert result is None


def test_no_delay_never_propagates() -> None:
    result = _model().propagate(source_delay_minutes=0.0, overlap_minutes=20.0, separation_minutes=0.0, depth=0)
    assert result is None


def test_high_overlap_yields_high_confidence() -> None:
    result = _model().propagate(source_delay_minutes=30.0, overlap_minutes=25.0, separation_minutes=0.0, depth=0)
    assert result is not None
    assert result.confidence == ConfidenceLevel.HIGH


def test_propagation_factor_is_reported() -> None:
    result = _model().propagate(source_delay_minutes=20.0, overlap_minutes=20.0, separation_minutes=0.0, depth=0)
    assert result is not None
    assert 0.0 < result.propagation_factor <= 1.0
