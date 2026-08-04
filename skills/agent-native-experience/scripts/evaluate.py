#!/usr/bin/env python3
"""Execute deterministic routing and report-synthesis evaluation cases."""

from __future__ import annotations

import json
import re
from pathlib import Path

from audit import build_report, load_json, render_markdown


ROOT = Path(__file__).resolve().parents[1]


def resolves_to_skill(prompt: str) -> bool:
    return re.search(
        r"agent[- ]native|agent (?:readiness|experience|friction)|\bAX\b|llms\.txt|"
        r"(?:audit|assess|score|clean-room|30/60/90).*(?:docs|quickstart|onboarding|developer product)|"
        r"(?:quickstart|onboarding).*(?:agent|friction)|Apostl Journey Check|AI agent.*(?:register|credentials|first value)",
        prompt,
        re.IGNORECASE,
    ) is not None


def synthesis_evidence(case: dict) -> dict:
    supplied = case.get("input", {})
    evidence = {
        "journey": {"name": supplied.get("journey", "Quickstart"), "target": "agent", "activation_event": "first value"},
        "checks": {},
        "agent_journey": supplied.get("agent_journey", {"status": "not_run", "activation_reached": False}),
        "human_journey": supplied.get("human_journey", {"status": "not_run"}),
        "corpus": {"mode": supplied.get("mode", "sample"), "rows": supplied.get("rows", [])},
        "frictions": [],
    }
    if isinstance(supplied.get("friction"), dict):
        rice = supplied["friction"]
        evidence["frictions"] = [{
            "id": "F-1", "title": "Fixture friction", "evidence": "fixture",
            "business_consequence": "Activation delay", "impact_type": "hypothesis",
            "metric": "time_to_first_value", "metric_owner": None, "rice": rice,
        }]
    return evidence


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    routing_failures = []
    routing = jsonl(ROOT / "routing-eval.jsonl")
    for case in routing:
        actual = resolves_to_skill(str(case["prompt"]))
        if actual is not case["should_trigger"]:
            routing_failures.append(case["prompt"])

    rubric = load_json(ROOT / "references" / "rubric.v1.json")
    synthesis_failures = []
    synthesis = jsonl(ROOT / "evals" / "synthesis-eval.jsonl")
    for case in synthesis:
        rendered = render_markdown(build_report(rubric, synthesis_evidence(case)))
        folded = rendered.casefold()
        missing = [value for value in case["must_include"] if value.casefold() not in folded]
        forbidden = [value for value in case["must_not_include"] if value.casefold() in folded]
        if missing or forbidden:
            synthesis_failures.append({"id": case["id"], "missing": missing, "forbidden": forbidden})

    receipt = {
        "routing": {"executed": len(routing), "failed": len(routing_failures), "failures": routing_failures},
        "synthesis": {"executed": len(synthesis), "failed": len(synthesis_failures), "failures": synthesis_failures},
        "provider_receipt": "UNKNOWN: requires three distinct frontier providers after release revision is frozen",
    }
    print(json.dumps(receipt, sort_keys=True))
    return 1 if routing_failures or synthesis_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
