"""
Configuration for the AI Incident Root Cause Analyzer.
Supports either Anthropic (Claude) or OpenAI (GPT) as the LLM provider -
pick which one to use with main.py's --provider flag.
"""
import os

# --- Anthropic (Claude) ---
# export ANTHROPIC_API_KEY="sk-ant-..."
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"

# --- OpenAI (GPT) ---
# export OPENAI_API_KEY="sk-..."
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o"

# Which provider to use if --provider isn't passed on the command line
DEFAULT_PROVIDER = "openai"  # or "openai"

# Safety cap on how many tool-use "investigation turns" the agent can take
# before it is forced to give a final answer.
MAX_AGENT_TURNS = 8

# How many raw log lines to show the agent up front (it can fetch more via tools)
INITIAL_LOG_SAMPLE_SIZE = 40