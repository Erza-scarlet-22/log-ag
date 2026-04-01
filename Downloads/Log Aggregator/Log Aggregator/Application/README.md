# Log Aggregator API

A simple Python Flask API application with built-in file logging capabilities.

## Features

- Flask/Python API server
- Automatic file logging to `logs/application.log`
- RESTful endpoints for managing logs
- Console and file logging
- Error handling and 404 management

## Requirements

- Python 3.7 or higher
- Flask 2.3.3+

## Installation

1. Make sure you have Python installed:
```bash
python --version
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Application

Start the server:
```bash
python app.py
```

The server will run on `http://localhost:5000`

You should see output like:
```
API running at http://localhost:5000
Available endpoints:
  GET  /                - Welcome message
  GET  /api/status      - Server status
  POST /api/logs        - Submit a log entry
  GET  /api/logs        - Retrieve all logs
```

## API Endpoints

### Get Welcome Message
```
GET /
```
Returns a welcome message and API version.

### Check Server Status
```
GET /api/status
```
Returns server health status and uptime.

### Submit a Log Entry
```
POST /api/logs
Content-Type: application/json

{
  "message": "Your log message",
  "level": "info"
}
```
Levels: `info`, `error`, `warn`, `debug`

### Retrieve All Logs
```
GET /api/logs
```
Returns all logged entries from the log file.

## Logging

All API requests and custom logs are automatically written to `logs/application.log`.

Log format:
```
[ISO_TIMESTAMP] [LEVEL] message
```

## File Structure

```
Application/
├── app.py              - Main Flask application
├── logger.py           - Logging utility
├── requirements.txt    - Python dependencies
├── .gitignore          - Git ignore rules
├── README.md           - This file
└── logs/               - Log files (auto-created)
    └── application.log
```

## Example Usage

```bash
# Check status
curl http://localhost:5000/api/status

# Submit a log
curl -X POST http://localhost:5000/api/logs \
  -H "Content-Type: application/json" \
  -d "{\"message\": \"Test log entry\", \"level\": \"info\"}"

# View all logs
curl http://localhost:5000/api/logs
```

## Stopping the Server

Press `Ctrl+C` in the terminal to stop the server.
