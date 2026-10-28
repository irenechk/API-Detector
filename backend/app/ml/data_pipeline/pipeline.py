"""
Training data pipeline orchestrator.

Coordinates multiple data sources to build a training dataset for the
status prediction model. Handles source selection, data merging,
feature computation, and dataset quality checks.

Usage:
    pipeline = TrainingDataPipeline()
    await pipeline.run()

    # Or for synchronous use (e.g. training script):
    data = build_status_training_data(source_type="auto")
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from collections import Counter

from app.ml.data_pipeline.sources import (
    DataSource,
    RawAPIRecord,
    RawTrafficRecord,
    RawFindingRecord,
    SyntheticSource,
    get_data_source,
)
from app.ml.data_pipeline.features import build_training_record

logger = logging.getLogger(__name__)


# ── Dataset Quality Checks ──────────────────────────────────────────────────

class DatasetQualityCheck:
    """Run quality checks on generated training data."""

    @staticmethod
    def check_status_distribution(samples: list[dict]) -> list[str]:
        """Warn if any status class is underrepresented."""
        issues = []
        counts = Counter(s["status"] for s in samples)
        total = len(samples)
        for status, count in counts.items():
            pct = count / total * 100
            if pct < 5:
                issues.append(
                    f"Status '{status}' is underrepresented: {count}/{total} ({pct:.1f}%)"
                )
        return issues

    @staticmethod
    def check_feature_ranges(samples: list[dict]) -> list[str]:
        """Check for suspicious feature values."""
        issues = []
        for s in samples:
            if s["risk_score"] < 0 or s["risk_score"] > 100:
                issues.append(f"Risk score out of range: {s['risk_score']}")
            if s["days_since_last_seen"] < 0:
                issues.append(f"Negative days_since_last_seen: {s['days_since_last_seen']}")
            if s["days_since_last_traffic"] < 0:
                issues.append(f"Negative days_since_last_traffic: {s['days_since_last_traffic']}")
        return issues

    @staticmethod
    def check_missing_features(samples: list[dict]) -> list[str]:
        """Check for missing required features."""
        required = {
            "avg_traffic_7d", "avg_traffic_30d", "traffic_trend",
            "avg_error_rate", "avg_response_time", "risk_score",
            "findings_count", "critical_findings", "high_findings",
            "days_since_last_seen", "days_since_last_traffic",
            "has_owner", "has_workflow", "status",
        }
        issues = []
        for i, s in enumerate(samples):
            missing = required - set(s.keys())
            if missing:
                issues.append(f"Sample {i} missing features: {missing}")
        return issues

    @staticmethod
    def run_all(samples: list[dict]) -> list[str]:
        issues = []
        issues.extend(DatasetQualityCheck.check_status_distribution(samples))
        issues.extend(DatasetQualityCheck.check_feature_ranges(samples))
        issues.extend(DatasetQualityCheck.check_missing_features(samples))
        return issues


# ── Data Merging ────────────────────────────────────────────────────────────

class DataMerger:
    """Merges data from multiple sources into a unified training dataset."""

    def __init__(self, sources: list[DataSource]):
        self.sources = sources

    def merge(self, days_back: int = 90) -> tuple[list[RawAPIRecord], list[RawTrafficRecord], list[RawFindingRecord]]:
        """Fetch and merge data from all configured sources."""
        since = datetime.utcnow() - timedelta(days=days_back)

        all_apis = []
        all_traffic = []
        all_findings = []

        for source in self.sources:
            try:
                apis = source.fetch_apis()
                traffic = source.fetch_traffic(since)
                findings = source.fetch_findings(since)

                all_apis.extend(apis)
                all_traffic.extend(traffic)
                all_findings.extend(findings)

                logger.info(
                    "Source '%s': %d APIs, %d traffic records, %d findings",
                    source.name(), len(apis), len(traffic), len(findings)
                )
            except Exception as e:
                logger.error("Source '%s' failed: %s", source.name(), e)

        # Deduplicate by path+method
        seen_api = set()
        deduped_apis = []
        for api in all_apis:
            key = f"{api.endpoint_path}:{api.http_method}"
            if key not in seen_api:
                seen_api.add(key)
                deduped_apis.append(api)

        logger.info(
            "Merged data: %d unique APIs, %d traffic records, %d findings",
            len(deduped_apis), len(all_traffic), len(all_findings)
        )
        return deduped_apis, all_traffic, all_findings


# ── Training Data Builder ───────────────────────────────────────────────────

class TrainingDataPipeline:
    """Orchestrates the full pipeline from data ingestion to labeled samples.

    Supports both synchronous and async execution patterns.

    Example (production):
        pipeline = TrainingDataPipeline(sources=[gateway_source, cmdb_source])
        samples = pipeline.run()

    Example (auto-detect):
        pipeline = TrainingDataPipeline(source_type="auto")
        samples = pipeline.run()
    """

    def __init__(
        self,
        sources: Optional[list[DataSource]] = None,
        source_type: str = "auto",
        source_config: Optional[dict] = None,
    ):
        if sources:
            self.merger = DataMerger(sources)
        else:
            source = get_data_source(source_type, source_config)
            self.merger = DataMerger([source])

    def run(self, days_back: int = 90, run_quality_checks: bool = True) -> list[dict]:
        """Execute the pipeline and return labeled training samples.

        Args:
            days_back: How many days of history to fetch.
            run_quality_checks: Whether to validate output dataset.

        Returns:
            List of dicts, each a complete training record (features + label).
        """
        logger.info("Running training data pipeline (days_back=%d)...", days_back)
        apis, traffic, findings = self.merger.merge(days_back=days_back)

        now = datetime.utcnow()
        samples = []
        for api in apis:
            record = build_training_record(
                api_record=api,
                traffic_records=traffic,
                findings=findings,
                has_workflow=getattr(api, "has_workflow", False),
                now=now,
            )
            samples.append(record)

        if run_quality_checks:
            issues = DatasetQualityCheck.run_all(samples)
            if issues:
                for issue in issues:
                    logger.warning("Quality issue: %s", issue)
            else:
                logger.info("All quality checks passed (%d samples)", len(samples))

        status_counts = Counter(s["status"] for s in samples)
        logger.info("Pipeline complete. Status distribution: %s", dict(status_counts))

        return samples


# ── Convenience function for training scripts ───────────────────────────────

def build_status_training_data(
    source_type: str = "auto",
    source_config: Optional[dict] = None,
    days_back: int = 90,
    min_samples: int = 200,
    synthetic_fallback: bool = True,
) -> list[dict]:
    """Build training data from real sources, falling back to synthetic.

    This is the main entry point for training scripts.

    Args:
        source_type: 'auto', 'gateway', 'cmdb', 'scanner', or 'synthetic'.
        source_config: Config dict passed to the data source factory.
        days_back: Days of history to fetch.
        min_samples: Minimum samples required before falling back.
        synthetic_fallback: If True, fall back to synthetic data when real
                           sources yield fewer than min_samples.

    Returns:
        List of training records (dicts with features + status label).
    """
    if source_type == "synthetic":
        logger.info("Using synthetic data source directly")
        return _build_synthetic_data()

    pipeline = TrainingDataPipeline(source_type=source_type, source_config=source_config)

    try:
        samples = pipeline.run(days_back=days_back)

        if len(samples) < min_samples:
            logger.warning(
                "Real sources yielded only %d samples (need %d)",
                len(samples), min_samples
            )
            if synthetic_fallback:
                logger.info("Augmenting with synthetic data...")
                synthetic = _build_synthetic_data()
                combined = samples + synthetic
                logger.info("Combined dataset: %d samples (%d real + %d synthetic)",
                          len(combined), len(samples), len(synthetic))
                return combined

        return samples

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        if synthetic_fallback:
            logger.info("Falling back to synthetic data")
            return _build_synthetic_data()
        raise


def _build_synthetic_data() -> list[dict]:
    """Generate training data using the built-in synthetic generator."""
    from app.ml.enhanced_classifier import _generate_status_training_data
    return _generate_status_training_data(n_samples=2000)
