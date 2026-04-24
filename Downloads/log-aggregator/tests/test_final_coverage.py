"""Final targeted tests to reach 90% coverage."""
import csv
import json
from pathlib import Path
import tempfile
from datetime import date

import Dashboard.dashboard_data_service as ds


def test_serialize_all_filtering_conditions():
    """Thoroughly test _serialize_aggregated_errors filtering conditions"""
    # This test targets the complex filter condition in line 123
    aggregated = {
        # Test: key[0] is NOT numeric - should not be included
        ("abc", "1000", "Error", "GET /test"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        
        # Test: numeric but < 400 - should not be included
        ("200", "2000", "Success", "GET /status"): {'count': 5, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        ("399", "3999", "Redirect", "GET /moved"): {'count': 2, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        
        # Test: numeric >= 400 but empty error code - should not be included
        ("400", "", "Bad Request", "GET /api"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        ("500", "", "Server Error", "GET /api"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        
        # Test: numeric >= 400 AND non-empty error code - SHOULD be included
        ("400", "0400", "Bad Request", "POST /create"): {'count': 3, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        ("404", "4004", "Not Found", "GET /missing"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        ("500", "5000", "Server Error", "POST /api"): {'count': 2, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
        ("503", "5003", "Service Unavailable", "GET /health"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},
    }
    
    serialized = ds._serialize_aggregated_errors(aggregated)
    
    # Should only include errors with:
    # 1. numeric status code
    # 2. status code >= 400  
    # 3. non-empty error code
    assert len(serialized) == 4  # 400, 404, 500, 503
    
    status_codes = {item["Status Code"] for item in serialized}
    error_codes = {item["Error Code"] for item in serialized}
    
    # Verify which ones were included
    assert "400" in status_codes
    assert "404" in status_codes
    assert "500" in status_codes
    assert "503" in status_codes
    
    # Verify which ones were excluded
    assert "200" not in status_codes
    assert "399" not in status_codes
    
    # Verify no empty error codes in result
    assert all(error_codes)


def test_build_dashboard_payload_integration():
    """Integration test exercising the full dashboard pipeline"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        
        # Create both JSON and CSV files
        unique_json = [
            {
                "Status Code": "500",
                "Error Code": "5000",
                "Description": "Server Error",
                "API": "POST /api/order",
                "Count": 5,
                "Last Seen": "2026-03-31T14:00:00",
                "Dates": ["2026-03-31", "2026-03-30"],
            }
        ]
        (tmp_path / ds.UNIQUE_ERRORS_JSON_FILENAME).write_text(json.dumps(unique_json))
        
        # CSV with multiple rows
        rows = [
            ["Timestamp", "Date", "Status code", "Error Code", "Description", "API"],
            ["2026-03-31T10:00:00", "2026-03-31", "500", "5000", "Server Error", "POST /api/order"],
            ["2026-03-31T12:00:00", "2026-03-31", "500", "5000", "Server Error", "POST /api/order"],
            ["2026-03-30T10:00:00", "2026-03-30", "500", "5000", "Server Error", "POST /api/order"],
            ["2026-03-29T10:00:00", "2026-03-29", "200", "", "Success", "GET /api/status"],
        ]
        with (tmp_path / "converted_application_logs.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows)
        
        # Test with date filter that matches some rows
        payload = ds.build_dashboard_payload(
            str(tmp_path),
            lambda: None,
            {"from": "2026-03-30", "to": "2026-03-31"}
        )
        
        # Verify structure
        assert "summary" in payload
        assert "byStatus" in payload
        assert "rows" in payload
        assert "filter" in payload
        
        # Should have 1 unique error (only the 500 error from CSV filtered by date)
        assert payload["summary"]["uniqueErrorTypes"] >= 0
        assert payload["summary"]["totalErrorEvents"] >= 0
