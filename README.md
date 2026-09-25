# TraceRoot-AI — Incident Root Cause Analyzer

> **Agentic AI system** that autonomously investigates production incidents by orchestrating multi-turn tool-use loops across log search, metrics, deployment history, and dependency health — replacing single-shot LLM prompts with iterative SRE-style reasoning.

🔗 **GitHub:** https://github.com/Git-shivansh/TraceRoot-AI

---

## What This Project Does (One Line)

Upload a production log file → AI agent investigates like a real SRE (using tools, not guessing) → get a structured report with root cause, evidence, and prioritized P0/P1/P2 fixes.

---

## Why This Is "Agentic AI" and Not Just "GenAI"

This is the most important thing to understand about this project.

| Normal GenAI (ChatGPT approach) | TraceRoot-AI (Agentic approach) |
|---|---|
| Paste logs → one-shot guess | Agent decides what to investigate next |
| No verification of hypothesis | Tools called to gather real evidence |
| Context limit — large logs fail | Only summary sent upfront, tools fetch rest |
| Free-form text output | Structured JSON — machine-readable |
| Cannot integrate with pipeline | Output plugs into Slack, Jira, alerts |

**The core difference:** A single-shot LLM prompt says *"there appear to be database errors."* This system calls `get_metrics("order-service")`, confirms 98/100 connections are used, calls `get_recent_deployments()`, finds the deploy 42 minutes ago that halved the pool size, and says *"Root cause: v2.14.0 deploy reduced DB connection pool from 200 to 100, causing exhaustion under normal traffic load."* Evidence-backed, not a guess.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     USER ENTRY POINTS                       │
│                                                             │
│   CLI: python main.py --log app.log --provider openai       │
│   WEB: python web_app.py → http://127.0.0.1:5100           │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 1: INGESTION — log_parser.py             │
│                                                             │
│  Raw .log file                                              │
│       │  regex (LOG_LINE_RE)                                │
│       ▼                                                     │
│  LogEntry[] — {timestamp, level, service, message,          │
│                stack_trace, raw}                            │
│       │  summarize_entries()                                │
│       ▼                                                     │
│  Summary — {total, level_counts, services, time_range}      │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│           LAYER 2: SHARED CORE — agent_common.py            │
│                                                             │
│  SYSTEM_PROMPT          ← how AI must behave                │
│  build_initial_user_message()  ← first brief to AI         │
│  extract_json()         ← parse AI's final verdict          │
└──────────┬───────────────────────┬──────────────────────────┘
           │                       │
           ▼                       ▼
┌──────────────────┐   ┌───────────────────────┐
│  LAYER 3A        │   │  LAYER 3B             │
│  agent.py        │   │  agent_openai.py      │
│  Anthropic SDK   │   │  OpenAI SDK           │
│                  │   │                       │
│  response        │   │  response.choices[0]  │
│  .content blocks │   │  .message.tool_calls  │
└────────┬─────────┘   └──────────┬────────────┘
         └──────────┬─────────────┘
                    │ both call same ToolExecutor
                    ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 4: TOOLS — tools.py                      │
│                                                             │
│  TOOL_SCHEMAS        → Anthropic format                     │
│  OPENAI_TOOL_SCHEMAS → auto-converted from above           │
│                                                             │
│  ToolExecutor:                                              │
│  ├── search_logs()           ← REAL — searches LogEntry[]  │
│  ├── get_error_timeline()    ← REAL — buckets by minute    │
│  ├── get_metrics()           ← MOCKED (swap → Datadog)     │
│  ├── get_recent_deployments()← MOCKED (swap → GitHub API)  │
│  └── check_dependency_health()←MOCKED (swap → health APIs) │
└──────────────────┬──────────────────────────────────────────┘
                   │ verdict dict
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 5: OUTPUT                                │
│                                                             │
│  report_generator.py → rca_report.md                       │
│  web_app.py → JSON → browser renders structured report     │
└─────────────────────────────────────────────────────────────┘
```

---

## The Agentic Investigation Loop (How It Works Internally)

```
Agent receives initial brief (log summary + first 40 error lines)
        │
        ▼
Turn 1: API call → AI thinks → decides to call get_error_timeline()
        │ result appended to message history
        ▼
Turn 2: API call → sees errors spike at 09:16 in order-service
        │ calls search_logs("connection pool")
        ▼
Turn 3: finds "Connection pool exhausted" — calls get_metrics("order-service")
        │ confirms 98/100 DB connections in use
        ▼
Turn 4: calls get_recent_deployments()
        │ finds deploy 42 mins before incident — pool size 200→100
        ▼
Turn 5: calls check_dependency_health("db-pool")
        │ status: "degraded"
        ▼
No more tool_calls in response → extract final JSON verdict
        │
        ▼
{
  "root_cause": "v2.14.0 deploy reduced DB connection pool from 200→100,
                 causing exhaustion under normal traffic load",
  "confidence": "high",
  "evidence": [...],
  "affected_services": ["order-service", "inventory-service", "payment-service"],
  "recommended_actions": [
    {"priority": "P0", "action": "Revert pool to 200", "rationale": "..."},
    {"priority": "P1", "action": "Add pool saturation alert", "rationale": "..."}
  ]
}
```

**Safety cap:** `MAX_AGENT_TURNS = 8` — if agent hasn't concluded in 8 turns, a force prompt is sent: *"Give verdict now based on everything gathered."* Prevents infinite loops and runaway API costs.

---

## File Structure

```
TraceRoot-AI/
│
├── main.py               ← CLI entry point (--log, --provider, --output flags)
├── web_app.py            ← Flask web UI (upload file → see report in browser)
├── config.py             ← API keys, model names, turn limits
│
├── log_parser.py         ← Regex-based log parser → structured LogEntry objects
├── agent_common.py       ← Shared: system prompt, message builder, JSON extractor
├── agent.py              ← Anthropic-specific API call + response parsing
├── agent_openai.py       ← OpenAI-specific API call + response parsing
├── tools.py              ← Tool schemas (both formats) + ToolExecutor class
├── report_generator.py   ← JSON verdict → Markdown report
│
├── templates/
│   └── index.html        ← Web UI page
├── static/
│   ├── style.css         ← Dark terminal-themed design
│   └── script.js         ← Upload, fetch, animated tool-call feed, render report
│
├── sample_logs/
│   └── sample_app.log    ← Demo: DB pool exhaustion → cascading failure
└── live_demo/
    ├── app.py            ← Real Flask app that auto-generates logs
    └── trigger_errors.py ← Sends concurrent requests to trigger real errors
```

---

## The 5 Tools — What Each Does

### Real Tools (operate on actual log data)

**`search_logs(keyword, max_results=15)`**
Case-insensitive substring search across all LogEntry message + stack_trace fields. Returns matching entries with timestamp, level, service. Agent uses this to follow specific error patterns — e.g. `search_logs("connection pool exhausted")`.

**`get_error_timeline()`**
Groups ERROR/FATAL/CRITICAL entries by minute, by service. Uses Python `Counter` + `defaultdict`. Shows exactly when errors started and whether they cascaded across services — key for identifying the first point of failure.

### Mocked Tools (swap these for real APIs in production)

**`get_metrics(service)`**
Returns CPU%, memory%, p99 latency ms, error rate%, active DB connections. Currently seeded-random (deterministic per service name using `hashlib`). Production: replace with Datadog/Prometheus/CloudWatch API call.

**`get_recent_deployments()`**
Returns list of recent deploys with service, version, deploy time, author, changelog. Currently hardcoded mock. Production: replace with GitHub Actions/ArgoCD API call.

**`check_dependency_health(dependency)`**
Returns health status and detail for a named dependency (db, cache, API). Currently rule-based mock — DB-related names return "degraded". Production: replace with actual health-check endpoint calls.

---

## Provider-Agnostic Design — How It Works

The same investigation runs on either Anthropic Claude or OpenAI GPT. This is not a cosmetic feature — it required solving real API differences.

### The 4 Concrete Differences Handled

**1. System prompt location:**
```python
# Anthropic — separate parameter
client.messages.create(system=SYSTEM_PROMPT, messages=[...])

# OpenAI — first message in list
messages = [{"role": "system", "content": SYSTEM_PROMPT}, ...]
```

**2. Tool schema format:**
```python
# Anthropic
{"name": "get_metrics", "input_schema": {"properties": {...}}}

# OpenAI
{"type": "function", "function": {"name": "get_metrics", "parameters": {...}}}
```
Solved with `_to_openai_schema()` — auto-converts Anthropic schemas to OpenAI format so both always stay in sync.

**3. Tool call arguments:**
```python
# Anthropic — already a Python dict
tool_input = block.input

# OpenAI — JSON string, must parse
tool_input = json.loads(tc.function.arguments)
```

**4. Tool result message format:**
```python
# Anthropic — tool_result block inside user message
{"type": "tool_result", "tool_use_id": id, "content": result}

# OpenAI — separate message with role="tool"
{"role": "tool", "tool_call_id": id, "content": result}
```

### Adding a Third Provider (e.g. Gemini)
Only 3 steps needed — existing code untouched:
1. Add `GEMINI_API_KEY` and `GEMINI_MODEL` to `config.py`
2. Create `agent_gemini.py` importing from `agent_common.py`
3. Add `--provider gemini` option to `main.py`

---

## Log Parser — How It Works

**Expected format:**
```
2026-06-25 09:16:01,553 ERROR [order-service] OrderProcessor - Failed to process order 8841
java.sql.SQLException: Connection pool exhausted
    at com.app.db.Pool.get(Pool.java:88)
    at com.app.order.OrderProcessor.process(OrderProcessor.java:142)
```

**What the parser does:**
- `LOG_LINE_RE` regex extracts named groups: `timestamp`, `level`, `service`, `rest`
- Timestamp string → Python `datetime` object (supports 6 different timestamp formats)
- Lines starting with whitespace, `at `, `Caused by:` → appended to previous entry's `stack_trace`
- Output: `List[LogEntry]` — structured Python objects, not raw strings

**Format mismatch:** If your logs are in JSON format (`{"level": "error", "msg": "..."}`), the parser returns 0 entries. Fix: detect first line format, use JSON parser branch. This is a known limitation.

---

## JSON Verdict Schema

```json
{
  "root_cause": "Concise one-line root cause statement",
  "confidence": "high | medium | low",
  "summary": "2-4 sentence human-readable explanation",
  "evidence": [
    "Pool exhaustion warnings 4 minutes before first ERROR",
    "Metrics confirm 98/100 DB connections in use",
    "Deploy changelog: pool size reduced 200 → 100"
  ],
  "affected_services": ["order-service", "inventory-service", "payment-service"],
  "incident_timeline": [
    "09:12 — Pool usage warnings begin (82/100)",
    "09:16 — First connection exhaustion errors",
    "09:16:20 — inventory-service timeouts start",
    "09:18:40 — Circuit breaker opens"
  ],
  "recommended_actions": [
    {
      "priority": "P0",
      "action": "Revert DB connection pool to 200",
      "rationale": "Restores prior capacity, immediately stops exhaustion"
    },
    {
      "priority": "P1",
      "action": "Add monitoring alert at 80% pool utilization",
      "rationale": "Early warning before exhaustion threshold"
    }
  ],
  "preventive_measures": [
    "Require load testing before pool size configuration changes",
    "Add pool saturation to deployment health checks"
  ]
}
```

**Why structured JSON and not free text:**
- Frontend can render it programmatically (priority badges, tables, timeline)
- Can auto-create Jira tickets from `recommended_actions`
- `confidence` field signals when human review is critical
- `rationale` field means engineers understand *why* before acting

---

## Web UI — How It Works

```
Browser                          web_app.py                    Agent
   │                                  │                           │
   │── POST /api/analyze ────────────►│                           │
   │   (log file + provider)          │── parse_log_file() ──────►│
   │                                  │   redirect_stdout         │
   │                                  │── run_rca_agent() ───────►│
   │                                  │                           │── tool calls loop
   │                                  │◄─ verdict dict ───────────│
   │◄─ JSON response ─────────────────│                           │
   │   {tool_calls[], verdict}        │                           │
   │                                  │                           │
   │ animate tool call feed           │                           │
   │ render structured report         │                           │
```

**Key trick — `contextlib.redirect_stdout`:**
Agent's verbose print statements (`[agent turn 1] calling tool: get_metrics(...)`) are captured by redirecting stdout to a `StringIO` buffer during the agent run. These are parsed and sent to the browser to power the live investigation feed animation — without changing a single line in `agent.py`.

---

## Setup and Run

### Prerequisites
- Python 3.9+
- OpenAI API key (get from platform.openai.com) OR Anthropic API key

### Installation
```bash
git clone https://github.com/Git-shivansh/TraceRoot-AI
cd TraceRoot-AI
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Set API Key
```bash
# OpenAI
export OPENAI_API_KEY="sk-..."          # Mac/Linux
setx OPENAI_API_KEY "sk-..."            # Windows (open new terminal after)

# OR Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Run — Web UI (Recommended for demo)
```bash
python web_app.py
# Open http://127.0.0.1:5100 in browser
# Upload sample_logs/sample_app.log
# Select provider → Run analysis
```

### Run — CLI
```bash
python main.py --log sample_logs/sample_app.log --provider openai
# Report saved to rca_report.md
# Also printed to terminal
```

### Generate Real Logs (Optional Demo)
```bash
# Terminal 1 — start real Flask app
cd live_demo && python app.py

# Terminal 2 — trigger real errors (20 concurrent requests, pool max=5)
python trigger_errors.py

# Then analyze the real auto-generated log
cd .. && python main.py --log live_demo/live_app.log --provider openai
```

---

## The Sample Incident — What the Demo Log Shows

`sample_logs/sample_app.log` tells a realistic cascading failure story:

```
09:00 — order-service starts (v2.14.0 — pool size was halved in this deploy)
09:12 — Pool usage warnings begin (82/100)
09:14 — Pool usage 91/100
09:15 — Pool usage 97/100
09:16 — FIRST ERRORS: "Connection pool exhausted" on order-service
09:16:20 — inventory-service: "Timeout calling order-service"
09:16:25 — payment-service: "order-service returned 503"
09:17 — More exhaustion errors cascade
09:18:40 — FATAL: Circuit breaker OPEN on db-pool
09:20 — PagerDuty alert fires
```

**What the agent correctly identifies:**
- Root cause: the v2.14.0 deploy (42 mins before incident) that reduced pool from 200→100
- NOT: "database errors" (that's the symptom, not the cause)
- NOT: "inventory-service timeouts" (that's downstream effect)
- Evidence chain: warnings → metrics confirmation → deploy history → health check

---

## Design Decisions and Tradeoffs

### Decision: Regex parser vs JSON parser
**Chose:** Regex for human-readable log format
**Tradeoff:** Modern apps using JSON structured logging (`structlog`, `winston`) will return 0 entries. Fix in production: auto-detect first line format, use appropriate parser branch.

### Decision: Mocked tools vs Real API integrations
**Chose:** Mocked tools with seeded-random data for demo
**Tradeoff:** Agent conclusions are partly based on fake data. This is the biggest gap between current prototype and production-ready system. All mock functions are isolated — swap internals without touching agent logic.

### Decision: Synchronous processing vs Async
**Chose:** Synchronous — user waits 30-60 seconds
**Tradeoff:** Poor UX for production. Fix: Celery + Redis job queue, return `job_id` immediately, frontend polls `/api/status/{job_id}` or receives WebSocket live updates.

### Decision: Flask vs FastAPI
**Chose:** Flask — simpler, matches synchronous agent
**Tradeoff:** FastAPI better for async/await pattern needed in production. Flask is fine for demo scope.

### Decision: `MAX_AGENT_TURNS = 8`
**Why 8:** Average real incident needs 2-4 tools. Complex cascading failures need 5-6. 8 gives safety margin. At ~$0.01-0.03 per analysis with GPT-4o, cost is controlled.
**If too low:** Agent gives verdict with incomplete evidence → `confidence: low`
**If no cap:** Infinite loop possible with weak models or ambiguous logs.

---

## Known Limitations (Honest Assessment)

| Limitation | Impact | Production Fix |
|---|---|---|
| Mocked metrics/deploys/health | Agent conclusions partly on fake data | Integrate Datadog, GitHub API, health endpoints |
| Regex parser only | JSON-format logs return 0 entries | Auto-detect format, dual parser |
| Synchronous processing | 30-60s wait, one user at a time | Celery + Redis + WebSocket |
| No unit tests | Regressions not caught automatically | pytest for parser, tools, extract_json |
| No authentication on web UI | Anyone with access can upload logs | JWT auth for production |
| Large files load into memory | 100MB+ files will be slow/crash | Streaming parser, Elasticsearch backend |
| No feedback loop | Wrong verdicts not corrected | Thumbs up/down → retraining data |

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.9+ | Rich AI/ML ecosystem, clean async support |
| LLM Providers | Anthropic Claude, OpenAI GPT-4o | Provider-agnostic design, cost/availability options |
| Web Framework | Flask | Lightweight, matches synchronous agent, easy to demo |
| Log Parsing | Pure Python + regex | Zero dependencies, full control over parsing logic |
| Frontend | Vanilla HTML/CSS/JS | No build step, easy to inspect and modify |
| Demo App | Flask (live_demo/app.py) | Generates real logs to prove automatic log generation |

---

*Built to demonstrate Agentic AI concepts — autonomous multi-turn tool-use orchestration applied to a real SRE problem domain.*
