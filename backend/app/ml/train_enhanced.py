#!/usr/bin/env python3
"""
Training script for the Enhanced API ML classifier.

Usage:
    python -m app.ml.train_enhanced
"""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_enhanced")

from app.ml.data import generate_dataset
from app.ml.enhanced_classifier import (
    EnhancedAPIClassifier, StatusPredictor, STATUS_FEATURE_NAMES, MODEL_DIR,
)
from app.ml.governance import ModelRegistry, next_version, register_trained_model
from collections import Counter


VULN_TYPES = [
    "Exposed Admin Interface", "Sensitive Data Exposure",
    "Insecure Direct Object Reference (IDOR)", "Authentication Bypass",
    "Mass Assignment / API Abuse", "Missing Rate Limiting",
    "GraphQL Introspection Enabled", "API Documentation Leakage",
    "File Operation Abuse", "CORS Misconfiguration", "Information Disclosure",
]


def main():
    logger.info("Generating training dataset...")
    samples = generate_dataset()
    logger.info("Generated %d labeled API endpoint samples", len(samples))

    sev_counts = Counter(s["severity"] for s in samples)
    cat_counts = Counter(s["category"] for s in samples)
    vuln_counts = Counter(v for s in samples for v in s["vulnerabilities"])

    logger.info("Severity distribution: %s", dict(sev_counts))
    logger.info("Category distribution: %s", dict(cat_counts))
    logger.info("Vulnerability distribution: %s", dict(vuln_counts))

    logger.info("Training Enhanced ML models (multi-output, Gradient Boosting)...")
    classifier = EnhancedAPIClassifier()
    classifier.fit(samples, cv_folds=5)

    logger.info("Saving enhanced models to disk...")
    classifier.save()

    # ── Register endpoint models ──
    top_features = [
        item["feature"] for item in (classifier.feature_importance or {}).get("top_features", [])
    ]
    feature_names = list(dict.fromkeys(top_features + classifier.structural_feature_names))
    artifact_hashes = {
        name: ModelRegistry.compute_file_hash(MODEL_DIR / name)
        for name in (
            "joint_classifier.pkl",
            "vulnerability_model.pkl",
            "risk_model.pkl",
        )
    }

    for model_type, artifact, notes in [
        ("category", "joint_classifier.pkl", "Joint category output; uncalibrated; rule-derived labels"),
        ("severity", "joint_classifier.pkl", "Joint severity output; uncalibrated; rule-derived labels"),
        ("vulnerability", "vulnerability_model.pkl", "Multi-label OneVsRest; rule-derived labels"),
        ("risk", "risk_model.pkl", "Risk regression; rule-derived labels"),
    ]:
        version = next_version(model_type)
        register_trained_model(
            model_version=version,
            model_type=model_type,
            training_samples=len(samples),
            source_type="synthetic",
            data_sources=["synthetic"],
            cv_scores=classifier.cv_scores if model_type == "category" else None,
            train_accuracy=(
                classifier.severity_train_accuracy if model_type == "severity"
                else classifier.train_accuracy if model_type == "category"
                else None
            ),
            feature_names=feature_names,
            file_hash=artifact_hashes[artifact],
            notes=notes,
        )
        logger.info("Registered %s v%s", model_type, version)

    # ── Status predictor ──
    logger.info("\n=== API Status Predictor ===")
    logger.info("Generating status training data through the data pipeline...")
    from app.ml.data_pipeline.pipeline import TrainingDataPipeline
    status_samples = TrainingDataPipeline(source_type="synthetic").run(days_back=30)

    from collections import Counter as Ctr
    status_dist = Ctr(s["status"] for s in status_samples)
    logger.info("Status distribution: %s", dict(status_dist))

    logger.info("Training status classifier (GradientBoosting)...")
    status_predictor = StatusPredictor()
    status_predictor.fit(status_samples, cv_folds=5)

    status_predictor.save(MODEL_DIR)
    logger.info("Status predictor saved to %s", MODEL_DIR)

    status_version = next_version("status")
    register_trained_model(
        model_version=status_version,
        model_type="status",
        training_samples=status_predictor.n_samples,
        source_type="synthetic",
        data_sources=["synthetic.pipeline"],
        cv_scores=status_predictor.cv_scores,
        train_accuracy=status_predictor.train_accuracy,
        feature_names=STATUS_FEATURE_NAMES,
        file_hash=ModelRegistry.compute_file_hash(MODEL_DIR / "status_model.pkl"),
        notes="Synthetic pipeline data; uncalibrated probabilities",
    )
    logger.info("Registered status v%s", status_version)

    # Validate with synthetic API-like scenarios
    logger.info("\nStatus prediction validation:")
    test_scenarios = [
        {"desc": "Active API (high traffic, low findings)", "avg_traffic_7d": 2500, "avg_traffic_30d": 2400, "traffic_trend": 1.04, "avg_error_rate": 0.02, "avg_response_time": 85, "risk_score": 72, "findings_count": 1, "critical_findings": 0, "high_findings": 0, "days_since_last_seen": 0, "days_since_last_traffic": 0, "has_owner": 1, "has_workflow": 0},
        {"desc": "Zombie (zero traffic, old, many findings)", "avg_traffic_7d": 0, "avg_traffic_30d": 1, "traffic_trend": 0.0, "avg_error_rate": 0.0, "avg_response_time": 0, "risk_score": 85, "findings_count": 8, "critical_findings": 3, "high_findings": 3, "days_since_last_seen": 120, "days_since_last_traffic": 90, "has_owner": 1, "has_workflow": 1},
        {"desc": "Shadow (no owner, medium traffic, high risk)", "avg_traffic_7d": 120, "avg_traffic_30d": 110, "traffic_trend": 1.09, "avg_error_rate": 0.04, "avg_response_time": 150, "risk_score": 88, "findings_count": 7, "critical_findings": 2, "high_findings": 3, "days_since_last_seen": 45, "days_since_last_traffic": 3, "has_owner": 0, "has_workflow": 0},
        {"desc": "Deprecated (low traffic, has owner)", "avg_traffic_7d": 45, "avg_traffic_30d": 60, "traffic_trend": 0.75, "avg_error_rate": 0.06, "avg_response_time": 200, "risk_score": 58, "findings_count": 5, "critical_findings": 1, "high_findings": 2, "days_since_last_seen": 30, "days_since_last_traffic": 15, "has_owner": 1, "has_workflow": 0},
        {"desc": "Orphaned (low traffic, no owner)", "avg_traffic_7d": 20, "avg_traffic_30d": 30, "traffic_trend": 0.67, "avg_error_rate": 0.05, "avg_response_time": 180, "risk_score": 55, "findings_count": 2, "critical_findings": 0, "high_findings": 1, "days_since_last_seen": 60, "days_since_last_traffic": 20, "has_owner": 0, "has_workflow": 0},
    ]

    logger.info("%-50s %-12s %s", "Scenario", "Predicted", "Confidence")
    logger.info("-" * 80)
    for sc in test_scenarios:
        result = status_predictor.predict(sc)
        logger.info("%-50s %-12s %.4f",
                    sc["desc"], result["status"], result["status_confidence"])

    # ── Endpoint models summary ──
    logger.info("\n=== Endpoint Classification Model Summary ===")
    logger.info("Models saved to app/ml/models_enhanced/")

    total_params = (
        classifier.joint_classifier.estimators_[0].n_estimators
        if hasattr(classifier.joint_classifier, "estimators_")
        else "N/A"
    )
    logger.info("  Feature dimensions: ~1500 TF-IDF + %d structural = ~%d total",
                len(classifier.structural_feature_names),
                1500 + len(classifier.structural_feature_names))
    logger.info("  Classifier ensemble: GradientBoosting (%s estimators, multi-output)", total_params)
    logger.info("  Vulnerability: OneVsRest LogisticRegression (%d labels)", len(VULN_TYPES))
    logger.info("  Risk: GradientBoostingRegressor (huber loss)")
    if classifier.cv_scores:
        logger.info("  Category CV accuracy: %.1f%% +/- %.1f%%",
                    classifier.cv_scores["category_cv_accuracy_mean"] * 100,
                    classifier.cv_scores["category_cv_accuracy_std"] * 100)

    logger.info("\n=== Status Prediction Model Summary ===")
    logger.info("  Features (13): %s", ", ".join(STATUS_FEATURE_NAMES))
    logger.info("  Classes: active, deprecated, orphaned, shadow, zombie")
    logger.info("  Classifier: GradientBoosting (250 estimators)")
    if status_predictor.cv_scores:
        logger.info("  CV accuracy: %.1f%% +/- %.1f%%",
                    status_predictor.cv_scores["status_cv_accuracy_mean"] * 100,
                    status_predictor.cv_scores["status_cv_accuracy_std"] * 100)

    logger.info("\nTraining complete!")

if __name__ == "__main__":
    main()
