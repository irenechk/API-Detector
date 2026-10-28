"""
Feature computation for the API status prediction model.

Transforms raw data (traffic logs, CMDB records, scanner findings)
into the 13 features the StatusPredictor expects.

Each function is pure and testable independently.
"""

from datetime import datetime, timedelta
from typing import Optional
from app.ml.data_pipeline.sources import (
    RawTrafficRecord,
    RawAPIRecord,
    RawFindingRecord,
)


def compute_traffic_features(
    traffic_records: list[RawTrafficRecord],
    api_path: str,
    http_method: str,
    now: Optional[datetime] = None,
) -> dict:
    """Compute traffic-derived features for a specific API endpoint.

    Args:
        traffic_records: All traffic records (will be filtered to match api_path+method).
        api_path: Target API path.
        http_method: Target HTTP method.
        now: Reference time for recency calculations.

    Returns:
        dict with keys: avg_traffic_7d, avg_traffic_30d, traffic_trend,
                        avg_error_rate, avg_response_time,
                        days_since_last_traffic
    """
    now = now or datetime.utcnow()

    matching = [
        r for r in traffic_records
        if r.api_path == api_path and r.http_method == http_method
    ]

    if not matching:
        return {
            "avg_traffic_7d": 0.0,
            "avg_traffic_30d": 0.0,
            "traffic_trend": 0.0,
            "avg_error_rate": 0.0,
            "avg_response_time": 0.0,
            "days_since_last_traffic": 999,
        }

    matching.sort(key=lambda r: r.timestamp, reverse=True)

    score_period = now - timedelta(days=7)
    long_period = now - timedelta(days=30)

    recent = [r for r in matching if r.timestamp >= score_period]
    historical = [r for r in matching if r.timestamp >= long_period]

    avg_traffic_7d = sum(r.request_count for r in recent) / max(len(recent), 1)
    avg_traffic_30d = sum(r.request_count for r in historical) / max(len(historical), 1)
    base = avg_traffic_30d if avg_traffic_30d > 0 else 1
    traffic_trend = round(avg_traffic_7d / base, 4)

    error_rates = []
    response_times = []
    for r in matching:
        total = r.request_count or 1
        error_rates.append((r.error_4xx_count + r.error_5xx_count) / total)
        response_times.append(r.avg_response_time_ms)

    avg_error_rate = round(sum(error_rates) / max(len(error_rates), 1), 4) if error_rates else 0
    avg_response_time = round(sum(response_times) / max(len(response_times), 1), 1) if response_times else 0

    last_traffic = matching[0].timestamp
    days_since_last_traffic = (now - last_traffic).days

    return {
        "avg_traffic_7d": float(avg_traffic_7d),
        "avg_traffic_30d": float(avg_traffic_30d),
        "traffic_trend": float(traffic_trend),
        "avg_error_rate": float(avg_error_rate),
        "avg_response_time": float(avg_response_time),
        "days_since_last_traffic": days_since_last_traffic,
    }


def compute_risk_features(
    api_record: RawAPIRecord,
) -> dict:
    """Extract risk-related features from an API record."""
    return {
        "risk_score": api_record.risk_score,
    }


def compute_governance_features(
    api_record: RawAPIRecord,
    now: Optional[datetime] = None,
) -> dict:
    """Compute governance-related features from CMDB data."""
    now = now or datetime.utcnow()

    last_seen = api_record.last_seen or now
    days_since_last_seen = (now - last_seen).days if last_seen else 999

    return {
        "days_since_last_seen": days_since_last_seen,
        "has_owner": int(bool(api_record.owner_team)),
    }


def compute_security_features(
    findings: list[RawFindingRecord],
    api_path: str,
    http_method: str,
) -> dict:
    """Compute security feature aggregates from scanner findings."""
    matching = [
        f for f in findings
        if f.api_path == api_path and f.http_method == http_method
    ]

    return {
        "findings_count": len(matching),
        "critical_findings": sum(1 for f in matching if f.severity == "critical"),
        "high_findings": sum(1 for f in matching if f.severity == "high"),
    }


def compute_api_features(
    api_record: RawAPIRecord,
    traffic_records: list[RawTrafficRecord],
    findings: list[RawFindingRecord],
    now: Optional[datetime] = None,
) -> dict:
    """Compute the complete feature vector for a single API.

    This is the main entry point for feature computation.
    Returns all 13 features needed by the StatusPredictor.
    """
    now = now or datetime.utcnow()

    traffic_feats = compute_traffic_features(
        traffic_records, api_record.endpoint_path, api_record.http_method, now
    )
    risk_feats = compute_risk_features(api_record)
    gov_feats = compute_governance_features(api_record, now)
    sec_feats = compute_security_features(
        findings, api_record.endpoint_path, api_record.http_method
    )

    features = {}
    features.update(traffic_feats)
    features.update(risk_feats)
    features.update(gov_feats)
    features.update(sec_feats)

    features["has_workflow"] = 0  # determined by pipeline from workflow table

    return features


def build_training_record(
    api_record: RawAPIRecord,
    traffic_records: list[RawTrafficRecord],
    findings: list[RawFindingRecord],
    has_workflow: bool = False,
    now: Optional[datetime] = None,
) -> dict:
    """Build a full training record (features + label) for one API.

    This is used by the pipeline to generate training data from
    production data sources.
    """
    features = compute_api_features(api_record, traffic_records, findings, now)
    features["has_workflow"] = int(has_workflow)
    features["status"] = api_record.status
    return features
