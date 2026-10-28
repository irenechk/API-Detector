"""
Model governance for the ZADDP ML pipeline.

Implements:
  - ModelRegistry: versioned model storage with metadata
  - ChampionChallenger: compare model versions in shadow mode
  - DriftDetector: monitor prediction distribution drift
  - ModelCard: generate model documentation for audit/inspectors

Compliance with FRB SR 11-7 / OCC 2011-12:
  - All models are documented, versioned, and auditable
  - Champion/challenger ensures continuous validation
  - Drift monitoring triggers retraining
  - Model cards provide explainability for non-technical reviewers
"""

import json
import math
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field, asdict

from packaging.version import Version, InvalidVersion

logger = logging.getLogger(__name__)


def _version_key(version: str) -> tuple[int, ...]:
    """Sort semver strings numerically instead of lexicographically."""
    try:
        return tuple(Version(version).release)
    except InvalidVersion:
        return (-1,)


# ── Model Registry ──────────────────────────────────────────────────────────

@dataclass
class ModelVersion:
    """Metadata for a single trained model version."""
    version: str                         # semver: "1.0.0", "1.1.0"
    model_type: str                      # "status", "category", "severity", "vulnerability", "risk"
    training_date: str                   # ISO 8601 timestamp
    training_samples: int                # number of samples used
    source_type: str                     # "synthetic", "production", "augmented"
    data_sources: list[str]              # ["synthetic", "cmdb.servicenow", "gateway.apigee"]
    cv_accuracy_mean: Optional[float] = None
    cv_accuracy_std: Optional[float] = None
    train_accuracy: Optional[float] = None
    feature_names: list[str] = field(default_factory=list)
    feature_importance: Optional[list[dict]] = None
    file_hash: Optional[str] = None     # SHA-256 of model pickle
    model_path: Optional[str] = None    # relative path to model file
    status: str = "staging"             # "development", "staging", "champion", "challenger", "deprecated", "archived"
    author: str = "pipeline"
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelVersion":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ModelRegistry:
    """Stores metadata for all trained model versions.

    Registry is stored as a JSON manifest alongside model files.
    In production, this would be a DB table or MLflow tracking server.

    Directory structure:
        models_enhanced/
            registry.json             # All version metadata
            status_model.pkl          # Current production model
            status_encoder.pkl
            archive/
                v1.0.0_status_model.pkl
                v1.0.0_status_encoder.pkl
    """

    def __init__(self, registry_path: Path):
        self.path = registry_path
        self._versions: list[ModelVersion] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self._versions = [ModelVersion.from_dict(v) for v in data.get("versions", [])]
                logger.info("Loaded registry: %d model versions", len(self._versions))
            except Exception as e:
                logger.warning("Failed to load registry: %s", e)
                self._versions = []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"versions": [v.to_dict() for v in self._versions], "updated_at": datetime.utcnow().isoformat()}, f, indent=2, default=str)
        logger.info("Registry saved: %d versions", len(self._versions))

    def register(self, version: ModelVersion):
        existing = [v for v in self._versions if v.version == version.version and v.model_type == version.model_type]
        if existing:
            self._versions.remove(existing[0])
        self._versions.append(version)
        self.save()

    def get_champion(self, model_type: str = "status") -> Optional[ModelVersion]:
        for v in sorted(self._versions, key=lambda x: _version_key(x.version), reverse=True):
            if v.model_type == model_type and v.status == "champion":
                return v
        return None

    def get_challenger(self, model_type: str = "status") -> Optional[ModelVersion]:
        for v in sorted(self._versions, key=lambda x: _version_key(x.version), reverse=True):
            if v.model_type == model_type and v.status == "challenger":
                return v
        return None

    def get_latest(self, model_type: str = "status") -> Optional[ModelVersion]:
        versions = [v for v in self._versions if v.model_type == model_type]
        if not versions:
            return None
        return max(versions, key=lambda v: _version_key(v.version))

    def list_versions(self, model_type: Optional[str] = None) -> list[ModelVersion]:
        if model_type:
            return [v for v in self._versions if v.model_type == model_type]
        return list(self._versions)

    def promote_to_champion(self, version: str, model_type: str = "status"):
        for v in self._versions:
            if v.model_type == model_type and v.status == "champion":
                v.status = "staging"
            if v.version == version and v.model_type == model_type:
                v.status = "champion"
        self.save()

    def archive_old_versions(self, keep_last: int = 3, model_type: str = "status"):
        versions = sorted(
            [v for v in self._versions if v.model_type == model_type],
            key=lambda x: _version_key(x.version), reverse=True
        )
        for v in versions[keep_last:]:
            v.status = "archived"
        self.save()

    @staticmethod
    def compute_file_hash(filepath: Path) -> str:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def default_path() -> Path:
        from app.ml.enhanced_classifier import MODEL_DIR
        return MODEL_DIR / "registry.json"


# ── Champion / Challenger Framework ─────────────────────────────────────────

@dataclass
class ComparisonResult:
    """Result of comparing champion vs challenger on a test set."""
    model_a_version: str
    model_b_version: str
    accuracy_a: float
    accuracy_b: float
    accuracy_delta: float               # b - a (positive = challenger better)
    samples_tested: int
    champion_wins: bool
    metric: str = "accuracy"
    ground_truth_used: bool = False
    confusion_delta: Optional[dict] = None
    promoted: bool = False


class ChampionChallenger:
    """Compare champion vs challenger models in shadow mode.

    Workflow:
      1. New model trained → registered as "challenger"
      2. Both models make predictions on same data (shadow mode)
      3. Compare metrics after sufficient samples
      4. If challenger wins → promote to champion
      5. Archived champion stays in registry
    """

    def __init__(self, registry: ModelRegistry):
        self.registry = registry
        self._challenger_wins: int = 0
        self._champion_wins: int = 0
        self._comparisons: list[ComparisonResult] = []
        self._predictions_a: list[dict] = []  # champion
        self._predictions_b: list[dict] = []  # challenger

    def record_shadow_prediction(
        self,
        champion_result: dict,
        challenger_result: dict,
    ):
        """Record a single shadow-mode prediction from both models."""
        self._predictions_a.append(champion_result)
        self._predictions_b.append(challenger_result)

    def compare(
        self,
        champion_version: str,
        challenger_version: str,
        ground_truth: Optional[list[str]] = None,
    ) -> ComparisonResult:
        """Compare champion vs challenger on collected predictions.

        If ground_truth is provided, compute accuracy.
        Otherwise, compare prediction distributions (label agreement).
        """
        if not self._predictions_a or not self._predictions_b:
            raise ValueError("No shadow predictions collected")

        a_labels = [p.get("status", p.get("category", "")) for p in self._predictions_a]
        b_labels = [p.get("status", p.get("category", "")) for p in self._predictions_b]

        ground_truth_used = bool(ground_truth)
        if ground_truth:
            correct_a = sum(1 for a, t in zip(a_labels, ground_truth) if a == t)
            correct_b = sum(1 for b, t in zip(b_labels, ground_truth) if b == t)
            acc_a = correct_a / max(len(ground_truth), 1)
            acc_b = correct_b / max(len(ground_truth), 1)
        else:
            # No ground truth: only label agreement is observable. Both models
            # receive the same score, so promotion must stay blocked.
            agreement = sum(1 for a, b in zip(a_labels, b_labels) if a == b)
            acc_a = agreement / max(len(a_labels), 1)
            acc_b = acc_a
            self._champion_wins = agreement
            self._challenger_wins = len(a_labels) - agreement

        delta = acc_b - acc_a
        result = ComparisonResult(
            model_a_version=champion_version,
            model_b_version=challenger_version,
            accuracy_a=round(acc_a, 4),
            accuracy_b=round(acc_b, 4),
            accuracy_delta=round(delta, 4),
            samples_tested=len(self._predictions_a),
            champion_wins=delta <= 0,
            ground_truth_used=ground_truth_used,
        )
        self._comparisons.append(result)
        self._predictions_a.clear()
        self._predictions_b.clear()
        return result

    def promote_if_better(
        self,
        challenger_version: str,
        model_type: str = "status",
        min_delta: float = 0.01,
        allow_ungrounded: bool = False,
    ) -> bool:
        """Promote challenger to champion if it outperforms by at least min_delta.

        Promotion requires a ground-truth comparison. Set allow_ungrounded=True
        only for a deliberate manual override.
        """
        champion = self.registry.get_champion(model_type)
        if not champion:
            logger.info("No champion exists, promoting %s directly", challenger_version)
            self.registry.promote_to_champion(challenger_version, model_type)
            return True

        if self._comparisons:
            latest = self._comparisons[-1]
            if not latest.ground_truth_used and not allow_ungrounded:
                logger.warning(
                    "Refusing to promote %s: comparison had no ground truth",
                    challenger_version,
                )
                return False
            if latest.accuracy_delta >= min_delta and not latest.champion_wins:
                logger.info(
                    "Challenger %s outperforms champion %s (Δ=%.4f). Promoting.",
                    challenger_version, champion.version, latest.accuracy_delta
                )
                self.registry.promote_to_champion(challenger_version, model_type)
                latest.promoted = True
                return True
            logger.info(
                "Challenger %s did not beat champion %s (Δ=%.4f)",
                challenger_version, champion.version, latest.accuracy_delta
            )
        return False


# ── Drift Detection ─────────────────────────────────────────────────────────

@dataclass
class DriftReport:
    """Report of prediction distribution drift."""
    metric: str
    baseline_distribution: dict[str, float]
    current_distribution: dict[str, float]
    psi: float                          # Population Stability Index
    chi_square_stat: float
    chi_square_p_value: float
    is_drifted: bool
    threshold: float
    samples_baseline: int
    samples_current: int
    timestamp: str

    def summary(self) -> str:
        direction = "DRIFTED" if self.is_drifted else "stable"
        return (
            f"[{direction}] PSI={self.psi:.4f} (threshold={self.threshold}) | "
            f"baseline={self.samples_baseline} current={self.samples_current} samples | "
            f"p={self.chi_square_p_value:.4f}"
        )


class DriftDetector:
    """Monitor prediction distribution drift using PSI and chi-square.

    Population Stability Index (PSI):
      PSI = Σ (p_i - q_i) * ln(p_i / q_i)
      where p_i = proportion in baseline, q_i = proportion in current

    PSI < 0.1  → no significant shift
    PSI 0.1-0.25 → moderate shift, investigate
    PSI > 0.25 → significant shift, retrain recommended
    """

    def __init__(self, threshold: float = 0.25, monitoring_dir: Optional[Path] = None):
        self.threshold = threshold
        self.monitoring_dir = monitoring_dir
        self._predictions_buffer: list[dict] = []
        self._baseline_distribution: Optional[dict[str, float]] = None
        self._baseline_samples: int = 0

    def set_baseline(self, predictions: list[dict], persist: bool = True):
        """Set baseline distribution from training set predictions."""
        self._baseline_distribution = self._compute_distribution(predictions)
        self._baseline_samples = len(predictions)
        logger.info("Baseline distribution set: %s", self._baseline_distribution)
        if persist and self.monitoring_dir:
            self._write_json("baseline.json", {
                "distribution": self._baseline_distribution,
                "samples": self._baseline_samples,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

    def load_baseline(self) -> bool:
        """Load a persisted baseline, if one exists."""
        if not self.monitoring_dir:
            return False
        path = self.monitoring_dir / "baseline.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            self._baseline_distribution = data["distribution"]
            self._baseline_samples = int(data.get("samples", 0))
            logger.info("Loaded drift baseline from %s", path)
            return True
        except Exception as e:
            logger.warning("Failed to load drift baseline: %s", e)
            return False

    def record_prediction(self, prediction: dict, max_buffer: int = 10000):
        """Record a production prediction for drift monitoring."""
        self._predictions_buffer.append(prediction)
        if len(self._predictions_buffer) > max_buffer:
            self._predictions_buffer = self._predictions_buffer[-max_buffer:]

    def buffered_count(self) -> int:
        return len(self._predictions_buffer)

    def check_drift(self, min_samples: int = 100) -> Optional[DriftReport]:
        """Check if prediction distribution has drifted from baseline.

        Requires at least min_samples collected since last check.
        """
        if self._baseline_distribution is None:
            logger.warning("No baseline set; call set_baseline() first")
            return None

        if len(self._predictions_buffer) < min_samples:
            logger.debug(
                "Not enough samples for drift check: %d/%d",
                len(self._predictions_buffer), min_samples
            )
            return None

        current_dist = self._compute_distribution(self._predictions_buffer)

        # Compute PSI
        all_labels = set(list(self._baseline_distribution.keys()) + list(current_dist.keys()))
        epsilon = 1e-4
        psi = 0.0
        for label in all_labels:
            p = max(self._baseline_distribution.get(label, 0.0), epsilon)
            q = max(current_dist.get(label, 0.0), epsilon)
            psi += (p - q) * math.log(p / q)
        psi = round(psi, 4)

        # Chi-square test
        from scipy.stats import chisquare
        baseline_counts = [
            int(self._baseline_distribution.get(label, 0) * len(self._predictions_buffer))
            for label in sorted(all_labels)
        ]
        current_counts = [
            int(current_dist.get(label, 0) * len(self._predictions_buffer))
            for label in sorted(all_labels)
        ]
        chi2, p_val = chisquare(current_counts, f_exp=baseline_counts) if len(all_labels) > 1 and sum(baseline_counts) > 0 else (0, 1.0)

        is_drifted = psi > self.threshold
        report = DriftReport(
            metric="psi",
            baseline_distribution=self._baseline_distribution,
            current_distribution=current_dist,
            psi=psi,
            chi_square_stat=round(float(chi2), 4),
            chi_square_p_value=round(float(p_val), 4),
            is_drifted=is_drifted,
            threshold=self.threshold,
            samples_baseline=self._baseline_samples,
            samples_current=len(self._predictions_buffer),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if is_drifted:
            logger.warning("Drift detected! %s", report.summary())
        else:
            logger.info("Distribution stable. %s", report.summary())

        if self.monitoring_dir:
            self._append_report(report)
        self._predictions_buffer.clear()
        return report

    def latest_report(self) -> Optional[dict]:
        """Return the most recently persisted drift report."""
        if not self.monitoring_dir:
            return None
        path = self.monitoring_dir / "drift_reports.json"
        if not path.exists():
            return None
        try:
            reports = json.loads(path.read_text())
            return reports[-1] if reports else None
        except Exception:
            return None

    def _write_json(self, filename: str, payload: dict):
        self.monitoring_dir.mkdir(parents=True, exist_ok=True)
        (self.monitoring_dir / filename).write_text(json.dumps(payload, indent=2))

    def _append_report(self, report: "DriftReport", keep_last: int = 100):
        path = self.monitoring_dir / "drift_reports.json"
        reports = []
        if path.exists():
            try:
                reports = json.loads(path.read_text())
            except Exception:
                reports = []
        reports.append(asdict(report))
        self.monitoring_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reports[-keep_last:], indent=2))

    @staticmethod
    def _compute_distribution(predictions: list[dict]) -> dict[str, float]:
        from collections import Counter
        label_key = "status" if "status" in (predictions[0] if predictions else {}) else "category"
        labels = [p.get(label_key, "unknown") for p in predictions]
        counts = Counter(labels)
        total = max(len(labels), 1)
        return {k: round(v / total, 4) for k, v in sorted(counts.items())}


# ── Model Card ──────────────────────────────────────────────────────────────

@dataclass
class ModelCard:
    """Model documentation card for audit / regulator review (FRB SR 11-7).

    Generates a structured report for model risk management.
    """
    model_name: str
    model_version: str
    model_type: str
    owner: str = "Platform Security"
    author: str = "ZADDP ML Pipeline"

    # Model overview
    model_description: str = ""
    intended_use: str = ""
    intended_users: str = ""
    out_of_scope_uses: list[str] = field(default_factory=list)

    # Training data
    training_data_source: str = ""
    training_samples: int = 0
    training_date: str = ""
    feature_list: list[str] = field(default_factory=list)
    target_variable: str = ""

    # Performance
    performance_metrics: dict[str, float] = field(default_factory=dict)
    cv_scores: dict[str, float] = field(default_factory=dict)
    confusion_matrix_summary: str = ""

    # Risks
    known_limitations: list[str] = field(default_factory=list)
    bias_considerations: list[str] = field(default_factory=list)
    operational_risks: list[str] = field(default_factory=list)

    # Governance
    model_risk_tier: str = "Tier 3"     # SR 11-7 tiers: 1 (highest) to 4
    approval_status: str = "pending"
    review_date: str = ""
    version_history: list[str] = field(default_factory=list)

    def render_markdown(self) -> str:
        """Render model card as markdown for documentation."""
        lines = [
            f"# Model Card: {self.model_name} v{self.model_version}",
            "",
            f"**Type:** {self.model_type}  ",
            f"**Owner:** {self.owner}  ",
            f"**Author:** {self.author}  ",
            f"**Model Risk Tier:** {self.model_risk_tier}  ",
            f"**Approval Status:** {self.approval_status}  ",
            "",
            "---",
            "",
            "## 1. Model Overview",
            "",
            f"**Description:** {self.model_description}",
            "",
            f"**Intended Use:** {self.intended_use}",
            "",
            f"**Intended Users:** {self.intended_users}",
            "",
            "**Out of Scope Uses:**",
        ]
        for u in self.out_of_scope_uses:
            lines.append(f"  - {u}")

        lines += [
            "",
            "---",
            "",
            "## 2. Training Data",
            "",
            f"**Source:** {self.training_data_source}",
            f"**Samples:** {self.training_samples}",
            f"**Training Date:** {self.training_date}",
            f"**Target Variable:** {self.target_variable}",
            "",
            "**Features:**",
        ]
        for f in self.feature_list:
            lines.append(f"  - `{f}`")

        lines += [
            "",
            "---",
            "",
            "## 3. Performance",
            "",
        ]
        for k, v in self.performance_metrics.items():
            lines.append(f"- **{k}:** {v}")
        if self.cv_scores:
            lines.append("")
            lines.append("**Cross-Validation:**")
            for k, v in self.cv_scores.items():
                lines.append(f"  - {k}: {v}")

        lines += [
            "",
            "---",
            "",
            "## 4. Risks & Limitations",
            "",
            "**Known Limitations:**",
        ]
        for l in self.known_limitations:
            lines.append(f"  - {l}")
        lines.append("")
        lines.append("**Bias Considerations:**")
        for b in self.bias_considerations:
            lines.append(f"  - {b}")
        lines.append("")
        lines.append("**Operational Risks:**")
        for r in self.operational_risks:
            lines.append(f"  - {r}")

        lines += [
            "",
            "---",
            "",
            "## 5. Governance",
            "",
            f"**Model Risk Tier:** {self.model_risk_tier}",
            f"**Approval Status:** {self.approval_status}",
            f"**Review Date:** {self.review_date}",
            "",
            "**Version History:**",
        ]
        for vh in self.version_history:
            lines.append(f"  - {vh}")

        return "\n".join(lines)

    def render_json(self) -> dict:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_model_version(
        cls,
        version: ModelVersion,
        feature_list: Optional[list[str]] = None,
    ) -> "ModelCard":
        """Auto-generate a ModelCard from a ModelVersion."""
        return cls(
            model_name=f"ZADDP {version.model_type.replace('_', ' ').title()} Classifier",
            model_version=version.version,
            model_type=version.model_type,
            training_data_source=version.source_type,
            training_samples=version.training_samples,
            training_date=version.training_date,
            feature_list=feature_list or version.feature_names,
            target_variable=version.model_type,
            cv_scores={
                "cv_accuracy_mean": version.cv_accuracy_mean or 0,
                "cv_accuracy_std": version.cv_accuracy_std or 0,
            } if version.cv_accuracy_mean else {},
            performance_metrics={
                "train_accuracy": version.train_accuracy or 0,
            } if version.train_accuracy else {},
            version_history=[f"{version.version} - {version.training_date} ({version.status})"],
        )


# ── Singleton ───────────────────────────────────────────────────────────────

_registry: Optional[ModelRegistry] = None
_drift_detector: Optional[DriftDetector] = None


def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry(ModelRegistry.default_path())
    return _registry


def get_drift_detector(threshold: float = 0.25) -> DriftDetector:
    """Return the process-wide drift detector with a persisted baseline."""
    global _drift_detector
    if _drift_detector is None:
        from app.ml.enhanced_classifier import MODEL_DIR
        detector = DriftDetector(
            threshold=threshold,
            monitoring_dir=MODEL_DIR.parent / "monitoring",
        )
        detector.load_baseline()
        _drift_detector = detector
    return _drift_detector


def record_audit_event(action: str, actor: str, details: Optional[dict] = None):
    """Append a governance action to the local audit log."""
    from app.ml.enhanced_classifier import MODEL_DIR

    monitoring_dir = MODEL_DIR.parent / "monitoring"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor,
        "details": details or {},
    }
    with open(monitoring_dir / "audit.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def generate_model_card(
    model_type: str = "status",
    version: Optional[str] = None,
) -> str:
    """Generate a model card markdown document for a given model type/version."""
    registry = get_model_registry()
    mv = None
    if version:
        for v in registry.list_versions(model_type):
            if v.version == version:
                mv = v
                break
    else:
        mv = registry.get_champion(model_type) or registry.get_latest(model_type)

    if not mv:
        return "# No model registered\n\nRun training first."

    card = ModelCard.from_model_version(mv)
    card.intended_use = "Classify API lifecycle status for decommission pipeline prioritization"
    card.intended_users = "API Security Team, Platform Engineering, Compliance"
    card.out_of_scope_uses = [
        "Determining actual decommission (always requires human approval)",
        "Security incident response (use dedicated security tooling)",
        "Credit or fraud risk decisions",
    ]
    card.known_limitations = [
        "Shadow APIs are difficult to distinguish from low-traffic active APIs",
        "Model requires at least 7 days of traffic data for reliable predictions",
        "New APIs with no traffic history default to 'active'",
        "Training labels are rule-derived; endpoint classifiers learn the labeling rules",
        "Training data is synthetic (or synthetic-augmented), not production traffic",
        "Output probabilities are uncalibrated (no CalibratedClassifierCV)",
        "No production gateway, CMDB, or scanner source was used for this artifact",
    ]
    card.bias_considerations = [
        "Older APIs may be over-represented in training data",
        "Ownerless APIs strongly correlate with shadow/zombie predictions",
        "Synthetic status priors (active 50%) do not reflect the real portfolio mix",
    ]
    card.operational_risks = [
        "False positives (flagging active APIs as zombie) cause unnecessary investigation",
        "False negatives (missing zombie APIs) increase security surface area",
        "Model should not be the sole decision maker for decommission actions",
        "Drift monitoring requires production predictions to be recorded over time",
    ]
    card.model_risk_tier = "Tier 3"
    card.approval_status = "pending"
    card.review_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return card.render_markdown()


def next_version(model_type: str, bump: str = "minor") -> str:
    """Return the next semver for a model type."""
    latest = get_model_registry().get_latest(model_type)
    if not latest:
        return "1.0.0"
    parsed = _version_key(latest.version)
    if parsed == (-1,):
        return "1.0.0"
    release = list(parsed[:3])
    while len(release) < 3:
        release.append(0)
    major, minor, patch = release
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor + 1}.0"


def register_trained_model(
    model_version: str,
    model_type: str,
    training_samples: int,
    source_type: str,
    data_sources: list[str],
    cv_scores: Optional[dict] = None,
    train_accuracy: Optional[float] = None,
    feature_names: Optional[list[str]] = None,
    file_hash: Optional[str] = None,
    author: str = "pipeline",
    notes: str = "",
) -> ModelVersion:
    """Register a newly trained model in the registry."""
    registry = get_model_registry()
    cv_mean = None
    cv_std = None
    if cv_scores:
        for key in ("status_cv_accuracy", "category_cv_accuracy"):
            if f"{key}_mean" in cv_scores:
                cv_mean = cv_scores[f"{key}_mean"]
                cv_std = cv_scores.get(f"{key}_std")
                break

    version = ModelVersion(
        version=model_version,
        model_type=model_type,
        training_date=datetime.now(timezone.utc).isoformat(),
        training_samples=training_samples,
        source_type=source_type,
        data_sources=data_sources,
        cv_accuracy_mean=cv_mean,
        cv_accuracy_std=cv_std,
        train_accuracy=train_accuracy,
        feature_names=feature_names or [],
        file_hash=file_hash,
        status="champion" if registry.get_champion(model_type) is None else "challenger",
        author=author,
        notes=notes,
    )
    registry.register(version)
    record_audit_event(
        "register_model",
        author,
        {"model_type": model_type, "version": model_version, "status": version.status},
    )
    logger.info("Registered model: %s v%s (%s)", model_type, model_version, version.status)
    return version
