# Log Aggregator - Configuration Guide

All configurable items for the Log Aggregator application are now centralized in the `.env` file. This guide documents all available configuration options.

## Environment Configuration File

The `.env` file is located at the root of the Log Aggregator workspace and contains all runtime configuration settings.

### Application Server Configuration

```env
# Flask / Application Server Configuration
FLASK_ENV=development           # Flask environment (development/production)
FLASK_DEBUG=true                # Enable Flask debug mode (true/false)
APP_PORT=5000                   # Server port (default: 5000)
APP_HOST=localhost              # Server host/bind address (default: localhost)
```

**Usage in Code:**
- `app.py`: Reads `APP_PORT`, `APP_HOST`, `FLASK_DEBUG` at startup
- `logger.py`: Reads log level from configuration

### Logging Configuration

```env
# Logging Configuration
LOG_LEVEL=INFO                  # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOGS_DIRECTORY=logs             # Directory where log files are stored
LOG_FILENAME=application.log    # Name of the main application log file
```

**Usage in Code:**
- `logger.py`: Creates logs directory and configures logging
- `routes/core.py`: Reads log file location for GET /api/logs endpoint
- `log_to_csv_service.py`: Uses for log processing and conversion

### AWS Bedrock Configuration

```env
# AWS Bedrock Integration
AWS_REGION=us-east-1                                        # AWS region
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0  # Model ID
BEDROCK_AGENT_ID=HB8PL0CMXJ                                 # Agent ID
BEDROCK_AGENT_ALIAS_ID=TSTALIASID                           # Agent Alias ID
```

**Usage in Code:**
- `bedrock_chat_service.py`: Uses all Bedrock configuration for AI chat integration

### AWS Credentials

```env
# AWS Credentials (recommended: use aws configure / IAM role instead)
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_SESSION_TOKEN=<your-session-token>
```

**⚠️ Security Note:** Use AWS IAM roles or `aws configure` instead of storing credentials in `.env` for production environments.

### Feature Toggles

```env
# Feature Toggles
ENABLE_BEDROCK_CHAT=true        # Enable Bedrock AI chat functionality
ENABLE_DASHBOARD=true           # Enable dashboard module
ENABLE_CONVERTER=true           # Enable log conversion/analytics module
```

**Usage in Code:**
- `app.py`: Checks `ENABLE_BEDROCK_CHAT` and `ENABLE_DASHBOARD` before loading optional modules

### API Tokens & Secrets

```env
# Optional API Tokens/Secrets
DASHBOARD_API_TOKEN=            # Token for dashboard API access (optional)
INTERNAL_SERVICE_TOKEN=         # Token for internal service communication (optional)
```

## Files Modified to Read Configuration

The following files have been updated to read configuration from the `.env` file instead of hardcoded values:

### 1. `Application/logger.py`
- **Changed:** Reads `LOG_LEVEL`, `LOGS_DIRECTORY`, `LOG_FILENAME` from environment
- **Before:** Hardcoded `logs_dir = 'logs'` and `log_filename = 'application.log'`
- **After:** Uses `os.getenv()` with sensible defaults

### 2. `Application/app.py`
- **Changed:** Reads `APP_PORT`, `APP_HOST`, `FLASK_DEBUG`, `LOG_FILENAME` from environment
- **Before:** Hardcoded `port=5000`, `debug=True`, event logs displayed hardcoded port
- **After:** Dynamic configuration with `os.getenv()` defaults

### 3. `Application/routes/core.py`
- **Changed:** Reads `LOG_FILENAME` and `LOGS_DIRECTORY` from environment
- **Before:** Hardcoded `_LOG_FILENAME = 'application.log'` and hardcoded `logs` directory
- **After:** Environment-driven with fallback defaults

### 4. `Conversion/log_to_csv_service.py`
- **Changed:** Reads `LOG_FILENAME` and `LOGS_DIRECTORY` in `main()` function
- **Before:** Hardcoded paths in CLI entry point
- **After:** CLI entry point respects environment configuration

## Configuration Usage Examples

### Change Server Port
```env
APP_PORT=8080              # Server now runs on port 8080
```

### Enable Production Mode
```env
FLASK_ENV=production       # Disable debug features
FLASK_DEBUG=false          # Disable development server reloading
LOG_LEVEL=WARNING          # Less verbose logging
```

### Custom Logging Directory
```env
LOGS_DIRECTORY=/var/log/aggregator          # Custom log location
LOG_FILENAME=app.log                        # Custom log filename
```

### Disable Optional Features
```env
ENABLE_BEDROCK_CHAT=false     # Disable AI chat
ENABLE_DASHBOARD=false        # Disable dashboard
```

## Default Values

All environment variables have sensible defaults, so you don't need to specify them unless you want to override:

| Variable | Default | Required |
|----------|---------|----------|
| FLASK_ENV | development | No |
| FLASK_DEBUG | true | No |
| APP_PORT | 5000 | No |
| APP_HOST | localhost | No |
| LOG_LEVEL | INFO | No |
| LOGS_DIRECTORY | logs | No |
| LOG_FILENAME | application.log | No |
| ENABLE_BEDROCK_CHAT | true | No |
| ENABLE_DASHBOARD | true | No |
| ENABLE_CONVERTER | true | No |

## Loading Environment Configuration

The `.env` file is automatically loaded by:
1. `Application/logger.py` - When the logging module initializes
2. `Application/app.py` - During Flask app initialization (with `override=True` to force updates)
3. `Application/routes/core.py` - When the core routes blueprint is imported
4. `Conversion/log_to_csv_service.py` - In the `main()` CLI function

The `override=True` setting ensures that `.env` values always take precedence over stale shell environment variables.

## Running with Custom Configuration

### Option 1: Edit .env file
Simply edit the `.env` file and restart the application.

### Option 2: Override at Runtime
```bash
# Unix/Linux/macOS
export APP_PORT=8080
export FLASK_DEBUG=false

# Windows PowerShell
$env:APP_PORT = '8080'
$env:FLASK_DEBUG = 'false'
```

Then run the application:
```bash
cd Application
python app.py
```

### Option 3: Docker/Environment Injection
When running in containers, pass environment variables during startup:
```bash
docker run -e APP_PORT=8080 -e FLASK_DEBUG=false log-aggregator:latest
```

## Migration Notes

**Legacy Hardcoded Values Removed:**
- ❌ `APP_LOG_FILENAME = 'application.log'` in app.py
- ❌ `_LOG_FILENAME = 'application.log'` in routes/core.py
- ❌ `logs_dir = 'logs'` in logger.py
- ❌ `port=5000` hardcoded in app.run()
- ❌ `debug=True` hardcoded in app.run()

**All now use `os.getenv()` with proper defaults.**
