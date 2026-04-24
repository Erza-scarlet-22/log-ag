from flask import abort

import Application.app as app_module
import Application.logger as logger_module


def test_logger_helpers_do_not_raise():
    logger_module.info("info")
    logger_module.warn("warn", {"x": 1})
    logger_module.error("error")
    logger_module.debug("debug", {"k": "v"})


def test_main_app_registered_routes_and_error_handlers(monkeypatch):
    # Avoid conversion side effects during endpoint calls.
    monkeypatch.setattr(app_module, "run_conversion_outputs", lambda: None)

    app = app_module.app
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)

    if "_raise500" not in app.view_functions:
        app.add_url_rule("/_raise500", "_raise500", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    if "_raise503" not in app.view_functions:
        app.add_url_rule("/_raise503", "_raise503", lambda: abort(503))

    client = app.test_client()

    # route from registered core blueprint
    assert client.get("/").status_code == 200

    # 404 handler
    res = client.get("/no-such-endpoint")
    assert res.status_code == 404
    assert res.json["error_code"] == 4004

    # 405 handler
    res = client.get("/api/logs")  # only POST/GET exist; GET exists. use PUT for 405
    assert res.status_code == 200
    res = client.put("/api/logs", json={"message": "x"})
    assert res.status_code == 405
    assert res.json["error_code"] == 4005

    # 500 handler
    res = client.get("/_raise500")
    assert res.status_code == 500
    assert res.json["error_code"] == 5000

    # 503 handler
    res = client.get("/_raise503")
    assert res.status_code == 503
    assert res.json["error_code"] == 5003
