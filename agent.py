"""
agent.py
The agentic Root Cause Analysis loop.

This is the "agentic AI" core of the project: instead of a single prompt,
Claude is given tools and allowed to take multiple investigative turns -
searching logs, pulling metrics, checking deploys, checking dependency
health - deciding for itself what to look at next, before producing a
final structured verdict.
"""
import json
import re
from typing import List

import anthropic

import config
from log_parser import LogEntry, summarize_entries
from tools import TOOL_SCHEMAS, ToolExecutor

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


def _build_initial_user_message(entries: List[LogEntry]) -> str:
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


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from the model's final text,
    in case it wraps it in markdown fences despite instructions."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to grabbing the largest {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def run_rca_agent(entries: List[LogEntry], verbose: bool = True) -> dict:
    """Runs the agentic RCA loop end-to-end and returns the final structured verdict."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "See README.md for setup instructions."
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    executor = ToolExecutor(entries)

    messages = [{"role": "user", "content": _build_initial_user_message(entries)}]

    for turn in range(config.MAX_AGENT_TURNS):
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Collect assistant content for the conversation history
        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # No more tool calls -> model should have given final JSON
            text_blocks = [b.text for b in response.content if b.type == "text"]
            final_text = "\n".join(text_blocks)
            return _extract_json(final_text)

        if verbose:
            for tb in tool_use_blocks:
                print(f"  [agent turn {turn+1}] calling tool: {tb.name}({tb.input})")

        tool_results = []
        for tb in tool_use_blocks:
            try:
                result = executor.execute(tb.name, tb.input)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": json.dumps(result),
            })

        messages.append({"role": "user", "content": tool_results})

    # Hit max turns without a clean final answer - force one last call asking
    # for the JSON verdict based on everything gathered so far.
    messages.append({
        "role": "user",
        "content": "You've reached the investigation limit. Based on everything "
                    "gathered so far, output ONLY the final JSON verdict now.",
    })
    response = client.messages.create(
        model=config.MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    text_blocks = [b.text for b in response.content if b.type == "text"]
    return _extract_json("\n".join(text_blocks))