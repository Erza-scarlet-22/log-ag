# Logging configuration for the Log Aggregator application.
#
# Writes structured log lines to both the application log file and stdout.
# Log format: [YYYY-MM-DDTHH:MM:SS] [LEVEL] <message>
#
# Public API — thin wrappers around the stdlib logger that accept an optional
# structured data argument appended to the message string:
#   info(message, data=None)
#   error(message, data=None)
#   warn(message, data=None)
#   debug(message, data=None)

import os
import logging
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

# Get logging configuration from environment variables
logs_dir = os.getenv('LOGS_DIRECTORY', 'logs')
log_filename = os.getenv('LOG_FILENAME', 'application.log')

# Create the logs directory relative to the working directory if it doesn't exist.
if not os.path.exists(logs_dir):
    os.makedirs(logs_dir)

log_file = os.path.join(logs_dir, log_filename)

# Configure the root logger: write to both the log file and the console with a
# consistent bracketed timestamp/level format that the log parser can process.
# Map LOG_LEVEL env var to logging level
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level_map = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}
log_level = log_level_map.get(log_level_str, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),  # Also log to console
    ]
)

logger = logging.getLogger(__name__)


def info(message, data=None):
    logger.info(f"{message} {data}" if data else message)

def error(message, data=None, exc_info=False):
    logger.error(f"{message} {data}" if data else message, exc_info=exc_info)

def warn(message, data=None):
    logger.warning(f"{message} {data}" if data else message)

def debug(message, data=None):
    logger.debug(f"{message} {data}" if data else message)
