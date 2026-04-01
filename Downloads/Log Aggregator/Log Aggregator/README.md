# Log Aggregator

A sophisticated API error analytics platform that ingests application logs, aggregates failures, and provides dashboards with AWS Bedrock AI-powered incident insights.

## Features

- **Structured Logging** — Centralized application log collection with file and console output
- **Log Parsing & Conversion** — Convert raw application logs to CSV and deduplicated error JSON
- **Error Dashboard** — Web UI displaying error metrics, aggregations by status code and API, and date filtering
- **PDF Reporting** — Generate landscape-format PDF summaries of dashboard findings
- **AI-Powered Insights** — Ask AWS Bedrock Agent questions about selected errors for root-cause analysis and remediation guidance
- **Traffic Simulator** — Seed realistic, backdated error events for dashboard testing
- **Data Validation** — Multi-field validation endpoint that logs failures for aggregation
- **Modular Architecture** — Separated concerns across route blueprints, parsing utilities, and service layers

## Project Structure

```
Log Aggregator/
├── Application/                   # Flask API application
│   ├── app.py                     # Entry point; bootstrap, middleware, error handlers
│   ├── logger.py                  # Structured logging configuration
│   ├── routes/                    # Blueprint modules by domain
│   │   ├── __init__.py
│   │   ├── core.py                # /, /api/status, /api/logs
│   │   ├── payments.py            # Payment endpoints (demo errors)
│   │   ├── auth.py                # Auth endpoints (demo errors)
│   │   ├── orders.py              # Order management endpoints (demo errors)
│   │   ├── users.py               # User endpoints (demo errors)
│   │   ├── infrastructure.py       # Downstream service endpoints (demo errors)
│   │   └── simulator.py           # /api/simulate-traffic, /api/validate
│   └── logs/                      # Application log directory (created at runtime)
│
├── Conversion/                    # Log parsing and aggregation pipeline
│   ├── log_parser.py              # Low-level regex patterns and parsing helpers
│   ├── log_to_csv_service.py      # Main conversion: logs → CSV + JSON
│   ├── converted_application_logs.csv      # Output: flat transaction log
│   └── unique_errors.json         # Output: deduplicated errors with metadata
│
├── Dashboard/                     # Dashboard Flask blueprint and services
│   ├── dashboard_blueprint.py     # Route handlers (thin delegation layer)
│   ├── dashboard_data_service.py  # Data aggregation, filtering, payload assembly
│   ├── dashboard_pdf_service.py   # PDF rendering via reportlab
│   ├── bedrock_chat_service.py    # AWS Bedrock Agent integration
│   ├── templates/
│   │   └── dashboard.html         # Single-page dashboard UI
│   └── dashboard_blueprint.py     # Blueprint factory and route handlers
│
├── requirements.txt               # Python dependencies
├── README.md                      # This file
└── .env                           # Environment variables (AWS credentials, agent IDs)
```

## Installation

### Prerequisites

- **Python 3.8+**
- **pip** or **conda** for dependency management

### Setup

1. Clone / download the repository and navigate to the workspace:
   ```bash
   cd "Log Aggregator"
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```

3. Activate the virtual environment:
   - **Windows (PowerShell):**
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS/Linux (bash):**
     ```bash
     source .venv/bin/activate
     ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Configure environment variables (optional, for Bedrock AI features):
   ```bash
   # Create a .env file in the workspace root with:
   AWS_REGION=us-east-1
   BEDROCK_AGENT_ID=your-agent-id
   BEDROCK_AGENT_ALIAS_ID=your-agent-alias-id
   ```

## Usage

### Running the API Server

#### Quick Start

1. **Activate the virtual environment** (if not already active):
   - **Windows (PowerShell):**
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS/Linux:**
     ```bash
     source .venv/bin/activate
     ```

2. **Start the Flask application:**
   ```bash
   python Application/app.py
   ```

3. **Verify the server is running:**
   - Open your browser and navigate to `http://localhost:5000`
   - You should see a welcome message
   - Check the console for log output confirming the server started

4. **Access the dashboard:**
   - Navigate to `http://localhost:5000/dashboard`
   - The dashboard will be empty until you seed test data

#### Seeding Data and Testing

Before using the dashboard, populate it with test error data:

```bash
curl -X POST http://localhost:5000/api/simulate-traffic
```

Then refresh the dashboard at `http://localhost:5000/dashboard` to see the aggregated errors.

#### Running Everything Together (Complete Workflow)

If you want to manually run the entire pipeline:

```bash
# 1. Activate the environment
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# OR
source .venv/bin/activate     # macOS/Linux

# 2. Start the API server
python Application/app.py

# 3. In another terminal, seed test data
curl -X POST http://localhost:5000/api/simulate-traffic

# 4. View the results:
#    - Dashboard: http://localhost:5000/dashboard
#    - CSV data:  Conversion/converted_application_logs.csv
#    - JSON data: Conversion/unique_errors.json
```

#### Manual Log Conversion (Without API Server)

If you only want to convert existing logs to CSV/JSON without running the server:

```bash
# Activate the environment
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# OR
source .venv/bin/activate     # macOS/Linux

# Run the conversion pipeline
cd Conversion
python log_to_csv_service.py

# Outputs:
#   converted_application_logs.csv
#   unique_errors.json
```

#### Server Configuration

By default, the server:
- Listens on `http://localhost:5000`
- Writes logs to `Application/logs/application.log`
- Automatically creates the logs directory on first run
- Converts logs to CSV/JSON after each request

To change the port, edit `Application/app.py` and modify the `app.run()` call at the bottom:
```python
app.run(host='0.0.0.0', port=8000, debug=True)  # Change port to 8000
```

**Available endpoints:**
- `GET  /`                             — Welcome message
- `GET  /api/status`                   — Server health and uptime
- `POST /api/logs`                     — Submit a custom log entry
- `GET  /api/logs`                     — Retrieve all log lines
- `GET  /dashboard`                    — Error analytics dashboard UI
- `GET  /api/dashboard-data`           — Dashboard JSON payload (with optional date filters)
- `GET  /api/dashboard-report.pdf`     — Download PDF report (requires reportlab)
- `POST /api/chat-insights`            — Ask Bedrock Agent about selected errors (requires AWS credentials)
- `POST /api/simulate-traffic`         — Seed 215 realistic backdated error events
- `POST /api/validate`                 — Validate user data (name, email, age)
- Payment, Auth, Order, User, and Infrastructure endpoints (demo errors)

### Seeding Test Data

Populate the dashboard with realistic errors:

```bash
curl -X POST http://localhost:5000/api/simulate-traffic
```

This seeds the log with weighted, backdated error events across the last 30 days and triggers a conversion pass so the dashboard reflects the new data immediately.

### Converting Logs to CSV / JSON

Run the conversion pipeline directly (useful for CI/CD or cron jobs):

```bash
cd Conversion
python log_to_csv_service.py
```

Outputs:
- `converted_application_logs.csv` — Flat transaction log (every API call)
- `unique_errors.json` — Deduplicated errors with count, dates, last-seen timestamp

## Module Documentation

### `Application/logger.py`
Centralized structured logging that writes to both the application log file and stdout.
- Functions: `info()`, `error()`, `warn()`, `debug()`
- Format: `[YYYY-MM-DDTHH:MM:SS] [LEVEL] <message>`

### `Application/routes/*.py`
Thin route blueprints grouped by domain. Each exposes logic through a single Flask Blueprint. All endpoints in `payments`, `auth`, `orders`, `users`, and `infrastructure` return simulated errors for testing.

### `Conversion/log_parser.py`
Low-level regex patterns and parsing utilities:
- `ANSI_ESCAPE_PATTERN`, `API_WITH_IP_PATTERN`, `STATUS_PATTERN`, `ERROR_CODE_PATTERN`, `TIMESTAMP_PATTERN`
- `clean_line()`, `extract_error_details()`, `extract_timestamp()`, `extract_date()`

### `Conversion/log_to_csv_service.py`
Main conversion service with three public functions:
- `convert_log_to_rows(source_log_path)` — Parse log file into row dicts
- `write_rows_to_csv(rows, output_csv_path)` — Write rows to CSV
- `write_unique_errors_json(rows, output_json_path)` — Aggregate and deduplicate errors to JSON

### `Dashboard/dashboard_data_service.py`
Dashboard data assembly pipeline:
- `build_dashboard_payload(conversion_dir, run_conversion_outputs, request_args)` — Main entry point
- Shared field-name constants: `STATUS_CODE_KEY`, `ERROR_CODE_KEY`, `DESCRIPTION_KEY`, `API_KEY`, `COUNT_KEY`, `LAST_SEEN_KEY`
- Date filter resolution: preset names ('today', 'week', 'month', 'quarter') or custom ISO date bounds

### `Dashboard/dashboard_pdf_service.py`
PDF report generation via reportlab:
- `build_dashboard_pdf(payload)` — Render dashboard payload to landscape-letter PDF
- Output: summary metrics table + detailed error table sorted by occurrence count

### `Dashboard/bedrock_chat_service.py`
AWS Bedrock Agent integration:
- `generate_error_insight(error_details, user_message, history, session_id)` — Invoke agent and return reply + metadata
- Requires: `BEDROCK_AGENT_ID`, `BEDROCK_AGENT_ALIAS_ID`, AWS credentials

## Architecture

### Request Flow

```
HTTP Request
    ↓
Flask App (app.py)
    ├─→ Middleware: log_request(), log_response()
    ├─→ Route Blueprints (routes/*.py)
    │   ├─ core.py          (welcome, status, logs endpoints)
    │   ├─ payments.py       (payment demo errors)
    │   ├─ auth.py           (auth demo errors)
    │   ├─ orders.py         (order demo errors)
    │   ├─ users.py          (user demo errors)
    │   ├─ infrastructure.py (downstream service demo errors)
    │   └─ simulator.py      (traffic simulator, validation)
    └─→ Dashboard Blueprint (dashboard_blueprint.py)
        ├─ /dashboard           (HTML shell)
        ├─ /api/dashboard-data  (delegated to dashboard_data_service.py)
        ├─ /api/dashboard-report.pdf (delegated to dashboard_pdf_service.py)
        └─ /api/chat-insights   (delegated to bedrock_chat_service.py)
         
Logs → logger.py → logs/application.log
         ↓
         (After each request via run_conversion_outputs())
         ↓
Conversion Pipeline (Conversion/log_to_csv_service.py)
    ├─→ log_parser.py (parsing helpers)
    └─→ Outputs:
        ├─ converted_application_logs.csv
        └─ unique_errors.json
         ↓
Dashboard reads from artifacts above
```

### Data Flow: Log Parsing

```
Raw Log Line
    ↓
log_parser.clean_line()  → Strip ANSI escapes
    ↓
Pattern Matching (regex in log_parser.py)
    ├─ API_WITH_IP_PATTERN    → current_api, current_timestamp, current_date
    ├─ [ERROR]/[WARNING]      → extract_error_details() → error_code, description
    └─ STATUS_PATTERN         → Emit CSV row, reset state
    ↓
CSV Row: {Timestamp, Date, Status code, Error Code, Description, API}
    ↓
Aggregation (write_unique_errors_json)
    → Group by (status_code, error_code, description, api)
    → Count occurrences + track dates + last_seen
    ↓
JSON: [{Status Code, Error Code, Description, API, Count, Last Seen, Dates}]
```

## Dependencies

See `requirements.txt` for a complete list. Key dependencies:

- **Flask** — Web framework
- **python-dotenv** — Environment variable management
- **reportlab** (optional) — PDF generation
- **boto3** (optional) — AWS SDK for Bedrock integration

## Configuration

### Environment Variables (`.env`)

```bash
# AWS Configuration (required for Bedrock chat features)
AWS_REGION=us-east-1
BEDROCK_AGENT_ID=<your-bedrock-agent-id>
BEDROCK_AGENT_ALIAS_ID=<your-bedrock-agent-alias-id>
BEDROCK_AGENT_SESSION_ID=<optional-session-id>  # Leave empty for auto-generated UUIDs
```

If AWS credentials are not configured, the dashboard will still work but the chat-insights endpoint will return a 503 error.

## Testing

### Example: Create a Log Entry

```bash
curl -X POST http://localhost:5000/api/logs \
  -H "Content-Type: application/json" \
  -d '{"message": "Test error", "level": "error"}'
```

### Example: Validate User Data

```bash
curl -X POST http://localhost:5000/api/validate \
  -H "Content-Type: application/json" \
  -d '{"name": "John", "email": "john@example.com", "age": 30}'
```

### Example: Get Dashboard Data (All Errors)

```bash
curl http://localhost:5000/api/dashboard-data
```

### Example: Get Dashboard Data (Last 7 Days)

```bash
curl 'http://localhost:5000/api/dashboard-data?preset=week'
```

### Example: Get Dashboard Data (Custom Date Range)

```bash
curl 'http://localhost:5000/api/dashboard-data?from=2026-03-25&to=2026-03-31'
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| ImportError: No module named 'flask' | Run `pip install -r requirements.txt` |
| ModuleNotFoundError: No module named 'reportlab' | PDF export will return 503; install `reportlab` for full support |
| AWS Bedrock chat unavailable | Ensure boto3 is installed and `BEDROCK_AGENT_ID` / `BEDROCK_AGENT_ALIAS_ID` are set in `.env` |
| Log file not found | Logs directory is created automatically on first request |
| Port 5000 already in use | Change Flask port via environment or use `flask run --port 8000` |

## Development Notes

### Code Quality

- All modules include file-level docstring headers explaining responsibilities
- Route modules are organized by domain for easier maintenance
- Separation of concerns: routes handle HTTP, service modules handle logic
- Low-level utilities (log_parser.py) are separate from high-level orchestration

### Adding a New Endpoint

1. Create a new file in `Application/routes/` (e.g., `routes/invoices.py`)
2. Define a blueprint and route handlers with full docstrings
3. Import and register the blueprint in `app.py`
4. Update this README with the new endpoint

### Extending the Dashboard

- Add metrics to `dashboard_data_service.py`'s aggregation logic
- Modify PDF layout in `dashboard_pdf_service.py`'s `build_dashboard_pdf()`
- Update the frontend JS/HTML in `Dashboard/templates/dashboard.html`

## Performance Considerations

- **Log Parsing**: O(n) pass through the log file once per request (via `run_conversion_outputs()`)
- **CSV Writing**: Streaming write; memory footprint is constant
- **JSON Aggregation**: In-memory dict; scales with unique error count (typically < 1000)
- **Dashboard Filtering**: When a date filter is active, re-aggregates from CSV; otherwise uses pre-built JSON
- **PDF Generation**: Streams to BytesIO buffer; no intermediate disk writes

## License

This project is for demonstration and testing purposes.

## Support

For issues, refer to the inline comments and docstrings throughout the codebase. Each module includes detailed documentation of its responsibilities and public APIs.
