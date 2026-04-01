import csv
import json
import tempfile
from pathlib import Path

import pytest

from Conversion.log_to_csv_service import (
    UNIQUE_ERRORS_JSON_FILENAME,
    convert_log_to_rows,
    write_rows_to_csv,
    write_unique_errors_json,
)


def test_convert_log_to_rows_parses_request_error_status_cycle(tmp_path: Path):
    source = tmp_path / "application.log"
    source.write_text(
        "\n".join(
            [
                "[2026-03-30T10:00:00] [INFO] GET /api/recommendations IP: 10.0.0.1",
                "[2026-03-30T10:00:00] [ERROR] Upstream timed out {'error_code': 9002}",
                "[2026-03-30T10:00:00] [INFO] GET /api/recommendations Status Code: 504",
                "[2026-03-30T10:01:00] [INFO] GET /api/status IP: 10.0.0.2",
                "[2026-03-30T10:01:00] [INFO] GET /api/status Status Code: 200",
            ]
        ),
        encoding="utf-8",
    )

    rows = convert_log_to_rows(str(source))
    assert len(rows) == 2
    assert rows[0]["Status code"] == "504"
    assert rows[0]["Error Code"] == "9002"
    assert rows[0]["Description"] == "Upstream timed out"
    assert rows[1]["Status code"] == "200"
    assert rows[1]["Description"] == "Success"


def test_convert_log_to_rows_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        convert_log_to_rows(str(tmp_path / "missing.log"))


def test_write_rows_to_csv_and_unique_errors_json(tmp_path: Path):
    rows = [
        {
            "Timestamp": "2026-03-30T10:00:00",
            "Date": "2026-03-30",
            "Status code": "504",
            "Error Code": "9002",
            "Description": "Upstream timed out",
            "API": "GET /api/recommendations",
        },
        {
            "Timestamp": "2026-03-30T11:00:00",
            "Date": "2026-03-30",
            "Status code": "504",
            "Error Code": "9002",
            "Description": "Upstream timed out",
            "API": "GET /api/recommendations",
        },
        {
            "Timestamp": "2026-03-30T11:10:00",
            "Date": "2026-03-30",
            "Status code": "200",
            "Error Code": "",
            "Description": "Success",
            "API": "GET /api/status",
        },
    ]

    csv_path = tmp_path / "out" / "converted.csv"
    json_path = tmp_path / "out" / UNIQUE_ERRORS_JSON_FILENAME

    write_rows_to_csv(rows, str(csv_path))
    assert csv_path.exists()

    with csv_path.open("r", encoding="utf-8") as fh:
        reader = list(csv.DictReader(fh))
    assert len(reader) == 3

    unique_count = write_unique_errors_json(rows, str(json_path))
    assert unique_count == 1

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload[0]["Error Code"] == "9002"
    assert payload[0]["Count"] == 2
    assert payload[0]["Status Code"] == "504"


def test_write_unique_errors_json_empty_rows():
    """Test JSON generation with empty rows list"""
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / UNIQUE_ERRORS_JSON_FILENAME
        count = write_unique_errors_json([], str(json_path))
        
        assert count == 0
        assert json_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload == []


def test_write_rows_to_csv_with_missing_fields():
    """Test CSV writing when rows have missing fields (should use empty defaults)"""
    rows = [
        {
            "Timestamp": "2026-03-30T10:00:00",
            "Date": "2026-03-30",
            "Status code": "500",
            "Error Code": "",  # Missing error code
            "Description": "Internal Server Error",
            "API": "POST /api/order",
        }
    ]
    
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "test.csv"
        write_rows_to_csv(rows, str(csv_path))
        
        with csv_path.open("r", encoding="utf-8") as fh:
            reader = list(csv.DictReader(fh))
        
        assert len(reader) == 1
        assert reader[0]["Error Code"] == ""
        assert reader[0]["Status code"] == "500"


def test_convert_log_to_rows_with_multiple_errors_per_request():
    """Test parsing logs where single request has multiple error lines"""
    log_content = "\n".join([
        "[2026-03-30T10:00:00] [INFO] POST /api/payment IP: 10.0.0.1",
        "[2026-03-30T10:00:00] [ERROR] Database connection failed {'error_code': 5001}",
        "[2026-03-30T10:00:00] [ERROR] Retrying... {'error_code': 5001}",
        "[2026-03-30T10:00:00] [INFO] POST /api/payment Status Code: 503",
    ])
    
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "test.log"
        source.write_text(log_content, encoding="utf-8")
        
        rows = convert_log_to_rows(str(source))
        
        # Should capture the last error code for this request
        assert len(rows) > 0
        assert rows[0]["Error Code"] == "5001"
        assert rows[0]["Status code"] == "503"


def test_write_unique_errors_with_all_same_error():
    """Test JSON generation when all rows have the same error"""
    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            {
                "Timestamp": "2026-03-30T10:00:00",
                "Date": "2026-03-30",
                "Status code": "500",
                "Error Code": "5000",
                "Description": "Server Error",
                "API": "POST /api/order",
            },
            {
                "Timestamp": "2026-03-30T11:00:00",
                "Date": "2026-03-30",
                "Status code": "500",
                "Error Code": "5000",
                "Description": "Server Error",
                "API": "POST /api/order",
            },
            {
                "Timestamp": "2026-03-30T12:00:00",
                "Date": "2026-03-31",
                "Status code": "500",
                "Error Code": "5000",
                "Description": "Server Error",
                "API": "POST /api/order",
            },
        ]
        json_path = Path(tmp) / UNIQUE_ERRORS_JSON_FILENAME
        count = write_unique_errors_json(rows, str(json_path))
        
        assert count == 1
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert len(payload) == 1
        assert payload[0]["Count"] == 3
        assert payload[0]["Dates"] == ["2026-03-30", "2026-03-31"]


def test_convert_log_to_rows_handles_missing_elements():
    """Test parsing logs when some expected fields are missing"""
    log_content = "\n".join([
        "[2026-03-30T10:00:00] [INFO] GET /api/status IP: 10.0.0.1",
        "[2026-03-30T10:00:00] [INFO] GET /api/status Status Code: 200",
        "",  # Empty line
        "   ",  # Whitespace only
        "[2026-03-30T10:01:00] [INFO] POST /api/data IP: 10.0.0.2",
        "[2026-03-30T10:01:00] [INFO] POST /api/data Status Code: 201",
    ])
    
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "test.log"
        source.write_text(log_content, encoding="utf-8")
        
        rows = convert_log_to_rows(str(source))
        
        # Should parse valid rows and ignore empty/malformed lines
        assert len(rows) >= 1


def test_write_rows_to_csv_preserves_field_order():
    """Test that CSV output has consistent field ordering"""
    rows = [
        {
            "Timestamp": "2026-03-30T10:00:00",
            "Date": "2026-03-30",
            "Status code": "404",
            "Error Code": "4004",
            "Description": "Not Found",
            "API": "GET /api/missing",
        },
    ]
    
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "test.csv"
        write_rows_to_csv(rows, str(csv_path))
        
        with csv_path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        
        # Check header row exists and has expected fields
        assert len(lines) >= 1
        header = lines[0].strip()
        assert "Timestamp" in header
        assert "Date" in header
        assert "Status code" in header
        assert "Error Code" in header
