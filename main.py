"""
main.py
CLI entry point for the AI Incident Root Cause Analyzer.

Usage:
    python main.py --log sample_logs/sample_app.log
    python main.py --log sample_logs/sample_app.log --output report.md --json verdict.json
"""
import argparse
import json
import sys

from agent import run_rca_agent
from log_parser import parse_log_file
from report_generator import generate_markdown_report


def main():
    parser = argparse.ArgumentParser(description="AI Incident Root Cause Analyzer")
    parser.add_argument("--log", required=True, help="Path to the application log file to analyze")
    parser.add_argument("--output", default="rca_report.md", help="Path to write the Markdown report")
    parser.add_argument("--json", default=None, help="Optional path to also write the raw JSON verdict")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-tool-call progress output")
    args = parser.parse_args()

    print(f"Parsing log file: {args.log}")
    entries = parse_log_file(args.log)
    if not entries:
        print("No parseable log entries found. Check the log format / LOG_LINE_RE in log_parser.py.")
        sys.exit(1)
    print(f"Parsed {len(entries)} log entries.")

    print("Running agentic root cause analysis (this may take a few tool-use turns)...")
    verdict = run_rca_agent(entries, verbose=not args.quiet)

    report_md = generate_markdown_report(verdict, args.log)
    with open(args.output, "w") as f:
        f.write(report_md)
    print(f"\nReport written to: {args.output}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(verdict, f, indent=2)
        print(f"Raw JSON verdict written to: {args.json}")

    print("\n" + "=" * 70)
    print(report_md)


if __name__ == "__main__":
    main()