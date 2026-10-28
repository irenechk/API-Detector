from datetime import datetime, timedelta

from app.ml.data_pipeline.sources import SyntheticSource


def test_synthetic_findings_and_traffic_attach_to_real_apis():
    source = SyntheticSource()
    apis = source.fetch_apis()
    traffic = source.fetch_traffic(datetime.utcnow() - timedelta(days=30))
    findings = source.fetch_findings(datetime.utcnow() - timedelta(days=30))

    api_keys = {(api.endpoint_path, api.http_method) for api in apis}
    assert traffic
    assert findings
    assert all((record.api_path, record.http_method) in api_keys for record in traffic)
    assert all((record.api_path, record.http_method) in api_keys for record in findings)


def test_synthetic_status_semantics_are_consistent():
    source = SyntheticSource()
    apis = source.fetch_apis()

    zombies = [api for api in apis if api.status == "zombie"]
    active = [api for api in apis if api.status == "active"]
    deprecated = [api for api in apis if api.status == "deprecated"]

    assert zombies and active and deprecated
    assert all(api.has_workflow for api in zombies)
    assert not any(api.has_workflow for api in active)
    assert all(api.owner_team for api in active)
    assert all(api.owner_team for api in deprecated)


def test_synthetic_traffic_respects_status_volume():
    source = SyntheticSource()
    apis = {api.endpoint_path: api for api in source.fetch_apis()}
    traffic = source.fetch_traffic(datetime.utcnow() - timedelta(days=30))

    zombie_records = [r for r in traffic if apis[r.api_path].status == "zombie"]
    active_records = [r for r in traffic if apis[r.api_path].status == "active"]

    max_zombie = max(r.request_count for r in zombie_records)
    min_active = min(r.request_count for r in active_records)
    assert max_zombie <= 5
    assert min_active > max_zombie
