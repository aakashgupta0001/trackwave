"""Lightweight filesystem model registry with lifecycle management, quality gates, and rollback (Phase 6 & 10).

Layout (ML_MODEL_DIR defaults to ./models):

    {ML_MODEL_DIR}/eta_residual/
        active_model.json      — pointer to currently promoted production model
        {version}/
            model.json          — trained XGBoost booster
            feature_schema.json — FEATURE_COLUMNS + categorical vocabularies
            metadata.json       — version, training timestamp, dataset info, metrics, status
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.ml.exceptions import ModelUnavailableError
from app.ml.features import CategoricalEncoder, FEATURE_COLUMNS

logger = logging.getLogger(__name__)

MODEL_FAMILY = "eta_residual"
MODEL_VERSION = "xgb-residual-v1"


@dataclass
class LoadedModel:
    version: str
    booster: object  # xgboost.Booster
    feature_columns: list[str]
    encoder: CategoricalEncoder
    metadata: dict = field(default_factory=dict)


class ModelRegistry:
    def __init__(self, root_dir: str | Path | None = None) -> None:
        root = root_dir or get_settings().ML_MODEL_DIR
        self.root = Path(root) / MODEL_FAMILY

    def model_dir(self, version: str) -> Path:
        return self.root / version

    @property
    def pointer_file(self) -> Path:
        return self.root / "active_model.json"

    def list_versions(self) -> list[str]:
        if not self.root.exists():
            return []
        versions = []
        for path in self.root.iterdir():
            if path.is_dir() and (path / "metadata.json").exists() and (path / "model.json").exists():
                versions.append(path.name)
        return sorted(versions)

    def get_metadata(self, version: str) -> dict[str, Any]:
        """Read metadata.json for a version, or return empty dict if missing."""
        path = self.model_dir(version) / "metadata.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    def update_metadata(self, version: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge updates into metadata.json and write back."""
        directory = self.model_dir(version)
        path = directory / "metadata.json"
        current = self.get_metadata(version)
        merged = {**current, **updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(merged, indent=2, default=str))
        return merged

    def register(
        self,
        version: str,
        booster,
        encoder: CategoricalEncoder,
        metadata: dict,
        status: str = "CANDIDATE",
    ) -> Path:
        """Persist a trained model + its exact feature preprocessing + metadata."""
        directory = self.model_dir(version)
        directory.mkdir(parents=True, exist_ok=True)

        booster.save_model(str(directory / "model.json"))

        schema = {
            "feature_columns": FEATURE_COLUMNS,
            "categorical_vocabularies": encoder.to_dict(),
        }
        (directory / "feature_schema.json").write_text(json.dumps(schema, indent=2))

        metadata = {
            **metadata,
            "version": version,
            "status": status,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
        logger.info("Registered model version=%s [status=%s] at %s", version, status, directory)
        return directory

    def load(self, version: str | None = None) -> LoadedModel:
        """Load a specific version, the configured active version, or the latest

        trained one. Raises ModelUnavailableError on any failure — never returns a
        half-loaded model.
        """
        import xgboost as xgb

        version = version or self.active_version()
        if version is None:
            raise ModelUnavailableError("No trained model available in the registry")

        directory = self.model_dir(version)
        model_path = directory / "model.json"
        schema_path = directory / "feature_schema.json"
        metadata_path = directory / "metadata.json"
        if not (model_path.exists() and schema_path.exists() and metadata_path.exists()):
            raise ModelUnavailableError(f"Model {version} is incomplete in the registry")

        try:
            booster = xgb.Booster()
            booster.load_model(str(model_path))
            schema = json.loads(schema_path.read_text())
            metadata = json.loads(metadata_path.read_text())
            encoder = CategoricalEncoder.from_dict(schema["categorical_vocabularies"])
            columns = schema["feature_columns"]
        except Exception as exc:
            raise ModelUnavailableError(f"Failed to load model {version}: {exc}") from exc

        return LoadedModel(
            version=version,
            booster=booster,
            feature_columns=columns,
            encoder=encoder,
            metadata=metadata,
        )

    def active_version(self) -> str | None:
        """The currently active/promoted model version."""
        settings = get_settings()

        # 1. Check explicit active pointer file (set via promote/rollback)
        if self.pointer_file.exists():
            try:
                data = json.loads(self.pointer_file.read_text())
                ver = data.get("active_version")
                if ver and self.model_dir(ver).exists():
                    return ver
            except Exception:
                pass

        # 2. Check settings override
        if settings.ML_MODEL_VERSION:
            return settings.ML_MODEL_VERSION

        # 3. Check versions marked with status == "PRODUCTION"
        for ver in self.list_versions():
            meta = self.get_metadata(ver)
            if meta.get("status") == "PRODUCTION":
                return ver

        # 4. Fallback to newest trained version by timestamp
        versions = self.list_versions()
        if not versions:
            return None

        def trained_at(version: str) -> datetime:
            try:
                meta = self.get_metadata(version)
                return datetime.fromisoformat(str(meta.get("training_timestamp", "")))
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)

        return max(versions, key=trained_at)

    def list_models(self) -> list[dict[str, Any]]:
        """List all models in the registry with their metadata, metrics, and lifecycle status."""
        results = []
        active_ver = self.active_version()

        for ver in self.list_versions():
            meta = self.get_metadata(ver)
            test_m = meta.get("test_metrics", {})
            ml_m = test_m.get("ml", {})
            base_m = test_m.get("baseline", {})
            comp = meta.get("comparison", {})
            unc = meta.get("uncertainty", {})

            status = meta.get("status")
            if not status:
                status = "PRODUCTION" if ver == active_ver else "CANDIDATE"

            results.append(
                {
                    "model_version": ver,
                    "status": status,
                    "is_active": ver == active_ver,
                    "training_timestamp": meta.get("training_timestamp"),
                    "dataset_version": meta.get("dataset_version", "dataset-v1"),
                    "feature_schema_version": meta.get("feature_schema_version", "features-v1"),
                    "test_mae": float(ml_m.get("mae_minutes", 0.0)) if "mae_minutes" in ml_m else None,
                    "baseline_mae": float(base_m.get("mae_minutes", 0.0)) if "mae_minutes" in base_m else None,
                    "improvement_percent": float(comp.get("improvement_percent", 0.0)) if "improvement_percent" in comp else None,
                    "uncertainty_level": float(unc.get("interval_level", 0.8)) if "interval_level" in unc else None,
                    "artifact_path": str(self.model_dir(ver)),
                }
            )
        return results

    def validate_candidate(self, candidate_version: str) -> tuple[bool, str, dict[str, Any]]:
        """Evaluate candidate model against strict production Quality Gate.

        Criteria:
        1. Model exists in registry.
        2. Candidate MAE < Baseline Engine MAE.
        3. Candidate MAE < Active Model MAE (if active model exists and is different).
        4. Relative improvement >= MODEL_MIN_IMPROVEMENT_PERCENT.
        5. Test samples >= MIN_EVALUATION_SAMPLES.
        """
        settings = get_settings()
        if candidate_version not in self.list_versions():
            return False, f"Candidate model {candidate_version} not found in registry", {}

        meta = self.get_metadata(candidate_version)
        test_m = meta.get("test_metrics", {})
        ml_m = test_m.get("ml", {})
        base_m = test_m.get("baseline", {})

        if not ml_m or "mae_minutes" not in ml_m:
            return False, "Candidate model has no evaluated test metrics", {}

        cand_mae = float(ml_m.get("mae_minutes", 999.0))
        cand_samples = int(ml_m.get("count", 0))
        base_mae = float(base_m.get("mae_minutes", 999.0)) if base_m else 999.0

        if cand_samples < settings.MIN_EVALUATION_SAMPLES:
            return False, f"Insufficient test samples ({cand_samples} < {settings.MIN_EVALUATION_SAMPLES})", {}

        if cand_mae >= base_mae:
            return False, f"Candidate MAE ({cand_mae}) does not improve upon baseline MAE ({base_mae})", {}

        imprv_pct = ((base_mae - cand_mae) / base_mae) * 100.0 if base_mae > 0 else 0.0
        if imprv_pct < settings.MODEL_MIN_IMPROVEMENT_PERCENT:
            return False, f"Improvement vs baseline ({imprv_pct:.2f}%) is below minimum threshold ({settings.MODEL_MIN_IMPROVEMENT_PERCENT}%)", {}

        # Compare against currently active model if different
        active_ver = self.active_version()
        if active_ver and active_ver != candidate_version:
            active_meta = self.get_metadata(active_ver)
            active_ml_m = active_meta.get("test_metrics", {}).get("ml", {})
            active_mae = float(active_ml_m.get("mae_minutes", 999.0)) if active_ml_m else 999.0

            if cand_mae > active_mae:
                return False, f"Candidate MAE ({cand_mae}) is worse than active model {active_ver} MAE ({active_mae})", {}

        details = {
            "candidate_version": candidate_version,
            "candidate_mae": cand_mae,
            "baseline_mae": base_mae,
            "improvement_percent": round(imprv_pct, 2),
            "test_samples": cand_samples,
        }
        return True, "Passed all quality gate validation criteria", details

    def promote_model(
        self, candidate_version: str, actor: str = "admin", reason: str | None = None, force: bool = False
    ) -> tuple[bool, str]:
        """Safely promote candidate model to PRODUCTION following Quality Gate validation."""
        if candidate_version not in self.list_versions():
            return False, f"Model version {candidate_version} does not exist in registry"

        if not force:
            passed, reason_msg, details = self.validate_candidate(candidate_version)
            if not passed:
                self.update_metadata(candidate_version, {"status": "REJECTED", "rejection_reason": reason_msg})
                logger.warning("Quality gate REJECTED model %s: %s", candidate_version, reason_msg)
                return False, f"Quality gate rejection: {reason_msg}"

        previous_active = self.active_version()

        # Archive previous active model
        if previous_active and previous_active != candidate_version:
            self.update_metadata(previous_active, {"status": "ARCHIVED"})

        # Promote candidate
        self.update_metadata(
            candidate_version,
            {
                "status": "PRODUCTION",
                "promoted_at": datetime.now(timezone.utc).isoformat(),
                "promoted_by": actor,
                "promotion_reason": reason or "Passed quality gate evaluation",
            },
        )

        # Write active pointer
        pointer_data = {
            "active_version": candidate_version,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "promoted_by": actor,
            "previous_version": previous_active,
        }
        self.pointer_file.write_text(json.dumps(pointer_data, indent=2))

        # Reload live predictor
        from app.ml.predictor import ml_predictor
        ml_predictor.reload()

        logger.info(
            "Model %s PROMOTED to PRODUCTION by %s (previous=%s)",
            candidate_version,
            actor,
            previous_active,
        )
        return True, f"Model {candidate_version} successfully promoted to PRODUCTION"

    def rollback_model(
        self, target_version: str, actor: str = "admin", reason: str | None = None
    ) -> tuple[bool, str]:
        """Rollback active production model to an explicit previous version."""
        if target_version not in self.list_versions():
            return False, f"Target version {target_version} does not exist in registry"

        current_active = self.active_version()
        if current_active == target_version:
            return False, f"Model {target_version} is already the active production model"

        # Demote current
        if current_active:
            self.update_metadata(current_active, {"status": "ARCHIVED"})

        # Restore target
        self.update_metadata(
            target_version,
            {
                "status": "PRODUCTION",
                "rolled_back_at": datetime.now(timezone.utc).isoformat(),
                "rolled_back_by": actor,
                "rollback_reason": reason or "Administrative rollback",
            },
        )

        pointer_data = {
            "active_version": target_version,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "promoted_by": actor,
            "previous_version": current_active,
            "is_rollback": True,
        }
        self.pointer_file.write_text(json.dumps(pointer_data, indent=2))

        from app.ml.predictor import ml_predictor
        ml_predictor.reload()

        logger.info(
            "Model ROLLED BACK to %s by %s (previous=%s)",
            target_version,
            actor,
            current_active,
        )
        return True, f"Successfully rolled back active model to {target_version}"


# Shared singleton registry
model_registry = ModelRegistry()
