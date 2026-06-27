"""
agent_openai.py
The agentic Root Cause Analysis loop - OPENAI implementation.

Functionally identical to agent.py (same prompt, same tools, same final
JSON verdict) - only the API call shape and response parsing differ,
because OpenAI's tool-calling API is structured differently from
Anthropic's.

Key differences from agent.py, all isolated to this one file:
  1. System prompt is the FIRST message in the list (role="system"),
     not a separate `system=` parameter.
  2. Tool calls come back in `response.choices[0].message.tool_calls`,
     not as blocks inside `response.content`.
  3. Tool call arguments arrive as a JSON STRING that must be parsed with
     json.loads() - Anthropic gives you an already-parsed dict.
  4. Tool results are sent back as their own message with role="tool" and
     a `tool_call_id`, not as a "tool_result" content block.
"""
import json
from typing import List

from openai import OpenAI

import config
from agent_common import SYSTEM_PROMPT, build_initial_user_message, extract_json
from log_parser import LogEntry
from tools import OPENAI_TOOL_SCHEMAS, ToolExecutor


def run_rca_agent_openai(entries: List[LogEntry], verbose: bool = True) -> dict:
    """Runs the agentic RCA loop end-to-end using OpenAI and returns the
    final structured verdict (same shape as the Anthropic version)."""
    if not config.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. "
            "See README.md for setup instructions."
        )

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    executor = ToolExecutor(entries)

    # OpenAI puts the system prompt as a regular message at the start.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_initial_user_message(entries)},
    ]

    for turn in range(config.MAX_AGENT_TURNS):
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            tools=OPENAI_TOOL_SCHEMAS,
        )

        message = response.choices[0].message

        # Must append the assistant message (with its tool_calls) back into
        # history exactly as returned, or OpenAI will reject the next call.
        messages.append(message.model_dump(exclude_none=True))

        tool_calls = message.tool_calls

        if not tool_calls:
            # No more tool calls -> model should have given the final JSON
            return extract_json(message.content or "")

        if verbose:
            for tc in tool_calls:
                print(f"  [agent turn {turn+1}] calling tool: {tc.function.name}({tc.function.arguments})")

        for tc in tool_calls:
            try:
                tool_input = json.loads(tc.function.arguments) if tc.function.arguments else {}
                result = executor.execute(tc.function.name, tool_input)
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    # Hit max turns without a clean final answer - force one last call.
    messages.append({
        "role": "user",
        "content": "You've reached the investigation limit. Based on everything "
                    "gathered so far, output ONLY the final JSON verdict now.",
    })
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
    )
    return extract_json(response.choices[0].message.content or "")