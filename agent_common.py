"""
agent_common.py
Logic shared by BOTH the Anthropic agent (agent.py) and the OpenAI agent
(agent_openai.py) - the system prompt, building the first message from
parsed logs, and extracting the final JSON verdict from the model's text.

Nothing in this file is provider-specific. This is what keeps the project
"provider-agnostic": if you switch LLM providers, only the API-calling code
changes - the prompt and parsing logic here stays exactly the same.
"""
import json
import re
from typing import List

import config
from log_parser import LogEntry, summarize_entries

SYSTEM_PROMPT = """You are an expert Site Reliability Engineer (SRE) AI agent \
performing root cause analysis (RCA) on a production incident.

You have been given a summary of an application log file and a set of tools \
to investigate further (search logs, check metrics, check recent deployments, \
check dependency health, get an error timeline).

Investigate like a real SRE would:
1. Form a hypothesis from the initial summary.
2. Use tools to gather evidence that confirms or rules out that hypothesis.
3. Follow the evidence - if something looks like a cascading failure, trace it \
back to the earliest root trigger, not just the most visible symptom.
4. Don't stop at the first error you see - distinguish root cause from \
downstream symptoms.

When you are confident in your conclusion (usually after 2-5 tool calls), \
respond with ONLY a single JSON object (no markdown fences, no extra prose) \
matching exactly this schema:

{
  "root_cause": "string - concise root cause statement",
  "confidence": "high | medium | low",
  "summary": "string - 2-4 sentence plain-English explanation of what happened and why",
  "evidence": ["string", "..."],
  "affected_services": ["string", "..."],
  "incident_timeline": ["string - short chronological bullet points", "..."],
  "recommended_actions": [
    {"priority": "P0|P1|P2", "action": "string", "rationale": "string"}
  ],
  "preventive_measures": ["string", "..."]
}

Do not output this JSON until you have actually gathered evidence using the tools.
"""


def build_initial_user_message(entries: List[LogEntry]) -> str:
    summary = summarize_entries(entries)
    sample_lines = []
    shown = 0
    for e in entries:
        if e.level in ("ERROR", "FATAL", "CRITICAL", "WARN", "WARNING"):
            ts = e.timestamp.isoformat() if e.timestamp else "unknown-time"
            line = f"[{ts}] {e.level} ({e.service}) {e.message}"
            if e.stack_trace:
                line += "\n    " + "\n    ".join(e.stack_trace[:3])
            sample_lines.append(line)
            shown += 1
        if shown >= config.INITIAL_LOG_SAMPLE_SIZE:
            break

    return (
        f"LOG FILE SUMMARY:\n{json.dumps(summary, indent=2)}\n\n"
        f"SAMPLE OF WARNING/ERROR LINES (showing up to {config.INITIAL_LOG_SAMPLE_SIZE}):\n"
        + "\n".join(sample_lines)
        + "\n\nInvestigate this incident using the available tools, then produce "
          "the final JSON verdict described in your instructions."
    )


def extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from the model's final text,
    in case it wraps it in markdown fences despite instructions."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise