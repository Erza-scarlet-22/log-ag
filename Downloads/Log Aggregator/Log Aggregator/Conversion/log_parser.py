# Low-level log parsing utilities for the Log Aggregator conversion pipeline.
#
# Provides compiled regex patterns and helper functions used by log_to_csv_service
# to extract structured data (timestamps, API paths, error codes, descriptions)
# from raw application log lines.
#
# All symbols here are considered internal to the Conversion package; consumers
# should import from log_to_csv_service instead of this module directly.

import re
from typing import Dict, Optional

# ── Compiled regex patterns ───────────────────────────────────────────────────

# Strips ANSI colour/control escape sequences that may appear when the app runs
# in a colour-aware terminal and its output is redirected into the log file.
ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Matches a request-arrival log line that contains the source IP address.
# Capture group 1: "METHOD /path"
# Example: [2026-03-31T12:00:00] [INFO] POST /api/auth/token IP: 192.168.1.1
API_WITH_IP_PATTERN = re.compile(
    r"\[(?:INFO|WARNING|ERROR|DEBUG)\]\s+([A-Z]+\s+\S+)\s+IP:"
)

# Matches a response-completion log line that contains the HTTP status code.
# Capture group 1: "METHOD /path", group 2: "NNN"
# Example: [2026-03-31T12:00:01] [INFO] POST /api/auth/token Status Code: 401
STATUS_PATTERN = re.compile(
    r"\[(?:INFO|WARNING|ERROR|DEBUG)\]\s+([A-Z]+\s+\S+)\s+Status Code:\s*(\d{3})"
)

# Extracts the numeric error_code value from a Python-dict-style log payload.
# Example payload fragment: {'error_code': 6001, 'attempts': 1}
ERROR_CODE_PATTERN = re.compile(r"'error_code'\s*:\s*(\d+)")

# Extracts the ISO-8601 timestamp from the opening bracket of a log line.
# Example: [2026-03-31T12:00:00] → group 1 = "2026-03-31T12:00:00"
TIMESTAMP_PATTERN = re.compile(r"^\[([^\]]+)\]")


# ── Helper functions ──────────────────────────────────────────────────────────

def clean_line(line: str) -> str:
    """Remove ANSI escape sequences and strip surrounding whitespace."""
    return ANSI_ESCAPE_PATTERN.sub("", line).strip()


def extract_error_details(line: str) -> Dict[str, Optional[str]]:
    """Return the error_code and human-readable description from an ERROR/WARNING log line.

    Expected format:
        [timestamp] [ERROR] <description text> {'error_code': NNNN, ...}

    Returns a dict with keys 'error_code' and 'description'. Either value may be
    an empty string when the information cannot be parsed from the line.
    """
    parsed_details: Dict[str, Optional[str]] = {"error_code": "", "description": ""}

    # Skip past the first bracket group (timestamp).
    message_start = line.find("] ")
    if message_start == -1:
        return parsed_details

    # Skip past the second bracket group ([ERROR], [WARNING], etc.).
    level_end = line.find("] ", message_start + 2)
    if level_end == -1:
        return parsed_details

    message = line[level_end + 2:].strip()

    error_code_match = ERROR_CODE_PATTERN.search(message)
    if error_code_match:
        parsed_details["error_code"] = error_code_match.group(1)
        # Everything before the dict payload is the human-readable description.
        parsed_details["description"] = message[: error_code_match.start()].strip()
    else:
        parsed_details["description"] = message

    # Remove trailing punctuation artifacts left by the dict serialisation (e.g. " {,").
    if parsed_details["description"]:
        parsed_details["description"] = parsed_details["description"].rstrip(" {,")

    return parsed_details


def extract_timestamp(line: str) -> str:
    """Return the ISO-8601 timestamp string from the first bracket of a log line,
    or an empty string when no timestamp bracket is found."""
    match = TIMESTAMP_PATTERN.search(line)
    return match.group(1) if match else ""


def extract_date(line: str) -> str:
    """Return the date portion (YYYY-MM-DD) of the timestamp in a log line,
    or an empty string when no timestamp is present."""
    timestamp = extract_timestamp(line)
    return timestamp.split("T", 1)[0] if "T" in timestamp else ""
