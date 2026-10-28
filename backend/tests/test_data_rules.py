from app.ml.data import (
    classify_api_category,
    classify_severity,
    classify_vulnerabilities,
    estimate_risk_score,
    generate_dataset,
)


def test_numeric_id_paths_are_flagged_as_idor():
    vulns = classify_vulnerabilities("/api/v1/users/12345", "GET")
    assert "Insecure Direct Object Reference (IDOR)" in vulns


def test_wildcard_paths_are_flagged_as_idor():
    vulns = classify_vulnerabilities("/api/v1/accounts/{accountId}", "GET")
    assert "Insecure Direct Object Reference (IDOR)" in vulns


def test_long_numeric_ids_add_risk():
    vulns_without = classify_vulnerabilities("/api/v1/orders/42", "GET")
    vulns_with = classify_vulnerabilities("/api/v1/orders/123456", "GET")
    severity = classify_severity(vulns_with)

    score_without = estimate_risk_score("/api/v1/orders/42", "GET", vulns_without, severity)
    score_with = estimate_risk_score("/api/v1/orders/123456", "GET", vulns_with, severity)

    assert score_with > score_without


def test_dataset_is_deterministic_and_labelled():
    first = generate_dataset()
    second = generate_dataset()

    assert first == second
    assert len(first) > 0
    for sample in first[:20]:
        assert sample["category"]
        assert sample["severity"] in {"critical", "high", "medium", "low"}
        assert 0 <= sample["risk_score"] <= 100


def test_category_classification_examples():
    assert classify_api_category("/api/v1/login", "POST") == "authentication"
    assert classify_api_category("/api/v1/payments/checkout", "POST") == "payment"
    assert classify_api_category("/api/v1/health", "GET") == "system_health"
