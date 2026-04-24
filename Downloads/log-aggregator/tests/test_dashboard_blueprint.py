from io import BytesIO

from flask import Flask

import Dashboard.dashboard_blueprint as db


def _client():
    app = Flask(__name__)
    app.register_blueprint(db.create_dashboard_blueprint(".", lambda: None))
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_page_and_data(monkeypatch):
    monkeypatch.setattr(db, "build_dashboard_payload", lambda *_args, **_kwargs: {
        "summary": {"uniqueErrorTypes": 1, "totalErrorEvents": 2, "statusCodeCount": 1, "apiCount": 1},
        "byStatus": {"504": 2},
        "byApi": {"GET /x": 2},
        "rows": [],
        "filter": {"from": None, "to": None, "label": "All Time"},
    })

    client = _client()
    dashboard_page = client.get("/dashboard")
    assert dashboard_page.status_code == 200

    html = dashboard_page.get_data(as_text=True)
    # Interactive metric cards should remain wired for detail popups.
    assert 'id="card-unique"' in html
    assert 'id="card-total"' in html
    assert 'id="card-status"' in html
    assert 'id="card-api"' in html
    assert 'id="detailModal"' in html
    assert 'id="modalSearchInput"' in html
    assert "openDetailModal('unique')" in html
    assert "openDetailModal('total')" in html
    assert "openDetailModal('status')" in html
    assert "openDetailModal('api')" in html

    res = client.get("/api/dashboard-data")
    assert res.status_code == 200
    assert res.json["summary"]["totalErrorEvents"] == 2


def test_dashboard_pdf_route_when_reportlab_unavailable(monkeypatch):
    monkeypatch.setattr(db, "REPORTLAB_AVAILABLE", False)
    client = _client()
    res = client.get("/api/dashboard-report.pdf")
    assert res.status_code == 503


def test_dashboard_pdf_route_success(monkeypatch):
    monkeypatch.setattr(db, "REPORTLAB_AVAILABLE", True)
    monkeypatch.setattr(db, "build_dashboard_payload", lambda *_args, **_kwargs: {
        "summary": {"uniqueErrorTypes": 1, "totalErrorEvents": 2, "statusCodeCount": 1, "apiCount": 1},
        "byStatus": {"504": 2},
        "byApi": {"GET /x": 2},
        "rows": [],
        "filter": {"from": None, "to": None, "label": "All Time"},
    })
    monkeypatch.setattr(db, "build_dashboard_pdf", lambda *_args, **_kwargs: BytesIO(b"%PDF-1.4\n..."))

    client = _client()
    res = client.get("/api/dashboard-report.pdf")
    assert res.status_code == 200
    assert res.mimetype == "application/pdf"


def test_chat_insights_validation_and_error_paths(monkeypatch):
    client = _client()

    # invalid error context
    res = client.post("/api/chat-insights", json={"error": "bad", "history": []})
    assert res.status_code == 400

    # invalid history
    res = client.post("/api/chat-insights", json={"error": {}, "history": "bad"})
    assert res.status_code == 400

    monkeypatch.setattr(db, "BEDROCK_CHAT_AVAILABLE", False)
    res = client.post("/api/chat-insights", json={"error": {}, "history": []})
    assert res.status_code == 503


def test_chat_insights_success_and_exception(monkeypatch):
    monkeypatch.setattr(db, "BEDROCK_CHAT_AVAILABLE", True)
    monkeypatch.setattr(
        db,
        "generate_error_insight",
        lambda *_args, **_kwargs: ("ok", {"model_id": "m", "region": "us-east-1", "session_id": "s"}),
    )
    client = _client()

    res = client.post("/api/chat-insights", json={"error": {}, "message": "hi", "history": [], "sessionId": "s"})
    assert res.status_code == 200
    assert res.json["reply"] == "ok"

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(db, "generate_error_insight", raise_error)
    res = client.post("/api/chat-insights", json={"error": {}, "message": "hi", "history": []})
    assert res.status_code == 500
