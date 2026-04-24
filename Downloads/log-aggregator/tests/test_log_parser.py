from Conversion.log_parser import clean_line, extract_error_details, extract_timestamp, extract_date


def test_clean_line_removes_ansi_sequences():
    raw = "\x1b[31m[2026-03-31T12:00:00] [ERROR] Boom\x1b[0m"
    assert clean_line(raw) == "[2026-03-31T12:00:00] [ERROR] Boom"


def test_extract_error_details_with_error_code():
    line = "[2026-03-31T12:00:00] [ERROR] Something failed {'error_code': 9002, 'x': 1}"
    details = extract_error_details(line)
    assert details["error_code"] == "9002"
    assert details["description"] == "Something failed"


def test_extract_error_details_without_code_keeps_description():
    line = "[2026-03-31T12:00:00] [WARNING] Just a warning"
    details = extract_error_details(line)
    assert details["error_code"] == ""
    assert details["description"] == "Just a warning"


def test_extract_timestamp_and_date():
    line = "[2026-03-31T16:01:16] [INFO] GET /api/status Status Code: 200"
    assert extract_timestamp(line) == "2026-03-31T16:01:16"
    assert extract_date(line) == "2026-03-31"


def test_extract_error_details_returns_empty_for_missing_timestamp_bracket():
    details = extract_error_details("ERROR message without bracket")
    assert details == {"error_code": "", "description": ""}


def test_extract_error_details_returns_empty_for_missing_level_bracket():
    details = extract_error_details("[2026-03-31T16:01:16] Message missing level bracket")
    assert details == {"error_code": "", "description": ""}
