from datetime import datetime
import logging
from synapse.utils.log import str_to_log_entry, log_entry_to_str, log_level_to_pb
from synapse.api.logging_pb2 import LogEntry, LogLevel

def test_log_level_conversion():
    assert log_level_to_pb("DEBUG") == LogLevel.LOG_LEVEL_DEBUG
    assert log_level_to_pb("INFO") == LogLevel.LOG_LEVEL_INFO
    assert log_level_to_pb("WARNING") == LogLevel.LOG_LEVEL_WARNING
    assert log_level_to_pb("ERROR") == LogLevel.LOG_LEVEL_ERROR
    assert log_level_to_pb("CRITICAL") == LogLevel.LOG_LEVEL_CRITICAL
    assert log_level_to_pb("INVALID") == LogLevel.LOG_LEVEL_UNKNOWN

    assert log_level_to_pb(logging.DEBUG) == LogLevel.LOG_LEVEL_DEBUG
    assert log_level_to_pb(logging.INFO) == LogLevel.LOG_LEVEL_INFO
    assert log_level_to_pb(logging.WARNING) == LogLevel.LOG_LEVEL_WARNING
    assert log_level_to_pb(logging.ERROR) == LogLevel.LOG_LEVEL_ERROR
    assert log_level_to_pb(logging.CRITICAL) == LogLevel.LOG_LEVEL_CRITICAL

def test_valid_log_entry_parsing():
    log_line = "2024-03-14T15:26:53.789000 | INFO | test_module | Test message"
    entry = str_to_log_entry(log_line)

    assert entry is not None
    assert entry.level == LogLevel.LOG_LEVEL_INFO
    assert entry.source == "test_module"
    assert entry.message == "Test message"

    dt = datetime.fromtimestamp(entry.timestamp_ns / 1e9)
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 14
    assert dt.hour == 15
    assert dt.minute == 26
    assert dt.second == 53
    assert dt.microsecond == 789000

def test_malformed_log_entry_parsing():
    invalid_logs = [
        "",
        "Not a log line",
        "2024-03-14T15:26:53.789000",
        "invalid_date | INFO | source | message",
        "| INFO | source | message",
        "2024-03-14T15:26:53.789000 | INFO | | message",
    ]

    for log_line in invalid_logs:
        assert str_to_log_entry(log_line) is None

def test_log_entry_serialization():
    timestamp = int(datetime(2024, 3, 14, 15, 26, 53, 789000).timestamp() * 1e9)
    entry = LogEntry(
        timestamp_ns=timestamp,
        level=LogLevel.LOG_LEVEL_WARNING,
        source="test_source",
        message="Test message"
    )

    log_str = log_entry_to_str(entry)

    parsed_entry = str_to_log_entry(log_str)

    assert parsed_entry is not None
    assert parsed_entry.timestamp_ns == entry.timestamp_ns
    assert parsed_entry.level == entry.level
    assert parsed_entry.source == entry.source
    assert parsed_entry.message == entry.message

def test_log_entry_with_special_characters():
    special_messages = [
        "Message with | pipe",
        "Message with multiple  spaces",
        "Message with special chars: !@#$%^&*()",
    ]

    for message in special_messages:
        now = datetime.now()
        entry = LogEntry(
            timestamp_ns=int(now.timestamp() * 1e9),
            level=LogLevel.LOG_LEVEL_INFO,
            source="test_source",
            message=message
        )

        log_str = log_entry_to_str(entry)

        now_str = now.isoformat(timespec='microseconds')
        assert log_str == f"{now_str} | INFO | test_source | {message}", f"Log string mismatch. Expected: {now_str} | INFO | test_source | {message}, Got: {log_str}"
        parsed_entry = str_to_log_entry(log_str)

        assert parsed_entry is not None, f"Failed to parse log string: {log_str}"
        assert parsed_entry.message == message, f"Message mismatch. Expected: {message}, Got from log string: {log_str}"
