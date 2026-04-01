# Dashboard data service for the Log Aggregator.
#
# Responsible for:
#   - Loading the pre-aggregated unique-errors JSON artefact produced by the
#     conversion pipeline.
#   - Resolving date-range filter presets ('today', 'week', 'month', 'quarter')
#     or custom ISO date bounds into concrete date objects.
#   - Re-aggregating the CSV when a date filter is active (date-filtered fast path
#     bypasses the pre-built JSON and reads the CSV directly).
#   - Building the complete dashboard payload dict consumed by the front-end and
#     the PDF export service.
#
# Public API:
#   build_dashboard_payload(conversion_dir, run_conversion_outputs, request_args) → dict
#
# Shared field-name constants (also imported by dashboard_pdf_service):
#   STATUS_CODE_KEY, ERROR_CODE_KEY, DESCRIPTION_KEY, API_KEY, COUNT_KEY, LAST_SEEN_KEY

import csv
import json
import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# ── Shared field-name constants ───────────────────────────────────────────────
# Defined here once and re-exported so dashboard_blueprint and dashboard_pdf_service
# use identical keys when accessing row dicts.
STATUS_CODE_KEY = 'Status Code'
ERROR_CODE_KEY  = 'Error Code'
DESCRIPTION_KEY = 'Description'
API_KEY         = 'API'
COUNT_KEY       = 'Count'
LAST_SEEN_KEY   = 'Last Seen'
UNIQUE_ERRORS_JSON_FILENAME = 'unique_errors.json'
LEGACY_UNIQUE_ERRORS_JSON_FILENAME = 'unique errors.json'


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_unique_errors_data(conversion_dir: str) -> List[dict]:
    """Load the pre-aggregated unique-errors list from the JSON artefact.
    Returns an empty list when the file is absent or unreadable."""
    candidate_paths = [
        os.path.join(conversion_dir, UNIQUE_ERRORS_JSON_FILENAME),
        os.path.join(conversion_dir, LEGACY_UNIQUE_ERRORS_JSON_FILENAME),
    ]

    for json_path in candidate_paths:
        if not os.path.exists(json_path):
            continue
        try:
            with open(json_path, 'r', encoding='utf-8') as json_file:
                data = json.load(json_file)
                return data if isinstance(data, list) else []
        except Exception:
            continue
    return []


def _resolve_date_filters(
    request_args: dict,
) -> Tuple[Optional[date], Optional[date], str]:
    """Translate query-string parameters into a (date_from, date_to, label) tuple.

    Supported named presets (via the 'preset' param):
        'today'   → current day only
        'week'    → last 7 days
        'month'   → last 30 days
        'quarter' → last 90 days

    Custom ranges use ISO-8601 'from' / 'to' params.
    Returns (None, None, 'All Time') when no filter is supplied.
    """
    date_from_str = request_args.get('from')
    date_to_str   = request_args.get('to')
    preset        = request_args.get('preset')

    today = date.today()

    # Named presets take precedence over explicit date strings.
    if preset == 'today':
        return today, today, 'Today'
    if preset == 'week':
        return today - timedelta(days=6), today, 'Last 7 Days'
    if preset == 'month':
        return today - timedelta(days=29), today, 'Last 30 Days'
    if preset == 'quarter':
        return today - timedelta(days=89), today, 'Last 90 Days'

    try:
        date_from = date.fromisoformat(date_from_str) if date_from_str else None
        date_to   = date.fromisoformat(date_to_str)   if date_to_str   else None
    except ValueError:
        date_from = None
        date_to   = None

    if date_from or date_to:
        from_label = date_from.isoformat() if date_from else '...'
        to_label   = date_to.isoformat()   if date_to   else '...'
        return date_from, date_to, f'{from_label} to {to_label}'

    return None, None, 'All Time'


def _row_is_in_range(row_date: date, date_from: Optional[date], date_to: Optional[date]) -> bool:
    """Return True if row_date falls within the inclusive [date_from, date_to] window."""
    if date_from and row_date < date_from:
        return False
    if date_to and row_date > date_to:
        return False
    return True


def _update_aggregated_error(
    aggregated: dict, row: dict, row_date_str: str, row_timestamp_str: str
) -> None:
    """Upsert a CSV row into the in-memory aggregation dict.
    Key: (status_code, error_code, description, api)
    Value: {count, dates (set), last_seen (str)}
    """
    key = (row['Status code'], row[ERROR_CODE_KEY], row[DESCRIPTION_KEY], row[API_KEY])
    if key not in aggregated:
        aggregated[key] = {'count': 0, 'dates': set(), 'last_seen': ''}
    aggregated[key]['count'] += 1
    if row_date_str:
        aggregated[key]['dates'].add(row_date_str)
    # Prefer the full timestamp for last_seen; fall back to date only.
    if row_timestamp_str and row_timestamp_str > aggregated[key]['last_seen']:
        aggregated[key]['last_seen'] = row_timestamp_str
    elif row_date_str and row_date_str > aggregated[key]['last_seen']:
        aggregated[key]['last_seen'] = row_date_str


def _serialize_aggregated_errors(aggregated: dict) -> List[dict]:
    """Convert the aggregation dict into a sorted list of dashboard row dicts.
    Only includes entries with HTTP status >= 400 and a non-empty error code."""
    return [
        {
            STATUS_CODE_KEY: key[0],
            ERROR_CODE_KEY:  key[1],
            DESCRIPTION_KEY: key[2],
            API_KEY:         key[3],
            COUNT_KEY:       meta['count'],
            LAST_SEEN_KEY:   meta['last_seen'],
            'Dates':         sorted(meta['dates']),
        }
        for key, meta in sorted(aggregated.items())
        if key[0].isdigit() and int(key[0]) >= 400 and key[1]
    ]


def _collect_unique_errors(
    conversion_dir: str,
    date_from: Optional[date],
    date_to: Optional[date],
) -> List[dict]:
    """Return the list of unique error records for the requested date range.

    Fast path (no filter active): returns the pre-built JSON artefact directly.
    Filtered path: re-reads and re-aggregates the raw CSV so counts and dates
    reflect only the specified window.
    """
    # When no date filter is active, use the pre-built JSON artefact directly.
    if not (date_from or date_to):
        return _read_unique_errors_data(conversion_dir)

    csv_path = os.path.join(conversion_dir, 'converted_application_logs.csv')
    if not os.path.exists(csv_path):
        # Fall back to the full JSON if the CSV is missing.
        return _read_unique_errors_data(conversion_dir)

    aggregated: dict = {}
    with open(csv_path, 'r', encoding='utf-8') as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            row_date_str      = row.get('Date', '')
            row_timestamp_str = row.get('Timestamp', '')
            try:
                row_date = date.fromisoformat(row_date_str)
            except ValueError:
                _logger.warning("Skipping CSV row with unparseable date: %r", row_date_str)
                continue  # Skip rows with an unparseable date.
            if not _row_is_in_range(row_date, date_from, date_to):
                continue
            _update_aggregated_error(aggregated, row, row_date_str, row_timestamp_str)

    return _serialize_aggregated_errors(aggregated)


# ── Public API ────────────────────────────────────────────────────────────────

def build_dashboard_payload(
    conversion_dir: str,
    run_conversion_outputs,
    request_args: dict,
) -> dict:
    """Assemble the full dashboard payload dict.

    Triggers a conversion pass first so the artefacts are always fresh, then
    applies any date filter and computes the summary statistics and breakdown dicts.

    Returns a dict with keys: summary, byStatus, byApi, rows, filter.
    """
    # Refresh artefacts from the latest log before reading them.
    run_conversion_outputs()

    date_from, date_to, filter_label = _resolve_date_filters(request_args)
    unique_errors = _collect_unique_errors(conversion_dir, date_from, date_to)

    total_errors = sum(item.get(COUNT_KEY, 0) for item in unique_errors)

    # Build breakdown dicts: total event counts grouped by status code and by API path.
    by_status: Dict[str, int] = {}
    by_api:    Dict[str, int] = {}
    for item in unique_errors:
        status_code = str(item.get(STATUS_CODE_KEY, 'Unknown'))
        api_name    = str(item.get(API_KEY,          'Unknown'))
        count       = int(item.get(COUNT_KEY, 0))
        by_status[status_code] = by_status.get(status_code, 0) + count
        by_api[api_name]       = by_api.get(api_name, 0)       + count

    return {
        'summary': {
            'uniqueErrorTypes': len(unique_errors),
            'totalErrorEvents': total_errors,
            'statusCodeCount':  len(by_status),
            'apiCount':         len(by_api),
        },
        'byStatus': by_status,
        'byApi':    by_api,
        'rows':     unique_errors,
        'filter': {
            'from':  date_from.isoformat() if date_from else None,
            'to':    date_to.isoformat()   if date_to   else None,
            'label': filter_label,
        },
    }
