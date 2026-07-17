import json

from fastapi.testclient import TestClient

from app.main import app


def test_evaluation_summary_defaults_to_live_and_supports_baseline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.evaluation_service.REPORT_DIR", tmp_path)
    (tmp_path / "latest-live.json").write_text(
        json.dumps({"status": "passed", "run_mode": "live", "case_count": 50}),
        encoding="utf-8",
    )
    (tmp_path / "latest-baseline.json").write_text(
        json.dumps({"status": "passed", "run_mode": "baseline", "case_count": 50}),
        encoding="utf-8",
    )

    client = TestClient(app)
    live = client.get("/api/v1/evaluations/summary").json()["data"]
    baseline = client.get("/api/v1/evaluations/summary?mode=baseline").json()["data"]

    assert live["run_mode"] == "live"
    assert baseline["run_mode"] == "baseline"


def test_evaluation_summary_reports_not_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.evaluation_service.REPORT_DIR", tmp_path)
    data = TestClient(app).get("/api/v1/evaluations/summary").json()["data"]
    assert data["status"] == "not_run"
    assert data["run_mode"] == "live"
