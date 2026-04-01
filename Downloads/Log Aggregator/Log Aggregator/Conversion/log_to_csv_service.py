# Log-to-CSV conversion service for the Log Aggregator pipeline.
#
# Parses the structured application log produced by logger.py and outputs:
#   - A flat CSV of every API transaction  (converted_application_logs.csv)
#   - A deduplicated JSON of unique error types with occurrence counts (unique_errors.json)
#
# Parsing helpers and compiled regex patterns live in log_parser.py; this module
# contains only the public service functions and a CLI entry point.
#
# Public API:
#   convert_log_to_rows(source_log_path)              → List[Dict[str, str]]
#   write_rows_to_csv(rows, output_csv_path)           → None
#   write_unique_errors_json(rows, output_json_path)   → int
#
# Run as a script:
#   python log_to_csv_service.py   — processes the default log path.

import csv
import json
import os
from typing import Dict, List

from log_parser import (  # type: ignore[reportMissingImports]
    clean_line, extract_error_details, extract_timestamp, extract_date,
    API_WITH_IP_PATTERN, STATUS_PATTERN,
)


UNIQUE_ERRORS_JSON_FILENAME = "unique_errors.json"


def convert_log_to_rows(source_log_path: str) -> List[Dict[str, str]]:
    """Parse every API request/response cycle in the log file into a row dict.

    Each row contains: Timestamp, Date, Status code, Error Code, Description, API.

    The parser tracks state across the three log lines that make up one request cycle:
      1. Request arrival line  → sets current_api, current_timestamp, current_date.
      2. ERROR/WARNING line    → sets current_error_code, current_description.
      3. Status code line      → emits the row and resets all state.
    """
    if not os.path.exists(source_log_path):
        raise FileNotFoundError(f"Log file not found: {source_log_path}")

    rows: List[Dict[str, str]] = []

    # State variables that accumulate context across the three lines of one request cycle.
    current_api         = ""
    current_error_code  = ""
    current_description = ""
    current_date        = ""
    current_timestamp   = ""

    with open(source_log_path, "r", encoding="utf-8", errors="ignore") as log_file:
        for raw_line in log_file:
            line = clean_line(raw_line)
            if not line:
                continue

            # ── 1. Request arrival line ──────────────────────────────────────
            api_ip_match = API_WITH_IP_PATTERN.search(line)
            if api_ip_match:
                current_api         = api_ip_match.group(1)
                current_error_code  = ""
                current_description = ""
                current_timestamp   = extract_timestamp(line)
                current_date        = extract_date(line)
                continue

            # ── 2. Error / warning detail line ───────────────────────────────
            if "[ERROR]" in line or "[WARNING]" in line:
                error_details = extract_error_details(line)
                if error_details["error_code"]:
                    current_error_code = error_details["error_code"] or ""
                if error_details["description"]:
                    current_description = error_details["description"] or ""
                continue

            # ── 3. Response status line — emit the row and reset state ────────
            status_match = STATUS_PATTERN.search(line)
            if status_match:
                api_from_status = status_match.group(1)
                status_code     = status_match.group(2)

                # Fall back to values extracted from the status line itself when
                # the preceding request context is missing.
                api_called       = current_api       or api_from_status
                timestamp_value  = current_timestamp or extract_timestamp(line)
                date_value       = current_date      or extract_date(line)
                description      = current_description or (
                    "Success" if status_code.startswith("2") else "No error description available"
                )

                rows.append({
                    "Timestamp":   timestamp_value,
                    "Date":        date_value,
                    "Status code": status_code,
                    "Error Code":  current_error_code,
                    "Description": description,
                    "API":         api_called,
                })

                # Reset all state so the next cycle starts clean.
                current_api = current_error_code = current_description = ""
                current_date = current_timestamp = ""

    return rows


def write_rows_to_csv(rows: List[Dict[str, str]], output_csv_path: str) -> None:
    """Write the list of row dicts to a CSV file at the given path.
    Creates any missing parent directories automatically."""
    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)
    with open(output_csv_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["Timestamp", "Date", "Status code", "Error Code", "Description", "API"],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_unique_errors_json(rows: List[Dict[str, str]], output_json_path: str) -> int:
    """Aggregate rows into a deduplicated list of unique error types and write to JSON.

    Only rows with HTTP status >= 400 and a non-empty error code are included.
    Each unique (status_code, error_code, description, api) combination is counted
    and its distinct occurrence dates and most-recent timestamp are tracked.

    Returns the number of unique error entries written.
    """
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)

    # key: (status_code, error_code, description, api)
    # value: {count, dates (set), last_seen (str)}
    aggregated: Dict[tuple, dict] = {}

    for row in rows:
        status_code_value = row.get("Status code", "")
        error_code_value  = row.get("Error Code",  "")

        # Skip successful responses and rows without an error code.
        if not status_code_value.isdigit() or int(status_code_value) < 400:
            continue
        if not error_code_value:
            continue

        key = (
            status_code_value,
            error_code_value,
            row.get("Description", ""),
            row.get("API", ""),
        )
        if key not in aggregated:
            aggregated[key] = {"count": 0, "dates": set(), "last_seen": ""}
        aggregated[key]["count"] += 1
        row_date = row.get("Date", "")
        row_timestamp = row.get("Timestamp", "")
        if row_date:
            aggregated[key]["dates"].add(row_date)
        # Track the most recent occurrence; prefer full timestamp, fall back to date.
        if row_timestamp and row_timestamp > aggregated[key]["last_seen"]:
            aggregated[key]["last_seen"] = row_timestamp
        elif row_date and row_date > aggregated[key]["last_seen"]:
            aggregated[key]["last_seen"] = row_date

    unique_errors = [
        {
            "Status Code": status_code,
            "Error Code":  error_code,
            "Description": description,
            "API":         api,
            "Count":       meta["count"],
            "Last Seen":   meta["last_seen"],
            "Dates":       sorted(meta["dates"]),
        }
        for (status_code, error_code, description, api), meta in sorted(aggregated.items())
    ]

    with open(output_json_path, "w", encoding="utf-8") as json_file:
        json.dump(unique_errors, json_file, indent=2)

    return len(unique_errors)


def main() -> None:
    """CLI entry point: convert the default application log to CSV and JSON."""
    from dotenv import load_dotenv
    load_dotenv()
    
    conversion_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.getenv('LOGS_DIRECTORY', 'logs')
    log_filename = os.getenv('LOG_FILENAME', 'application.log')
    source_log     = os.path.abspath(os.path.join(conversion_dir, "..", "Application", logs_dir, log_filename))
    output_csv     = os.path.join(conversion_dir, "converted_application_logs.csv")
    output_unique_errors_json = os.path.join(conversion_dir, UNIQUE_ERRORS_JSON_FILENAME)

    rows = convert_log_to_rows(source_log)
    write_rows_to_csv(rows, output_csv)
    unique_error_count = write_unique_errors_json(rows, output_unique_errors_json)

    print(f"CSV generated successfully: {output_csv}")
    print(f"Total rows written: {len(rows)}")
    print(f"Unique errors JSON generated successfully: {output_unique_errors_json}")
    print(f"Total unique entries written: {unique_error_count}")


if __name__ == "__main__":
    main()
