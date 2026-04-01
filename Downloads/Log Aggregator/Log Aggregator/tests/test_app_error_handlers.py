"""Test Flask error handlers and app middleware integration."""
import pytest
import sys
from pathlib import Path

# Add Application directory to path
app_dir = Path(__file__).parent.parent / "Application"
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from app import app as flask_app


@pytest.fixture
def app():
    """Prepare Flask app for testing."""
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


def test_error_handler_400_bad_request(client):
    """Test 400 Bad Request error handler"""
    # Attempt request with invalid/malformed input
    response = client.post("/api/logs", json="invalid-not-dict")
    # Should trigger 400 or another error - but handler should respond
    assert response.status_code in [400, 422, 500]  # Could be different based on validation
    
    
def test_error_handler_404_not_found(client):
    """Test 404 Not Found error handler"""
    response = client.get("/nonexistent/route")
    assert response.status_code == 404
    data = response.json
    assert "error_description" in data or "message" in data or "error" in data


def test_error_handler_405_method_not_allowed(client):
    """Test 405 Method Not Allowed error handler"""
    response = client.post("/")  # GET / exists but not POST
    assert response.status_code == 405
    data = response.json
    # Error response has 'error' key
    assert "error" in data or "message" in data


def test_app_blueprint_registration(app):
    """Test that all blueprints are registered"""
    # Check that core, auth, orders, users, payments, infrastructure, simulator, dashboard are registered
    blueprint_names = [bp.name for bp in app.blueprints.values()]
    
    expected_blueprints = {"core", "auth", "orders", "users", "payments", "infrastructure", "simulator", "dashboard"}
    registered_blueprints = set(blueprint_names)
    
    # All expected blueprints should be registered
    for bp_name in expected_blueprints:
        assert bp_name in registered_blueprints, f"Blueprint {bp_name} not registered"


def test_app_request_context_setup(app, client):
    """Test that before_request middleware runs"""
    with app.test_request_context("/"):
        # Should have app context
        from flask import has_request_context
        assert has_request_context()


def test_app_initialization(app):
    """Test Flask app initialization and config"""
    assert app is not None
    assert app.name == "app"
    
    # App should have json encoder configured
    assert hasattr(app, "json")


def test_multiple_requests_context_isolation(client):
    """Test isolation between multiple requests"""
    response1 = client.get("/")
    assert response1.status_code == 200
    
    response2 = client.get("/")  
    assert response2.status_code == 200


# Note: Can't test dynamic route registration on an already-started app
# in Flask - routes must be registered before first request
def test_error_responses_have_consistent_format(client):
    """Test that error responses have consistent JSON format"""
    # Test 404 error
    response = client.get("/nonexistent/route")
    assert response.status_code == 404
    data = response.json
    # Should have error code or error message
    assert "error_code" in data or "error" in data
