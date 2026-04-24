import csv
import json
from datetime import date
from pathlib import Path

import Dashboard.dashboard_data_service as ds


def _write_unique_json(conversion_dir: Path):
    payload = [
        {
            "Status Code": "504",
            "Error Code": "9002",
            "Description": "Upstream timeout",
            "API": "GET /api/recommendations",
            "Count": 4,
            "Last Seen": "2026-03-31T10:00:00",
            "Dates": ["2026-03-31"],
        },
        {
            "Status Code": "503",
            "Error Code": "9001",
            "Description": "Email service unavailable",
            "API": "POST /api/notifications/email",
            "Count": 2,
            "Last Seen": "2026-03-30T09:00:00",
            "Dates": ["2026-03-30"],
        },
    ]
    (conversion_dir / ds.UNIQUE_ERRORS_JSON_FILENAME).write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(conversion_dir: Path):
    rows = [
        ["Timestamp", "Date", "Status code", "Error Code", "Description", "API"],
        ["2026-03-31T10:00:00", "2026-03-31", "504", "9002", "Upstream timeout", "GET /api/recommendations"],
        ["2026-03-30T09:00:00", "2026-03-30", "503", "9001", "Email service unavailable", "POST /api/notifications/email"],
        ["2026-03-15T12:00:00", "2026-03-15", "200", "", "Success", "GET /api/status"],
    ]
    with (conversion_dir / "converted_application_logs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)


def test_build_dashboard_payload_all_time_uses_prebuilt_json(tmp_path: Path):
    _write_unique_json(tmp_path)

    called = {"count": 0}

    def run_conversion_outputs():
        called["count"] += 1

    payload = ds.build_dashboard_payload(str(tmp_path), run_conversion_outputs, {})
    assert called["count"] == 1
    assert payload["summary"]["uniqueErrorTypes"] == 2
    assert payload["summary"]["totalErrorEvents"] == 6
    assert payload["filter"]["label"] == "All Time"
    assert payload["byStatus"]["504"] == 4


def test_build_dashboard_payload_with_date_filter_reads_csv(tmp_path: Path):
    _write_unique_json(tmp_path)
    _write_csv(tmp_path)

    payload = ds.build_dashboard_payload(
        str(tmp_path),
        lambda: None,
        {"from": "2026-03-31", "to": "2026-03-31"},
    )

    assert payload["summary"]["uniqueErrorTypes"] == 1
    assert payload["summary"]["totalErrorEvents"] == 1
    assert payload["rows"][0]["Error Code"] == "9002"
    assert payload["filter"]["label"] == "2026-03-31 to 2026-03-31"


def test_resolve_date_filters_presets(monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)

    monkeypatch.setattr(ds, "date", FakeDate)

    frm, to, label = ds._resolve_date_filters({"preset": "week"})
    assert (frm.isoformat(), to.isoformat(), label) == ("2026-03-25", "2026-03-31", "Last 7 Days")

    frm, to, label = ds._resolve_date_filters({"preset": "quarter"})
    assert (frm.isoformat(), to.isoformat(), label) == ("2026-01-01", "2026-03-31", "Last 90 Days")


def test_build_dashboard_payload_csv_file_not_found_fallback(tmp_path: Path):
    """Test fallback when CSV file missing but JSON exists"""
    _write_unique_json(tmp_path)
    # CSV file intentionally not created
    
    payload = ds.build_dashboard_payload(
        str(tmp_path),
        lambda: None,
        {"from": "2026-03-31", "to": "2026-03-31"}
    )
    
    # Should still return payload from JSON despite missing CSV
    assert payload["summary"]["uniqueErrorTypes"] >= 0


def test_build_dashboard_payload_empty_csv(tmp_path: Path):
    """Test with CSV containing only headers"""
    _write_unique_json(tmp_path)
    
    # Write empty CSV (headers only)
    with (tmp_path / "converted_application_logs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Timestamp", "Date", "Status code", "Error Code", "Description", "API"])
    
    payload = ds.build_dashboard_payload(
        str(tmp_path),
        lambda: None,
        {"from": "2026-03-31", "to": "2026-03-31"}
    )
    
    assert payload["summary"]["totalErrorEvents"] == 0
    assert payload["rows"] == []


def test_build_dashboard_payload_date_boundary_conditions(tmp_path: Path):
    """Test date filtering with rows exactly at boundary dates"""
    _write_unique_json(tmp_path)
    _write_csv(tmp_path)
    
    # Filter from 2026-03-30 to 2026-03-31 (should include both boundary dates)
    payload = ds.build_dashboard_payload(
        str(tmp_path),
        lambda: None,
        {"from": "2026-03-30", "to": "2026-03-31"}
    )
    
    assert payload["summary"]["totalErrorEvents"] == 2  # Both 9002 and 9001


def test_resolve_date_filters_with_invalid_date_strings(monkeypatch):
    """Test handling of unparseable date strings"""
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)
    
    monkeypatch.setattr(ds, "date", FakeDate)
    
    # Invalid dates should fall back to default
    _, _, label = ds._resolve_date_filters({"from": "invalid-date", "to": "2026-03-31"})
    # Should fall back to default behavior
    assert label == "All Time"


def test_resolve_date_filters_today_preset(monkeypatch):
    """Test 'today' preset filter"""
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)
    
    monkeypatch.setattr(ds, "date", FakeDate)
    
    frm, to, label = ds._resolve_date_filters({"preset": "today"})
    assert (frm, to, label) == (date(2026, 3, 31), date(2026, 3, 31), "Today")


def test_resolve_date_filters_month_preset(monkeypatch):
    """Test 'month' preset filter"""
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 3, 31)
    
    monkeypatch.setattr(ds, "date", FakeDate)
    
    frm, to, label = ds._resolve_date_filters({"preset": "month"})
    assert (frm.isoformat(), to.isoformat(), label) == ("2026-03-02", "2026-03-31", "Last 30 Days")


def test_read_unique_errors_data_missing_json_file(tmp_path: Path):
    """Test handling when unique errors JSON file is missing"""
    # No JSON file created
    result = ds._read_unique_errors_data(str(tmp_path))
    assert result == []


def test_read_unique_errors_data_invalid_json(tmp_path: Path):
    """Test handling when JSON file contains invalid JSON"""
    json_path = tmp_path / ds.UNIQUE_ERRORS_JSON_FILENAME
    json_path.write_text("invalid json {{{", encoding="utf-8")
    
    result = ds._read_unique_errors_data(str(tmp_path))
    assert result == []  # Should return empty list on parse error


def test_read_unique_errors_data_non_list_json(tmp_path: Path):
    """Test handling when JSON file contains non-list data"""
    json_path = tmp_path / ds.UNIQUE_ERRORS_JSON_FILENAME
    json_path.write_text('{"key": "value"}', encoding="utf-8")  # Dict, not list
    
    result = ds._read_unique_errors_data(str(tmp_path))
    assert result == []  # Should return empty list for non-list JSON


def test_row_is_in_range_boundary_conditions():
    """Test date range boundary conditions"""
    test_date = date(2026, 3, 15)
    
    # Within range
    assert ds._row_is_in_range(test_date, date(2026, 3, 1), date(2026, 3, 31))
    
    # Before range
    assert not ds._row_is_in_range(test_date, date(2026, 3, 20), date(2026, 3, 31))
    
    # After range
    assert not ds._row_is_in_range(test_date, date(2026, 3, 1), date(2026, 3, 10))
    
    # No from date
    assert ds._row_is_in_range(test_date, None, date(2026, 3, 31))
    
    # No to date
    assert ds._row_is_in_range(test_date, date(2026, 3, 1), None)


def test_serialize_aggregated_errors_filters_status_code():
    """Test that serialize only includes 400+ errors with non-empty error codes"""
    aggregated = {
        ("200", "", "Success", "GET /api/status"): {'count': 5, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T10:00:00"},  # No error code
        ("500", "5000", "Error", "GET /api/error"): {'count': 2, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T09:00:00"},  # Valid error
        ("404", "4004", "Not Found", "GET /api/missing"): {'count': 1, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T08:00:00"},  # Valid error
        ("302", "3002", "Redirect", "GET /api/moved"): {'count': 3, 'dates': {"2026-03-31"}, 'last_seen': "2026-03-31T07:00:00"},  # < 400
    }
    
    serialized = ds._serialize_aggregated_errors(aggregated)
    
    # Should only include errors with status >= 400 and non-empty error code
    assert len(serialized) == 2  # Only 500 and 404
    
    status_codes = [e["Status Code"] for e in serialized]
    error_codes = [e["Error Code"] for e in serialized]
    
    assert "500" in status_codes
    assert "404" in status_codes
    assert "200" not in status_codes
    assert "302" not in status_codes
    
    assert "" not in error_codes  # All error codes non-empty


def test_collect_unique_errors_with_unparseable_dates(tmp_path: Path):
    """Test CSV processing when some rows have invalid dates"""
    _write_unique_json(tmp_path)
    
    # Write CSV with one valid and one invalid date
    rows = [
        ["Timestamp", "Date", "Status code", "Error Code", "Description", "API"],
        ["2026-03-31T10:00:00", "2026-03-31", "504", "9002", "Timeout", "GET /api/recommendations"],
        ["invalid-date", "BADDATE", "500", "5000", "Error", "GET /api/error"],
    ]
    with (tmp_path / "converted_application_logs.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)
    
    # Filter to a date range
    result = ds._collect_unique_errors(
        str(tmp_path),
        date(2026, 3, 31),
        date(2026, 3, 31)
    )
    
    # Should return a list and not crash on malformed rows.
    assert isinstance(result, list)


def test_update_aggregated_error_with_various_timestamps():
    """Test aggregation with different timestamp scenarios"""
    aggregated = {}
    row = {
        "Status code": "500",
        "Error Code": "5000", 
        "Description": "Error",
        "API": "GET /test"
    }
    
    # First call with timestamps
    ds._update_aggregated_error(aggregated, row, "2026-03-31", "2026-03-31T10:00:00")
    assert aggregated[("500", "5000", "Error", "GET /test")]["count"] == 1
    assert aggregated[("500", "5000", "Error", "GET /test")]["last_seen"] == "2026-03-31T10:00:00"
    
    # Second call - same row should increment
    ds._update_aggregated_error(aggregated, row, "2026-03-31", "2026-03-31T11:00:00")
    assert aggregated[("500", "5000", "Error", "GET /test")]["count"] == 2
    assert aggregated[("500", "5000", "Error", "GET /test")]["last_seen"] == "2026-03-31T11:00:00"
    
    # Third call with empty timestamp - should keep previous
    ds._update_aggregated_error(aggregated, row, "2026-03-31", "")
    assert aggregated[("500", "5000", "Error", "GET /test")]["last_seen"] == "2026-03-31T11:00:00"
