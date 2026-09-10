"""ML-layer exceptions. All are caught by the fusion layer and trigger a clean
fallback to the baseline ETA — never an invented ML value."""


class ModelUnavailableError(Exception):
    """No trained model is available (disabled, not trained yet, or unreadable)."""


class ModelPredictionError(Exception):
    """A loaded model failed at inference time (invalid features, runtime error)."""
