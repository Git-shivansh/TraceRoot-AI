"""
report_generator.py
Turns the agent's structured JSON verdict into a readable Markdown report.
"""
from datetime import datetime


def generate_markdown_report(verdict: dict, log_file: str) -> str:
    lines = []
    lines.append("# Incident Root Cause Analysis Report")
    lines.append("")
    lines.append(f"**Log source:** `{log_file}`  ")
    lines.append(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}  ")
    lines.append(f"**Confidence:** {verdict.get('confidence', 'unknown').upper()}")
    lines.append("")

    lines.append("## Root Cause")
    lines.append(verdict.get("root_cause", "Not determined."))
    lines.append("")

    lines.append("## Summary")
    lines.append(verdict.get("summary", ""))
    lines.append("")

    affected = verdict.get("affected_services", [])
    if affected:
        lines.append("## Affected Services")
        for s in affected:
            lines.append(f"- {s}")
        lines.append("")

    timeline = verdict.get("incident_timeline", [])
    if timeline:
        lines.append("## Incident Timeline")
        for t in timeline:
            lines.append(f"- {t}")
        lines.append("")

    evidence = verdict.get("evidence", [])
    if evidence:
        lines.append("## Supporting Evidence")
        for e in evidence:
            lines.append(f"- {e}")
        lines.append("")

    actions = verdict.get("recommended_actions", [])
    if actions:
        lines.append("## Recommended Actions")
        lines.append("")
        lines.append("| Priority | Action | Rationale |")
        lines.append("|---|---|---|")
        for a in actions:
            lines.append(f"| {a.get('priority','-')} | {a.get('action','')} | {a.get('rationale','')} |")
        lines.append("")

    preventive = verdict.get("preventive_measures", [])
    if preventive:
        lines.append("## Preventive Measures")
        for p in preventive:
            lines.append(f"- {p}")
        lines.append("")

    return "\n".join(lines)