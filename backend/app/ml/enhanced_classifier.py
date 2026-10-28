"""
Enhanced ML classifier for API endpoints.

Improvements over the original APIClassifier:
  - Multi-output architecture (single model predicts category + severity jointly)
  - Gradient Boosting (GradientBoostingClassifier/Regressor)
  - Richer feature engineering (path structure, method encoding, keyword density)
  - Stratified cross-validation during training (probabilities are uncalibrated)
  - Feature importance extraction for explainability
  - Chain classifier for vulnerability multi-label prediction
"""

import os
import re
import json
import random
import pickle
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from typing import Optional, Any
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.multioutput import MultiOutputClassifier
from sklearn.multiclass import OneVsRestClassifier
from sklearn.multioutput import RegressorChain
from sklearn.preprocessing import LabelEncoder, MultiLabelBinarizer, StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, accuracy_score, mean_absolute_error

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models_enhanced"
MODEL_DIR.mkdir(exist_ok=True)

VULN_TYPES = [
    "Exposed Admin Interface",
    "Sensitive Data Exposure",
    "Insecure Direct Object Reference (IDOR)",
    "Authentication Bypass",
    "Mass Assignment / API Abuse",
    "Missing Rate Limiting",
    "GraphQL Introspection Enabled",
    "API Documentation Leakage",
    "File Operation Abuse",
    "CORS Misconfiguration",
    "Information Disclosure",
]

SEVERITY_LEVELS = ["low", "medium", "high", "critical"]

API_CATEGORIES = [
    "authentication", "user_management", "data_crud", "admin",
    "system_health", "file_operations", "configuration", "reporting",
    "notifications", "search", "messaging", "payment", "analytics",
    "integration", "unknown",
]


# ── Enhanced Feature Engineering ────────────────────────────────────────────

# Keyword groups for structural features
ADMIN_KEYWORDS = ["admin", "internal", "debug", "console", "manager"]
SENSITIVE_KEYWORDS = ["user", "account", "customer", "profile", "config", "env",
                      "secret", "token", "key", "credential", "password", "db", "database"]
AUTH_KEYWORDS = ["login", "auth", "oauth", "signin", "logout", "register", "token",
                 "saml", "callback", "mfa", "otp", "verify", "reset", "forgot"]
CRUD_KEYWORDS = ["create", "update", "edit", "delete", "save", "add", "remove",
                 "modify", "bulk", "batch", "import", "export"]
FILE_KEYWORDS = ["file", "upload", "download", "document", "attachment", "media", "image"]
HEALTH_KEYWORDS = ["health", "status", "metrics", "healthz", "readyz", "ping", "version"]
DOC_KEYWORDS = ["swagger", "openapi", "docs", "redoc", "api-docs"]
PAYMENT_KEYWORDS = ["pay", "payment", "checkout", "invoice", "billing", "subscription",
                    "pricing", "wallet", "transaction"]


def _extract_structural_features(path: str, method: str) -> dict:
    """Extract rich structural features from an endpoint path."""
    path_lower = path.lower()
    segments = [s for s in path_lower.split("/") if s]
    features = {}

    # Path structure
    features["depth"] = len(segments)
    features["path_length"] = len(path)
    features["num_segments"] = len(segments)
    features["avg_segment_length"] = np.mean([len(s) for s in segments]) if segments else 0

    # Numeric patterns
    features["has_numeric_id"] = int(bool(re.search(r"/\d{4,}", path)))
    features["has_uuid"] = int(bool(re.search(
        r"/[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}", path_lower
    )))
    features["has_version_prefix"] = int(bool(re.search(r"/v\d+/", path_lower)))
    features["has_api_prefix"] = int(bool(re.search(r"/api/", path_lower)))

    # HTTP method encoding
    for m in ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]:
        features[f"method_{m}"] = int(method.upper() == m)

    # Keyword density per group
    all_words = set(segments)
    features["admin_kw_count"] = sum(1 for kw in ADMIN_KEYWORDS if kw in all_words)
    features["sensitive_kw_count"] = sum(1 for kw in SENSITIVE_KEYWORDS if kw in all_words)
    features["auth_kw_count"] = sum(1 for kw in AUTH_KEYWORDS if kw in all_words)
    features["crud_kw_count"] = sum(1 for kw in CRUD_KEYWORDS if kw in all_words)
    features["file_kw_count"] = sum(1 for kw in FILE_KEYWORDS if kw in all_words)
    features["health_kw_count"] = sum(1 for kw in HEALTH_KEYWORDS if kw in all_words)
    features["doc_kw_count"] = sum(1 for kw in DOC_KEYWORDS if kw in all_words)
    features["payment_kw_count"] = sum(1 for kw in PAYMENT_KEYWORDS if kw in all_words)

    # Segment structure pattern (type of each segment)
    struct_pattern = []
    for seg in segments:
        if re.match(r"^\d+$", seg):
            struct_pattern.append("N")
        elif re.match(r"^[a-f0-9-]{36}$", seg):
            struct_pattern.append("U")
        else:
            struct_pattern.append("S")
    features["struct_pattern"] = ",".join(struct_pattern)
    features["num_numeric_segments"] = struct_pattern.count("N")
    features["num_uuid_segments"] = struct_pattern.count("U")
    features["ratio_numeric"] = struct_pattern.count("N") / max(len(struct_pattern), 1)

    return features


def _build_text_representation(path: str, method: str) -> str:
    """Build a rich text representation for TF-IDF, including structural hints."""
    path_lower = path.lower()
    tokens = []

    for part in re.split(r"[/\-_.#?=&]", path_lower):
        part = part.strip()
        if part and not re.match(r"^\d+$", part):
            tokens.append(part)

    segments = [s for s in path_lower.split("/") if s]
    for i in range(len(segments) - 1):
        tokens.append(f"bigram_{segments[i]}_{segments[i+1]}")
    for i in range(len(segments) - 2):
        tokens.append(f"trigram_{segments[i]}_{segments[i+1]}_{segments[i+2]}")

    tokens.append(f"depth_{len(segments)}")

    if segments:
        tokens.append(f"first_seg_{segments[0]}")
        tokens.append(f"last_seg_{segments[-1]}")

    tokens.append(f"method_{method.upper()}")

    return " ".join(tokens)


def prepare_features(paths: list[str], methods: list[str]) -> tuple[list[str], list[dict]]:
    """Convert raw endpoint data into text + structural features."""
    text_features = [_build_text_representation(p, m) for p, m in zip(paths, methods)]
    struct_features = [_extract_structural_features(p, m) for p, m in zip(paths, methods)]
    return text_features, struct_features


# ── Enhanced Classifier ─────────────────────────────────────────────────────

class EnhancedAPIClassifier:
    """Enhanced multi-model classifier with multi-output architecture,
    gradient boosting, and explainability.

    Probabilities are raw model scores, not calibrated estimates.
    """

    def __init__(self):
        # Vectorizer
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.structural_feature_names: list[str] = []

        # Multi-output category + severity model
        self.joint_classifier: Optional[MultiOutputClassifier] = None
        self.joint_encoder: Optional[MultiOutputEncoder] = None

        # Vulnerability multi-label model (chained)
        self.vulnerability_model: Optional[OneVsRestClassifier] = None
        self.mlb: Optional[MultiLabelBinarizer] = None

        # Risk score regressor
        self.risk_model: Optional[GradientBoostingRegressor] = None
        self.risk_scaler: Optional[StandardScaler] = None

        # Feature importance
        self.feature_importance: Optional[dict] = None

        # Training metadata
        self.cv_scores: Optional[dict] = None
        self.n_samples: int = 0
        self.trained_at: Optional[str] = None
        self.dataset_hash: Optional[str] = None
        self.label_distribution: Optional[dict] = None
        self.label_provenance: str = "rule-derived"
        self.probabilities_calibrated: bool = False
        self.train_accuracy: Optional[float] = None
        self.severity_train_accuracy: Optional[float] = None
        self._fitted = False

    def _build_text_pipeline(self) -> Pipeline:
        return Pipeline([
            ("vectorizer", TfidfVectorizer(
                max_features=1500,
                ngram_range=(1, 4),
                analyzer="word",
                sublinear_tf=True,
                min_df=2,
            )),
        ])

    def _build_joint_classifier(self) -> MultiOutputClassifier:
        return MultiOutputClassifier(
            GradientBoostingClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.1,
                subsample=0.8,
                min_samples_leaf=2,
                random_state=42,
            ),
        )

    def _build_vulnerability_model(self) -> OneVsRestClassifier:
        return OneVsRestClassifier(
            LogisticRegression(
                max_iter=2000,
                C=3.0,
                class_weight="balanced",
                random_state=42,
            ),
        )

    def _build_risk_model(self) -> GradientBoostingRegressor:
        return GradientBoostingRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            min_samples_leaf=3,
            loss="huber",
            random_state=42,
        )

    def fit(self, samples: list[dict], cv_folds: int = 5) -> "EnhancedAPIClassifier":
        paths = [s["endpoint_path"] for s in samples]
        methods = [s["http_method"] for s in samples]
        text_feats, struct_feats = prepare_features(paths, methods)

        self.n_samples = len(samples)
        self.trained_at = datetime.now(timezone.utc).isoformat()
        fingerprint = json.dumps(
            sorted(
                (s["endpoint_path"], s["http_method"], s["category"], s["severity"],
                 tuple(sorted(s["vulnerabilities"])))
                for s in samples
            ),
            default=str,
        )
        self.dataset_hash = hashlib.sha256(fingerprint.encode()).hexdigest()
        self.label_distribution = {
            "category": dict(Counter(s["category"] for s in samples)),
            "severity": dict(Counter(s["severity"] for s in samples)),
        }

        # Vectorize text features
        text_pipeline = self._build_text_pipeline()
        X_text = text_pipeline.fit_transform(text_feats)
        self.vectorizer = text_pipeline.named_steps["vectorizer"]
        logger.info(f"Vectorized text: {X_text.shape[1]} features from {len(samples)} samples")

        # Build structural feature matrix
        struct_keys = [k for k in struct_feats[0].keys() if k != "struct_pattern"]
        self.structural_feature_names = struct_keys
        X_struct = np.array([
            [sf[k] for k in struct_keys] for sf in struct_feats
        ], dtype=np.float64)

        # Feature scaling for structural features
        self.risk_scaler = StandardScaler()
        X_struct_scaled = self.risk_scaler.fit_transform(X_struct)

        # Combine: text TF-IDF + structural features
        from scipy.sparse import hstack, csr_matrix
        X = hstack([X_text, csr_matrix(X_struct_scaled)])
        logger.info(f"Combined feature matrix: {X.shape}")

        # ── Joint category + severity classifier ──
        categories = [s["category"] for s in samples]
        severities = [s["severity"] for s in samples]
        self.joint_encoder = MultiOutputEncoder()
        y_joint = self.joint_encoder.fit_transform(categories, severities)

        logger.info("Training joint category+severity classifier (GradientBoosting, uncalibrated)...")
        self.joint_classifier = self._build_joint_classifier()
        self.joint_classifier.fit(X, y_joint)
        joint_predictions = self.joint_classifier.predict(X)
        self.train_accuracy = float(accuracy_score(y_joint[:, 0], joint_predictions[:, 0]))
        self.severity_train_accuracy = float(accuracy_score(y_joint[:, 1], joint_predictions[:, 1]))
        logger.info(
            "Joint classifier trained (category accuracy: %.3f, severity accuracy: %.3f)",
            self.train_accuracy, self.severity_train_accuracy,
        )

        # CV scores for category classifier
        try:
            base = GradientBoostingClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
            )
            skf = StratifiedKFold(n_splits=min(cv_folds, 3), shuffle=True, random_state=42)
            cat_cv = cross_val_score(base, X, y_joint[:, 0], cv=skf, scoring="accuracy")
            self.cv_scores = {
                "category_cv_accuracy_mean": float(cat_cv.mean()),
                "category_cv_accuracy_std": float(cat_cv.std()),
            }
            logger.info(f"Category CV accuracy: {cat_cv.mean():.3f} +/- {cat_cv.std():.3f}")
        except Exception as e:
            logger.warning(f"CV scoring failed (non-fatal): {e}")
            self.cv_scores = {}

        # ── Vulnerability multi-label classifier ──
        vuln_lists = [s["vulnerabilities"] for s in samples]
        self.mlb = MultiLabelBinarizer(classes=VULN_TYPES)
        y_vuln = self.mlb.fit_transform(vuln_lists)

        self.vulnerability_model = self._build_vulnerability_model()
        self.vulnerability_model.fit(X, y_vuln)
        logger.info(f"Vulnerability model trained ({len(VULN_TYPES)} labels)")

        # ── Risk score regressor ──
        risk_scores = [s["risk_score"] for s in samples]
        self.risk_model = self._build_risk_model()
        self.risk_model.fit(X, risk_scores)

        y_pred_risk = self.risk_model.predict(X)
        mae = mean_absolute_error(risk_scores, y_pred_risk)
        logger.info(f"Risk regressor trained (MAE: {mae:.2f})")

        # ── Feature importance ──
        self._extract_feature_importance()

        self._fitted = True
        return self

    def _extract_feature_importance(self):
        try:
            text_feature_names = self.vectorizer.get_feature_names_out().tolist()
            all_feature_names = text_feature_names + self.structural_feature_names

            estimators = self.joint_classifier.estimators_
            importances = np.mean([est.feature_importances_ for est in estimators], axis=0)

            top_indices = np.argsort(importances)[-30:][::-1]
            self.feature_importance = {
                "top_features": [
                    {
                        "feature": all_feature_names[i],
                        "importance": round(float(importances[i]), 4),
                    }
                    for i in top_indices
                ],
                "num_total_features": len(importances),
            }
        except Exception as e:
            logger.warning(f"Could not extract feature importance: {e}")
            self.feature_importance = None

    def predict(self, path: str, method: str = "GET") -> dict:
        if not self._fitted:
            return self._fallback(path, method)

        text_feats, struct_feats = prepare_features([path], [method])
        X_text = self.vectorizer.transform(text_feats)

        struct_keys = [k for k in struct_feats[0].keys() if k != "struct_pattern"]
        X_struct = np.array([
            [sf[k] for k in struct_keys] for sf in struct_feats
        ], dtype=np.float64)
        X_struct_scaled = self.risk_scaler.transform(X_struct)

        from scipy.sparse import hstack, csr_matrix
        X = hstack([X_text, csr_matrix(X_struct_scaled)])

        # ── Joint prediction ──
        y_joint = self.joint_classifier.predict(X)
        category, severity = self.joint_encoder.inverse_transform(y_joint)

        # ── Joint probabilities ──
        y_proba_list = self.joint_classifier.predict_proba(X)
        cat_probas = y_proba_list[0][0]
        sev_probas = y_proba_list[1][0]
        cat_confidence = float(max(cat_probas))
        sev_confidence = float(max(sev_probas))

        # ── Vulnerability prediction ──
        vuln_preds = self.vulnerability_model.predict(X)
        vuln_probas = self.vulnerability_model.predict_proba(X)

        vulnerabilities = []
        vuln_confidences = {}
        for i, present in enumerate(vuln_preds[0]):
            if present:
                vuln_name = self.mlb.classes_[i]
                vulnerabilities.append(vuln_name)
                proba = float(vuln_probas[0][i]) if vuln_probas.ndim == 2 else 0.5
                vuln_confidences[vuln_name] = round(proba, 3)

        # ── Risk score ──
        risk_score_raw = self.risk_model.predict(X)[0]
        risk_score = max(0, min(100, int(round(risk_score_raw))))

        return {
            "category": category,
            "category_confidence": round(cat_confidence, 3),
            "severity": severity,
            "severity_confidence": round(sev_confidence, 3),
            "vulnerabilities": vulnerabilities,
            "vulnerability_confidences": vuln_confidences,
            "risk_score": risk_score,
            "ml_model_version": "enhanced-v1.0",
            "method": method,
        }

    def predict_batch(self, endpoints: list[tuple[str, str]]) -> list[dict]:
        return [self.predict(path, method) for path, method in endpoints]

    def _fallback(self, path: str, method: str = "GET") -> dict:
        from app.ml.data import classify_vulnerabilities, classify_severity, classify_api_category, estimate_risk_score
        vulns = classify_vulnerabilities(path, method)
        return {
            "category": classify_api_category(path, method),
            "category_confidence": 1.0,
            "severity": classify_severity(vulns),
            "severity_confidence": 1.0,
            "vulnerabilities": vulns,
            "vulnerability_confidences": {v: 1.0 for v in vulns},
            "risk_score": estimate_risk_score(path, method, vulns, classify_severity(vulns)),
            "ml_model_version": "rule-based-fallback",
            "method": method,
        }

    def save(self, directory: Optional[Path] = None) -> None:
        save_dir = directory or MODEL_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / "joint_classifier.pkl", "wb") as f:
            pickle.dump(self.joint_classifier, f)
        with open(save_dir / "vulnerability_model.pkl", "wb") as f:
            pickle.dump(self.vulnerability_model, f)
        with open(save_dir / "risk_model.pkl", "wb") as f:
            pickle.dump(self.risk_model, f)
        with open(save_dir / "vectorizer.pkl", "wb") as f:
            pickle.dump(self.vectorizer, f)
        with open(save_dir / "risk_scaler.pkl", "wb") as f:
            pickle.dump(self.risk_scaler, f)
        with open(save_dir / "joint_encoder.pkl", "wb") as f:
            pickle.dump(self.joint_encoder, f)
        with open(save_dir / "mlb.pkl", "wb") as f:
            pickle.dump(self.mlb, f)

        import sklearn

        metadata = {
            "structural_feature_names": self.structural_feature_names,
            "cv_scores": self.cv_scores,
            "feature_importance": self.feature_importance,
            "training_samples": self.n_samples,
            "trained_at": self.trained_at,
            "dataset_hash": self.dataset_hash,
            "label_distribution": self.label_distribution,
            "label_provenance": self.label_provenance,
            "probabilities_calibrated": self.probabilities_calibrated,
            "train_accuracy": self.train_accuracy,
            "severity_train_accuracy": self.severity_train_accuracy,
            "sklearn_version": sklearn.__version__,
        }
        with open(save_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Enhanced models saved to {save_dir}")

    @classmethod
    def load(cls, directory: Optional[Path] = None) -> "EnhancedAPIClassifier":
        load_dir = directory or MODEL_DIR
        required = [
            load_dir / "joint_classifier.pkl",
            load_dir / "vulnerability_model.pkl",
            load_dir / "risk_model.pkl",
            load_dir / "vectorizer.pkl",
            load_dir / "risk_scaler.pkl",
            load_dir / "joint_encoder.pkl",
            load_dir / "mlb.pkl",
        ]

        if not all(f.exists() for f in required):
            logger.warning("Enhanced model files not found at %s", load_dir)
            instance = cls()
            instance._fitted = False
            return instance

        instance = cls()

        with open(load_dir / "joint_classifier.pkl", "rb") as f:
            instance.joint_classifier = pickle.load(f)
        with open(load_dir / "vulnerability_model.pkl", "rb") as f:
            instance.vulnerability_model = pickle.load(f)
        with open(load_dir / "risk_model.pkl", "rb") as f:
            instance.risk_model = pickle.load(f)
        with open(load_dir / "vectorizer.pkl", "rb") as f:
            instance.vectorizer = pickle.load(f)
        with open(load_dir / "risk_scaler.pkl", "rb") as f:
            instance.risk_scaler = pickle.load(f)
        with open(load_dir / "joint_encoder.pkl", "rb") as f:
            instance.joint_encoder = pickle.load(f)
        with open(load_dir / "mlb.pkl", "rb") as f:
            instance.mlb = pickle.load(f)

        meta_path = load_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            instance.structural_feature_names = meta.get("structural_feature_names", [])
            instance.cv_scores = meta.get("cv_scores")
            instance.feature_importance = meta.get("feature_importance")
            instance.n_samples = meta.get("training_samples") or 0
            instance.trained_at = meta.get("trained_at")
            instance.dataset_hash = meta.get("dataset_hash")
            instance.label_distribution = meta.get("label_distribution")
            instance.label_provenance = meta.get("label_provenance", "rule-derived")
            instance.probabilities_calibrated = meta.get("probabilities_calibrated", False)
            instance.train_accuracy = meta.get("train_accuracy")
            instance.severity_train_accuracy = meta.get("severity_train_accuracy")

        instance._fitted = True
        logger.info(f"Enhanced models loaded from {load_dir}")
        return instance

    def predict_status(self, api) -> dict:
        """Predict API lifecycle status from an API database object.
        Delegates to the global StatusPredictor singleton."""
        predictor = get_status_predictor()
        if not predictor or not predictor._fitted:
            return {"status": "unknown", "status_confidence": 0.0, "status_probabilities": {}}
        features = ApiFeatures.from_db(api)
        return predictor.predict_from_api(features)

    def explain(self, path: str, method: str = "GET") -> dict:
        """Return prediction with explanation of key contributing features."""
        if not self._fitted:
            return {"error": "Model not fitted"}

        result = self.predict(path, method)
        result["feature_importance"] = self.feature_importance

        return result


# ── Multi-output encoder for joint category + severity ──────────────────────

class MultiOutputEncoder:
    """Encodes and decodes category + severity as a single multi-output target."""

    def __init__(self):
        self.category_encoder = LabelEncoder()
        self.severity_encoder = LabelEncoder()

    def fit_transform(self, categories: list[str], severities: list[str]) -> np.ndarray:
        y_cat = self.category_encoder.fit_transform(categories).reshape(-1, 1)
        y_sev = self.severity_encoder.fit_transform(severities).reshape(-1, 1)
        return np.hstack([y_cat, y_sev])

    def transform(self, categories: list[str], severities: list[str]) -> np.ndarray:
        y_cat = self.category_encoder.transform(categories).reshape(-1, 1)
        y_sev = self.severity_encoder.transform(severities).reshape(-1, 1)
        return np.hstack([y_cat, y_sev])

    def inverse_transform(self, y: np.ndarray) -> tuple[str, str]:
        category = self.category_encoder.inverse_transform([int(y[0][0])])[0]
        severity = self.severity_encoder.inverse_transform([int(y[0][1])])[0]
        return category, severity


# ── API Status Predictor ────────────────────────────────────────────────────

STATUS_LABELS = ["active", "deprecated", "orphaned", "shadow", "zombie"]

STATUS_STAGE_MAP = {
    "active": 0,
    "deprecated": 1,
    "orphaned": 2,
    "shadow": 3,
    "zombie": 4,
}


def _generate_status_training_data(n_samples: int = 2000, seed: int = 42) -> list[dict]:
    """Generate synthetic API data for status classification training.

    Mirrors the patterns from seed.py:
      - active:    high traffic (100-5000), risk 70-95, recent last_seen
      - deprecated: low traffic (10-100), risk 50-70, has findings
      - orphaned:  very low traffic (5-50), risk 40-75, no owner
      - shadow:    medium traffic (50-200), risk 75-98, no owner, high findings
      - zombie:    near-zero traffic (0-3), risk 60-90, old traffic, has workflow
    """
    rng = random.Random(seed)

    samples = []
    status_configs = [
        ("active",    0.50, 100, 5000, 70, 95,  0, 2,   True,  0.1),
        ("deprecated", 0.15, 10, 100,  50, 70,  3, 8,   True,  0.5),
        ("orphaned",  0.12, 5,  50,   40, 75,  1, 4,   False, 0.3),
        ("shadow",    0.13, 50, 200,  75, 98,  4, 10,  False, 0.7),
        ("zombie",    0.10, 0,  3,    60, 90,  5, 12,  True,  0.9),
    ]

    for status, pct, traffic_min, traffic_max, risk_min, risk_max, \
            find_min, find_max, has_owner_p, workflow_prob in status_configs:

        count = int(n_samples * pct)
        for _ in range(count):
            # Traffic features
            avg_traffic_7d = rng.randint(traffic_min, traffic_max)
            avg_traffic_30d = avg_traffic_7d + rng.randint(-int(avg_traffic_7d * 0.15),
                                                           int(avg_traffic_7d * 0.15))
            avg_traffic_30d = max(0, avg_traffic_30d)

            # Traffic trend: (7d / 30d) ratio
            base = avg_traffic_30d if avg_traffic_30d > 0 else 1
            traffic_trend = round(avg_traffic_7d / base, 4)

            # Error rate (higher for deprecated/orphaned)
            error_base = 0.02 if status == "active" else 0.05
            avg_error_rate = round(max(0, rng.gauss(error_base, 0.02)), 4)

            avg_response_time = round(rng.uniform(45, 350), 1)

            # Risk score
            risk_score = rng.randint(risk_min, risk_max)

            # Security findings
            findings_count = rng.randint(find_min, find_max)
            critical_findings = rng.randint(0, max(0, findings_count // 3))
            high_findings = rng.randint(0, max(0, findings_count - critical_findings))

            # Recency
            days_since_last_seen = rng.randint(0, 90 if status == "active" else 180)
            days_since_last_traffic = rng.randint(0, 7) if status == "active" else \
                rng.randint(10, 90)

            # Owner
            has_owner = rng.random() < has_owner_p

            # Workflow (only zombies + some deprecated have one)
            has_workflow = rng.random() < workflow_prob

            samples.append({
                "avg_traffic_7d": avg_traffic_7d,
                "avg_traffic_30d": avg_traffic_30d,
                "traffic_trend": traffic_trend,
                "avg_error_rate": avg_error_rate,
                "avg_response_time": avg_response_time,
                "risk_score": risk_score,
                "findings_count": findings_count,
                "critical_findings": critical_findings,
                "high_findings": high_findings,
                "days_since_last_seen": days_since_last_seen,
                "days_since_last_traffic": days_since_last_traffic,
                "has_owner": int(has_owner),
                "has_workflow": int(has_workflow),
                "status": status,
            })

    rng.shuffle(samples)
    return samples


STATUS_FEATURE_NAMES = [
    "avg_traffic_7d", "avg_traffic_30d", "traffic_trend",
    "avg_error_rate", "avg_response_time", "risk_score",
    "findings_count", "critical_findings", "high_findings",
    "days_since_last_seen", "days_since_last_traffic",
    "has_owner", "has_workflow",
]


class StatusPredictor:
    """Predicts API lifecycle status (active/deprecated/orphaned/shadow/zombie)
    from traffic patterns, risk, findings, and metadata features."""

    def __init__(self):
        self.model: Optional[GradientBoostingClassifier] = None
        self.label_encoder: Optional[LabelEncoder] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: list[str] = STATUS_FEATURE_NAMES
        self.cv_scores: Optional[dict] = None
        self.n_samples: int = 0
        self.trained_at: Optional[str] = None
        self.dataset_hash: Optional[str] = None
        self.label_distribution: Optional[dict] = None
        self.label_provenance: str = "synthetic"
        self.train_accuracy: Optional[float] = None
        self._fitted = False

    def _build_model(self) -> GradientBoostingClassifier:
        return GradientBoostingClassifier(
            n_estimators=250,
            max_depth=5,
            learning_rate=0.12,
            subsample=0.8,
            min_samples_leaf=4,
            random_state=42,
        )

    def fit(self, samples: list[dict], cv_folds: int = 5) -> "StatusPredictor":
        X = np.array([[s[f] for f in self.feature_names] for s in samples], dtype=np.float64)

        self.n_samples = len(samples)
        self.trained_at = datetime.now(timezone.utc).isoformat()
        self.label_distribution = dict(Counter(s["status"] for s in samples))
        fingerprint = json.dumps(
            sorted(
                (tuple(float(s[f]) for f in self.feature_names), s["status"])
                for s in samples
            ),
            default=str,
        )
        self.dataset_hash = hashlib.sha256(fingerprint.encode()).hexdigest()

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        y = [s["status"] for s in samples]
        self.label_encoder = LabelEncoder()
        y_enc = self.label_encoder.fit_transform(y)

        self.model = self._build_model()
        self.model.fit(X_scaled, y_enc)

        self.train_accuracy = float(accuracy_score(y_enc, self.model.predict(X_scaled)))
        logger.info(f"Status classifier trained (train accuracy: {self.train_accuracy:.3f})")

        try:
            skf = StratifiedKFold(n_splits=min(cv_folds, 5), shuffle=True, random_state=42)
            cv_scores = cross_val_score(self.model, X_scaled, y_enc, cv=skf, scoring="accuracy")
            self.cv_scores = {
                "status_cv_accuracy_mean": float(cv_scores.mean()),
                "status_cv_accuracy_std": float(cv_scores.std()),
            }
            logger.info(f"Status CV accuracy: {cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")
        except Exception as e:
            logger.warning(f"Status CV scoring failed: {e}")

        self._fitted = True
        return self

    def predict(self, features: dict[str, Any]) -> dict:
        if not self._fitted:
            return {"status": "unknown", "status_confidence": 0.0, "status_probabilities": {}}

        X = np.array([[features.get(f, 0) for f in self.feature_names]], dtype=np.float64)
        X_scaled = self.scaler.transform(X)

        pred_idx = self.model.predict(X_scaled)[0]
        status = self.label_encoder.inverse_transform([pred_idx])[0]

        probas = self.model.predict_proba(X_scaled)[0]
        confidence = float(max(probas))

        status_probas = {}
        for i, label in enumerate(self.label_encoder.classes_):
            status_probas[label] = round(float(probas[i]), 4)

        return {
            "status": status,
            "status_confidence": round(confidence, 4),
            "status_probabilities": status_probas,
        }

    def predict_from_api(self, api: "ApiFeatures") -> dict:
        return self.predict({
            "avg_traffic_7d": api.avg_traffic_7d,
            "avg_traffic_30d": api.avg_traffic_30d,
            "traffic_trend": api.traffic_trend,
            "avg_error_rate": api.avg_error_rate,
            "avg_response_time": api.avg_response_time,
            "risk_score": api.risk_score,
            "findings_count": api.findings_count,
            "critical_findings": api.critical_findings,
            "high_findings": api.high_findings,
            "days_since_last_seen": api.days_since_last_seen,
            "days_since_last_traffic": api.days_since_last_traffic,
            "has_owner": int(api.has_owner),
            "has_workflow": int(api.has_workflow),
        })

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "status_model.pkl", "wb") as f:
            pickle.dump(self.model, f)
        with open(directory / "status_encoder.pkl", "wb") as f:
            pickle.dump(self.label_encoder, f)
        with open(directory / "status_scaler.pkl", "wb") as f:
            pickle.dump(self.scaler, f)

        import sklearn

        metadata = {
            "feature_names": self.feature_names,
            "cv_scores": self.cv_scores,
            "training_samples": self.n_samples,
            "trained_at": self.trained_at,
            "dataset_hash": self.dataset_hash,
            "label_distribution": self.label_distribution,
            "label_provenance": self.label_provenance,
            "probabilities_calibrated": False,
            "train_accuracy": self.train_accuracy,
            "sklearn_version": sklearn.__version__,
        }
        with open(directory / "status_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    def load(self, directory: Path) -> bool:
        required = [
            directory / "status_model.pkl",
            directory / "status_encoder.pkl",
            directory / "status_scaler.pkl",
        ]
        if not all(f.exists() for f in required):
            logger.warning("Status model files not found at %s", directory)
            return False

        with open(directory / "status_model.pkl", "rb") as f:
            self.model = pickle.load(f)
        with open(directory / "status_encoder.pkl", "rb") as f:
            self.label_encoder = pickle.load(f)
        with open(directory / "status_scaler.pkl", "rb") as f:
            self.scaler = pickle.load(f)

        meta_path = directory / "status_metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            self.cv_scores = meta.get("cv_scores")
            self.n_samples = meta.get("training_samples") or 0
            self.trained_at = meta.get("trained_at")
            self.dataset_hash = meta.get("dataset_hash")
            self.label_distribution = meta.get("label_distribution")
            self.label_provenance = meta.get("label_provenance", "synthetic")
            self.train_accuracy = meta.get("train_accuracy")

        self._fitted = True
        logger.info("Status predictor loaded from %s", directory)
        return True


# ── ApiFeatures (bag-of-fields from inventory) ──────────────────────────────

@dataclass
class ApiFeatures:
    """Feature bag extracted from an API record for status prediction."""
    avg_traffic_7d: float = 0
    avg_traffic_30d: float = 0
    traffic_trend: float = 1.0
    avg_error_rate: float = 0
    avg_response_time: float = 0
    risk_score: int = 0
    findings_count: int = 0
    critical_findings: int = 0
    high_findings: int = 0
    days_since_last_seen: int = 0
    days_since_last_traffic: int = 0
    has_owner: bool = False
    has_workflow: bool = False

    @classmethod
    def from_db(cls, api: Any) -> "ApiFeatures":
        now = datetime.utcnow()

        traffic_metrics = getattr(api, "traffic_metrics", None) or []
        sorted_metrics = sorted(traffic_metrics, key=lambda m: m.time, reverse=True) if traffic_metrics else []

        traffic_7d_list = [m.request_count for m in sorted_metrics[:7]] if len(sorted_metrics) >= 7 else \
                          [m.request_count for m in sorted_metrics]
        traffic_30d_list = [m.request_count for m in sorted_metrics[:30]] if len(sorted_metrics) >= 30 else \
                           [m.request_count for m in sorted_metrics]

        avg_traffic_7d = sum(traffic_7d_list) / max(len(traffic_7d_list), 1)
        avg_traffic_30d = sum(traffic_30d_list) / max(len(traffic_30d_list), 1)
        base = avg_traffic_30d if avg_traffic_30d > 0 else 1
        traffic_trend = round(avg_traffic_7d / base, 4)

        error_rates = []
        response_times = []
        for m in sorted_metrics:
            total = m.request_count or 1
            error_rates.append((m.error_4xx_count + m.error_5xx_count) / total)
            response_times.append(m.avg_response_time_ms or 0)

        avg_error_rate = round(sum(error_rates) / max(len(error_rates), 1), 4) if error_rates else 0
        avg_response_time = round(sum(response_times) / max(len(response_times), 1), 1) if response_times else 0

        risk_score = getattr(api, "risk_score", 0) or 0

        findings = getattr(api, "security_findings", None) or []
        findings_count = len(findings)
        critical_findings = sum(1 for f in findings if getattr(f, "severity", "") == "critical")
        high_findings = sum(1 for f in findings if getattr(f, "severity", "") == "high")

        last_seen = getattr(api, "last_seen", None)
        days_since_last_seen = (now - last_seen).days if last_seen else 999

        last_traffic = getattr(api, "last_traffic_timestamp", None)
        days_since_last_traffic = (now - last_traffic).days if last_traffic else 999

        has_owner = bool(getattr(api, "owner_team", None))
        has_workflow = bool(getattr(api, "decommission_workflow", None))

        return cls(
            avg_traffic_7d=avg_traffic_7d,
            avg_traffic_30d=avg_traffic_30d,
            traffic_trend=traffic_trend,
            avg_error_rate=avg_error_rate,
            avg_response_time=avg_response_time,
            risk_score=risk_score,
            findings_count=findings_count,
            critical_findings=critical_findings,
            high_findings=high_findings,
            days_since_last_seen=days_since_last_seen,
            days_since_last_traffic=days_since_last_traffic,
            has_owner=has_owner,
            has_workflow=has_workflow,
        )


# ── Singleton ───────────────────────────────────────────────────────────────

_classifier_instance: Optional[EnhancedAPIClassifier] = None
_status_predictor_instance: Optional[StatusPredictor] = None


def get_enhanced_classifier() -> EnhancedAPIClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = EnhancedAPIClassifier.load()
    return _classifier_instance


def classify_endpoint_enhanced(path: str, method: str = "GET") -> dict:
    return get_enhanced_classifier().predict(path, method)


def get_status_predictor() -> Optional[StatusPredictor]:
    global _status_predictor_instance
    if _status_predictor_instance is None:
        predictor = StatusPredictor()
        if predictor.load(MODEL_DIR):
            _status_predictor_instance = predictor
        else:
            logger.warning("Status predictor not available, train with train_enhanced.py")
            return None
    return _status_predictor_instance


def predict_api_status(api) -> dict:
    """Convenience: predict lifecycle status from an API DB record."""
    predictor = get_status_predictor()
    if not predictor:
        return {"status": "unknown", "status_confidence": 0.0, "status_probabilities": {}}
    features = ApiFeatures.from_db(api)
    return predictor.predict_from_api(features)
