import asyncio
from datetime import datetime
import logging
import re
from pathlib import Path
from typing import Union

from logging.handlers import RotatingFileHandler
from synapse.api.logging_pb2 import LogEntry, LogLevel

FORMAT_STRING = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

class Formatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        return dt.isoformat(timespec='microseconds')

def init_file_handler(logger, log_filepath: Union[str, Path], level=logging.DEBUG):
    try:
        Path(log_filepath).parent.mkdir(parents=True, exist_ok=True)

        max_bytes = 1024 * 1024 * 1024
        file_handler = RotatingFileHandler(
            log_filepath,
            maxBytes=max_bytes,
            backupCount=5
        )
        file_handler.setFormatter(Formatter(fmt=FORMAT_STRING))
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    except Exception as e:
        logging.warning(f"failed to set up file logging: {e}")

def init_logging(level=logging.INFO):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = Formatter(fmt=FORMAT_STRING)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    ch.setLevel(level)
    root.addHandler(ch)

# Parsing

def log_entry_to_str(entry: LogEntry) -> str:
    dt = datetime.fromtimestamp(entry.timestamp_ns / 1e9)
    return f"{dt.isoformat(timespec='microseconds')} | {LogLevel.Name(entry.level).replace('LOG_LEVEL_', '')} | {entry.source} | {entry.message}"

def log_level_to_pb(level: Union[str, int]) -> LogLevel:
    if level == "DEBUG" or level == logging.DEBUG:
        return LogLevel.LOG_LEVEL_DEBUG
    elif level == "INFO" or level == logging.INFO:
        return LogLevel.LOG_LEVEL_INFO
    elif level == "WARNING" or level == logging.WARNING:
        return LogLevel.LOG_LEVEL_WARNING
    elif level == "ERROR" or level == logging.ERROR:
        return LogLevel.LOG_LEVEL_ERROR
    elif level == "CRITICAL" or level == logging.CRITICAL:
        return LogLevel.LOG_LEVEL_CRITICAL
    else:
        return LogLevel.LOG_LEVEL_UNKNOWN

def str_to_log_entry(line: str) -> Union[LogEntry, None]:
    """
    Parses a log line into a LogEntry object.

    Assume logs obey the following format:
    <timestamp> | <level> | <source> | <message>
    """
    pattern = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*\|\s*(\w+)\s*\|\s*([^|\s][^|]*[^|\s])\s*\|\s*(.+)"
    match = re.match(pattern, line)
    if not match:
        return None

    datetime_str = match.group(1)
    level = match.group(2)
    source = match.group(3)
    message = match.group(4)

    dt = None
    timestamp = None
    try:
        dt = datetime.fromisoformat(datetime_str.replace(',', '.'))
    except ValueError:
        return None

    try:
        timestamp = int(dt.timestamp() * 1e9)
    except ValueError:
        return None

    entry = LogEntry(
        timestamp_ns=timestamp,
        level=log_level_to_pb(level),
        source=source,
        message=message
    )
    return entry

class StreamingLogHandler(logging.Handler):
    def __init__(self, broadcast_func):
        super().__init__()
        self.broadcast_func = broadcast_func
        self.formatter = Formatter(fmt=FORMAT_STRING)

    def emit(self, record):
        try:
            formatted_record = self.formatter.format(record)
            self.broadcast_func(formatted_record)
        except Exception:
            pass
