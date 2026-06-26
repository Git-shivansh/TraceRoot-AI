"""
log_parser.py
Parses raw application log files into structured records.

Expected log line format (flexible, regex-based):
    2026-06-25 09:12:03,221 ERROR [order-service] OrderProcessor - Failed to process order 8841
    java.sql.SQLException: Connection pool exhausted
        at com.app.db.Pool.get(Pool.java:88)

Works reasonably well even if your logs differ slightly - adjust LOG_LINE_RE
to match your own format.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[,.]?\d*)\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\s+"
    r"\[?(?P<service>[\w\-\.]+)\]?\s*"
    r"(?P<rest>.*)$"
)

TIMESTAMP_FORMATS = [
    "%Y-%m-%d %H:%M:%S,%f",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S,%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
]


@dataclass
class LogEntry:
    timestamp: Optional[datetime]
    level: str
    service: str
    message: str
    stack_trace: List[str] = field(default_factory=list)
    raw: str = ""

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "level": self.level,
            "service": self.service,
            "message": self.message,
            "stack_trace": self.stack_trace,
        }


def _parse_timestamp(ts_str: str) -> Optional[datetime]:
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def parse_log_file(path: str) -> List[LogEntry]:
    """Reads a log file and returns a list of structured LogEntry objects.
    Lines that look like stack-trace continuations (start with whitespace or
    'at ', 'Caused by:', etc.) are attached to the previous entry."""
    entries: List[LogEntry] = []

    with open(path, "r", errors="replace") as f:
        lines = f.readlines()

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue

        match = LOG_LINE_RE.match(line)
        if match:
            ts = _parse_timestamp(match.group("timestamp"))
            entries.append(
                LogEntry(
                    timestamp=ts,
                    level=match.group("level").upper(),
                    service=match.group("service"),
                    message=match.group("rest").strip(),
                    raw=line,
                )
            )
        else:
            # Likely a stack trace / continuation line -> attach to last entry
            if entries and (line.startswith((" ", "\t")) or line.strip().startswith(("at ", "Caused by", "...", "Exception", "Error"))):
                entries[-1].stack_trace.append(line.strip())
            elif entries:
                # Unparseable line, still useful context - attach as stack trace too
                entries[-1].stack_trace.append(line.strip())

    return entries


def summarize_entries(entries: List[LogEntry]) -> dict:
    """Quick statistical summary used to brief the agent at the start."""
    level_counts = {}
    services = set()
    first_ts, last_ts = None, None

    for e in entries:
        level_counts[e.level] = level_counts.get(e.level, 0) + 1
        services.add(e.service)
        if e.timestamp:
            if first_ts is None or e.timestamp < first_ts:
                first_ts = e.timestamp
            if last_ts is None or e.timestamp > last_ts:
                last_ts = e.timestamp

    return {
        "total_lines": len(entries),
        "level_counts": level_counts,
        "services": sorted(services),
        "time_range": {
            "start": first_ts.isoformat() if first_ts else None,
            "end": last_ts.isoformat() if last_ts else None,
        },
    }