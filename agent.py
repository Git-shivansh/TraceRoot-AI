"""
agent.py
The agentic Root Cause Analysis loop - ANTHROPIC (Claude) implementation.

This is the "agentic AI" core of the project: instead of a single prompt,
Claude is given tools and allowed to take multiple investigative turns -
searching logs, pulling metrics, checking deploys, checking dependency
health - deciding for itself what to look at next, before producing a
final structured verdict.

See agent_openai.py for the equivalent implementation using OpenAI's API.
"""
import json
from typing import List

import anthropic

import config
from agent_common import SYSTEM_PROMPT, build_initial_user_message, extract_json
from log_parser import LogEntry
from tools import TOOL_SCHEMAS, ToolExecutor


def run_rca_agent(entries: List[LogEntry], verbose: bool = True) -> dict:
    """Runs the agentic RCA loop end-to-end and returns the final structured verdict."""
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "See README.md for setup instructions."
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    executor = ToolExecutor(entries)

    messages = [{"role": "user", "content": build_initial_user_message(entries)}]

    for turn in range(config.MAX_AGENT_TURNS):
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            text_blocks = [b.text for b in response.content if b.type == "text"]
            final_text = "\n".join(text_blocks)
            return extract_json(final_text)

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
    return extract_json("\n".join(text_blocks))