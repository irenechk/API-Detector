#!/usr/bin/env python3
"""
Training script for the API ML classifier.

Generates labeled training data using the rule-based labeling system,
trains all models, and saves them to disk for inference.

Usage:
    python -m app.ml.train
    # or
    python backend/app/ml/train.py
"""

import sys
import logging
from pathlib import Path

# Ensure the backend root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train")

from app.ml.data import generate_dataset
from app.ml.classifier import APIClassifier


def main():
    logger.info("Generating training dataset...")
    samples = generate_dataset()
    logger.info("Generated %d labeled API endpoint samples", len(samples))

    # Show dataset stats
    from collections import Counter
    sev_counts = Counter(s["severity"] for s in samples)
    cat_counts = Counter(s["category"] for s in samples)
    vuln_counts = Counter(v for s in samples for v in s["vulnerabilities"])

    logger.info("Severity distribution: %s", dict(sev_counts))
    logger.info("Category distribution: %s", dict(cat_counts))
    logger.info("Vulnerability distribution: %s", dict(vuln_counts))

    logger.info("Training ML models...")
    classifier = APIClassifier()
    classifier.fit(samples)

    logger.info("Saving models to disk...")
    classifier.save()

    # Quick validation
    logger.info("Running validation predictions...")
    test_cases = [
        ("/api/v1/auth/login", "POST"),
        ("/api/v1/users/123", "GET"),
        ("/admin/dashboard", "GET"),
        ("/api/v1/health", "GET"),
        ("/graphql", "POST"),
        ("/api/v1/files/upload", "POST"),
        ("/api/v1/config", "GET"),
        ("/swagger.json", "GET"),
        ("/api/v1/payments/charge", "POST"),
        ("/api/v1/search", "GET"),
    ]

    for path, method in test_cases:
        result = classifier.predict(path, method)
        logger.info(
            "  %-45s → cat=%-20s sev=%-10s risk=%-3d vulns=%s",
            f"{method} {path}",
            result["category"],
            result["severity"],
            result["risk_score"],
            result["vulnerabilities"],
        )

    logger.info("Training complete! Models saved to app/ml/models/")


if __name__ == "__main__":
    main()
