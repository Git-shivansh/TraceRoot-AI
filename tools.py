"""
tools.py
Defines the tool schemas (given to Claude) and the actual Python functions
(executed locally) that the agentic RCA loop can call.

In a real deployment you would swap the "mock" functions below for real
calls to Datadog/Prometheus/Grafana, your deploy system (GitHub Actions/
ArgoCD), and a dependency/health-check API. They are mocked here so the
project runs end-to-end with zero external infra.
"""
import hashlib
import random
from collections import Counter, defaultdict
from datetime import timedelta
from typing import List

from log_parser import LogEntry

# ----------------------------------------------------------------------------
# Tool schemas (Anthropic tool-use format)
# ----------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "search_logs",
        "description": (
            "Search the parsed log entries for a keyword or phrase "
            "(case-insensitive substring match against message + stack trace). "
            "Returns matching lines with timestamps. Use this to follow leads, "
            "e.g. search for a specific exception name, service, or order ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Keyword or phrase to search for"},
                "max_results": {"type": "integer", "description": "Max matching lines to return", "default": 15},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_error_timeline",
        "description": (
            "Get a chronological count of ERROR/FATAL/CRITICAL log entries "
            "bucketed by minute, per service. Useful for spotting when an "
            "incident started and whether it cascaded across services."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_metrics",
        "description": (
            "Fetch recent infrastructure metrics (CPU %, memory %, p99 latency ms, "
            "error rate %, active DB connections) for a given service over the "
            "incident window. Use this to confirm whether resource exhaustion or "
            "latency spikes correlate with the errors in the logs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name to fetch metrics for"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "get_recent_deployments",
        "description": (
            "List recent deployments/releases (service, version, deploy time, "
            "author, changed config flags) across all services. Use this to check "
            "whether the incident correlates with a recent deploy or config change."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_dependency_health",
        "description": (
            "Check the current health/status of a downstream dependency "
            "(e.g. a database, cache, third-party API, or message queue) that a "
            "service relies on."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dependency": {"type": "string", "description": "Name of the dependency to check, e.g. 'postgres-primary', 'redis-cache', 'payments-api'"},
            },
            "required": ["dependency"],
        },
    },
]


# ----------------------------------------------------------------------------
# OpenAI uses a different (nested) tool schema shape than Anthropic.
# Rather than maintaining two separate lists by hand, we convert automatically
# from TOOL_SCHEMAS above so both providers always stay in sync.
#
# Anthropic shape: {"name", "description", "input_schema"}
# OpenAI shape:    {"type": "function", "function": {"name", "description", "parameters"}}
# ----------------------------------------------------------------------------

def _to_openai_schema(anthropic_schemas: list) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        }
        for s in anthropic_schemas
    ]


OPENAI_TOOL_SCHEMAS = _to_openai_schema(TOOL_SCHEMAS)


# ----------------------------------------------------------------------------
# Deterministic "mock" helpers so re-runs on the same log file are consistent
# ----------------------------------------------------------------------------

def _seeded_random(*parts: str) -> random.Random:
    seed = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(seed)


class ToolExecutor:
    """Holds parsed log entries and executes tool calls against them /
    against mocked external systems."""

    def __init__(self, entries: List[LogEntry]):
        self.entries = entries

    # -- search_logs ----------------------------------------------------
    def search_logs(self, keyword: str, max_results: int = 15) -> dict:
        keyword_lower = keyword.lower()
        matches = []
        for e in self.entries:
            haystack = (e.message + " " + " ".join(e.stack_trace)).lower()
            if keyword_lower in haystack:
                matches.append({
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "level": e.level,
                    "service": e.service,
                    "message": e.message,
                    "stack_trace": e.stack_trace[:5],
                })
        return {
            "keyword": keyword,
            "total_matches": len(matches),
            "results": matches[:max_results],
        }

    # -- get_error_timeline ----------------------------------------------
    def get_error_timeline(self) -> dict:
        buckets = defaultdict(lambda: Counter())
        for e in self.entries:
            if e.level in ("ERROR", "FATAL", "CRITICAL") and e.timestamp:
                minute_bucket = e.timestamp.replace(second=0, microsecond=0)
                buckets[minute_bucket.isoformat()][e.service] += 1

        timeline = [
            {"minute": ts, "errors_by_service": dict(counts)}
            for ts, counts in sorted(buckets.items())
        ]
        return {"timeline": timeline, "total_error_minutes": len(timeline)}

    # -- get_metrics (MOCKED) --------------------------------------------
    def get_metrics(self, service: str) -> dict:
        rng = _seeded_random("metrics", service)
        # Bias certain "interesting" services toward showing resource strain,
        # so the demo log file tells a coherent story end-to-end.
        strained = service.lower() in ("order-service", "payment-service", "db-pool", "inventory-service")
        cpu = rng.uniform(78, 97) if strained else rng.uniform(20, 55)
        mem = rng.uniform(82, 99) if strained else rng.uniform(30, 60)
        latency = rng.uniform(1200, 4800) if strained else rng.uniform(50, 300)
        error_rate = rng.uniform(15, 45) if strained else rng.uniform(0, 2)
        db_conns = rng.randint(95, 100) if strained else rng.randint(5, 40)

        return {
            "service": service,
            "window": "last 30 minutes",
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(mem, 1),
            "p99_latency_ms": round(latency, 0),
            "error_rate_percent": round(error_rate, 1),
            "active_db_connections": db_conns,
            "db_connection_pool_max": 100,
            "note": "(simulated metrics for demo purposes)",
        }

    # -- get_recent_deployments (MOCKED) ----------------------------------
    def get_recent_deployments(self) -> dict:
        base_time = self.entries[0].timestamp if self.entries and self.entries[0].timestamp else None
        deploys = [
            {
                "service": "order-service",
                "version": "v2.14.0",
                "deployed_at": (base_time - timedelta(minutes=42)).isoformat() if base_time else "unknown",
                "author": "ci-bot",
                "changes": "Increased default request timeout; reduced DB connection pool size from 200 to 100",
            },
            {
                "service": "inventory-service",
                "version": "v1.9.3",
                "deployed_at": (base_time - timedelta(hours=6)).isoformat() if base_time else "unknown",
                "author": "ci-bot",
                "changes": "Minor logging improvements",
            },
        ]
        return {"recent_deployments": deploys}

    # -- check_dependency_health (MOCKED) ---------------------------------
    def check_dependency_health(self, dependency: str) -> dict:
        rng = _seeded_random("health", dependency)
        is_db = "db" in dependency.lower() or "postgres" in dependency.lower() or "sql" in dependency.lower() or "pool" in dependency.lower()
        if is_db:
            status = "degraded"
            detail = "Connection pool near saturation (98/100 connections in use). Increased wait times observed for new connection requests."
        else:
            status = rng.choice(["healthy", "healthy", "degraded"])
            detail = "Operating normally." if status == "healthy" else "Elevated latency observed but within tolerance."
        return {"dependency": dependency, "status": status, "detail": detail}

    # -- dispatcher --------------------------------------------------------
    def execute(self, tool_name: str, tool_input: dict) -> dict:
        if tool_name == "search_logs":
            return self.search_logs(**tool_input)
        if tool_name == "get_error_timeline":
            return self.get_error_timeline()
        if tool_name == "get_metrics":
            return self.get_metrics(**tool_input)
        if tool_name == "get_recent_deployments":
            return self.get_recent_deployments()
        if tool_name == "check_dependency_health":
            return self.check_dependency_health(**tool_input)
        return {"error": f"Unknown tool: {tool_name}"}