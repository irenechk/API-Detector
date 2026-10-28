from pathlib import Path

from app.ml.governance import (
    ChampionChallenger,
    DriftDetector,
    ModelRegistry,
    ModelVersion,
    _version_key,
)


def _version(version: str, model_type: str = "status", status: str = "staging") -> ModelVersion:
    return ModelVersion(
        version=version,
        model_type=model_type,
        training_date="2026-01-01T00:00:00+00:00",
        training_samples=100,
        source_type="synthetic",
        data_sources=["synthetic"],
        cv_accuracy_mean=0.8,
        status=status,
    )


def test_version_key_sorts_semver_numerically():
    versions = ["1.9.0", "1.10.0", "1.2.3", "2.0.0"]
    assert sorted(versions, key=_version_key) == ["1.2.3", "1.9.0", "1.10.0", "2.0.0"]


def test_registry_promotes_and_archives_with_semver_order(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "registry.json")
    for version in ("1.2.0", "1.9.0", "1.10.0"):
        registry.register(_version(version))

    assert registry.get_latest().version == "1.10.0"
    registry.promote_to_champion("1.10.0")
    assert registry.get_champion().version == "1.10.0"
    assert registry.get_challenger() is None

    registry.archive_old_versions(keep_last=2)
    statuses = {v.version: v.status for v in registry.list_versions()}
    assert statuses["1.2.0"] == "archived"
    assert statuses["1.10.0"] == "champion"


def test_registry_persists_to_disk(tmp_path: Path):
    path = tmp_path / "registry.json"
    registry = ModelRegistry(path)
    registry.register(_version("1.0.0"))

    reloaded = ModelRegistry(path)

    assert [v.version for v in reloaded.list_versions()] == ["1.0.0"]


def test_drift_detector_uses_correct_psi_and_persists(tmp_path: Path):
    detector = DriftDetector(threshold=0.25, monitoring_dir=tmp_path)
    detector.set_baseline([{"status": "active"}] * 50 + [{"status": "zombie"}] * 50)
    for _ in range(100):
        detector.record_prediction({"status": "active"})

    report = detector.check_drift(min_samples=100)

    assert report is not None
    assert report.samples_baseline == 100
    assert report.samples_current == 100
    assert report.is_drifted is True
    assert report.psi > 0.25
    assert (tmp_path / "baseline.json").exists()
    assert detector.latest_report()["psi"] == report.psi
    assert detector.buffered_count() == 0


def test_ungrounded_comparison_cannot_promote(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_version("1.0.0", status="champion"))
    registry.register(_version("1.1.0", status="challenger"))
    cc = ChampionChallenger(registry)
    cc.record_shadow_prediction({"status": "active"}, {"status": "zombie"})

    result = cc.compare("1.0.0", "1.1.0")

    assert result.ground_truth_used is False
    assert cc.promote_if_better("1.1.0") is False
    assert registry.get_champion().version == "1.0.0"


def test_grounded_comparison_promotes_better_challenger(tmp_path: Path):
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register(_version("1.0.0", status="champion"))
    registry.register(_version("1.1.0", status="challenger"))
    cc = ChampionChallenger(registry)
    cc.record_shadow_prediction({"status": "zombie"}, {"status": "active"})
    cc.record_shadow_prediction({"status": "zombie"}, {"status": "active"})

    result = cc.compare("1.0.0", "1.1.0", ground_truth=["active", "active"])

    assert result.ground_truth_used is True
    assert result.accuracy_b > result.accuracy_a
    assert cc.promote_if_better("1.1.0") is True
    assert registry.get_champion().version == "1.1.0"
