from pathlib import Path

from flask import Flask

from Application.routes.core import core_bp
from Application.routes.payments import payments_bp
from Application.routes.auth import auth_bp
from Application.routes.orders import orders_bp
from Application.routes.users import users_bp
from Application.routes.infrastructure import infrastructure_bp
from Application.routes.simulator import create_simulator_blueprint


def _client_with_blueprints(tmp_path: Path):
    app = Flask(__name__)
    app.register_blueprint(core_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(infrastructure_bp)
    app.register_blueprint(create_simulator_blueprint(str(tmp_path), "application.log", lambda: None))
    app.config["TESTING"] = True
    return app.test_client()


def test_core_routes(tmp_path: Path):
    client = _client_with_blueprints(tmp_path)

    res = client.get("/")
    assert res.status_code == 200

    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json["status"] == "healthy"

    res = client.post("/api/logs", json={"message": "hello", "level": "debug"})
    assert res.status_code == 201

    res = client.post("/api/logs", json={})
    assert res.status_code == 400


def test_core_get_logs_file_error_paths(tmp_path: Path, monkeypatch):
    client = _client_with_blueprints(tmp_path)

    import builtins

    def raise_file_not_found(*_args, **_kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(builtins, "open", raise_file_not_found)
    res = client.get("/api/logs")
    assert res.status_code == 500
    assert res.json["error_code"] == 1001

    def raise_generic(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(builtins, "open", raise_generic)
    res = client.get("/api/logs")
    assert res.status_code == 500
    assert res.json["error_code"] == 1000


def test_error_simulation_routes(tmp_path: Path):
    client = _client_with_blueprints(tmp_path)

    assert client.post("/api/payments/charge", json={}).status_code == 402
    assert client.post("/api/payments/charge", json={"simulate": "gateway_timeout"}).status_code == 503
    assert client.post("/api/payments/refund", json={}).status_code == 422

    assert client.post("/api/auth/token", json={}).status_code == 401
    assert client.post("/api/auth/token", json={"simulate": "mfa_required"}).status_code == 401
    assert client.post("/api/auth/refresh", json={}).status_code == 401
    assert client.post("/api/auth/login", json={}).status_code == 429

    assert client.post("/api/orders", json={}).status_code == 409
    assert client.get("/api/orders/abc").status_code == 404
    assert client.delete("/api/orders/abc").status_code == 409

    assert client.post("/api/users/register", json={"email": "x@x.com"}).status_code == 409
    assert client.put("/api/users/profile", json={}).status_code == 422

    assert client.post("/api/notifications/email", json={}).status_code == 503
    assert client.get("/api/recommendations").status_code == 504
    assert client.post("/api/inventory/sync", json={}).status_code == 503
    assert client.post("/api/fulfillment/dispatch", json={}).status_code == 502


def test_simulator_routes(tmp_path: Path):
    client = _client_with_blueprints(tmp_path)

    res = client.post("/api/simulate-traffic")
    assert res.status_code == 200
    assert res.json["events_seeded"] > 0

    # validate: empty payload
    assert client.post("/api/validate", json={}).status_code == 400

    # validate: missing fields
    assert client.post("/api/validate", json={"name": "A"}).status_code == 400

    # validate: bad email
    assert client.post("/api/validate", json={"name": "A", "email": "bad", "age": 30}).status_code == 400

    # validate: non-integer age
    assert client.post("/api/validate", json={"name": "A", "email": "a@b.com", "age": "x"}).status_code == 400

    # validate: out-of-range age
    assert client.post("/api/validate", json={"name": "A", "email": "a@b.com", "age": 999}).status_code == 400

    # validate: success
    assert client.post("/api/validate", json={"name": "A", "email": "a@b.com", "age": 30}).status_code == 200

    log_file = tmp_path / "logs" / "application.log"
    assert log_file.exists()


def test_core_create_log_validation_and_level_fallback(tmp_path: Path):
    client = _client_with_blueprints(tmp_path)

    # Non-string message should be rejected.
    res = client.post("/api/logs", json={"message": 123})
    assert res.status_code == 400
    assert "Message must be a string" in res.json["error"]

    # Overly long message should be rejected.
    res = client.post("/api/logs", json={"message": "x" * 10001})
    assert res.status_code == 400
    assert "at most 10000" in res.json["error"]

    # Unknown level should fall back to info and still succeed.
    res = client.post("/api/logs", json={"message": "ok", "level": "trace"})
    assert res.status_code == 201
    assert res.json["success"] is True


def test_core_get_logs_invalid_query_defaults(tmp_path: Path, monkeypatch):
    client = _client_with_blueprints(tmp_path)

    logs_dir = tmp_path / "custom_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "application.log").write_text("line-a\n\nline-b\n", encoding="utf-8")

    monkeypatch.setenv("LOGS_DIRECTORY", str(logs_dir))

    # Invalid page/per_page should use fallback defaults (1 and 500).
    res = client.get("/api/logs?page=abc&per_page=xyz")
    assert res.status_code == 200
    assert res.json["page"] == 1
    assert res.json["per_page"] == 500
    assert res.json["count"] == 2
