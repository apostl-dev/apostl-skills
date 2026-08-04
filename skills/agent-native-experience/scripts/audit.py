#!/usr/bin/env python3
"""Deterministic Agent Native Experience evidence scorer and report renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from safety import SensitiveOutputError, sanitize_data  # noqa: E402


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUBRIC = SKILL_ROOT / "references" / "rubric.v1.json"
STATUS_COEFFICIENT = {
    "pass": 1.0,
    "warn": 0.5,
    "fail": 0.0,
    "blocked": 0.0,
    "not_run": 0.0,
    "unknown": 0.0,
}
TERMINAL_GUIDE_STATUSES = {"passed", "failed", "blocked", "not_run", "excluded", "not_applicable"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        hostname = f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((scheme, hostname, path, query, ""))


def normalize_corpus(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for supplied in rows:
        if not isinstance(supplied, dict) or not str(supplied.get("url", "")).strip():
            continue
        row = dict(supplied)
        row["original_url"] = str(row["url"])
        row["url"] = canonicalize_url(str(row["url"]))
        grouped.setdefault(row["url"], []).append(row)

    status_priority = {"failed": 0, "blocked": 1, "not_run": 2, "passed": 3, "not_applicable": 4, "excluded": 5}
    normalized = []
    for url, duplicates in grouped.items():
        ordered_duplicates = sorted(
            duplicates,
            key=lambda row: (status_priority.get(str(row.get("status")), 99), json.dumps(row, sort_keys=True)),
        )
        row = dict(ordered_duplicates[0])
        row["url"] = url
        row["original_urls"] = sorted({str(item.get("original_url", item.get("url", ""))) for item in duplicates})
        row.pop("original_url", None)
        sources = set()
        redirects = []
        hashes = set()
        for item in duplicates:
            source = item.get("source")
            if isinstance(source, list):
                sources.update(str(value) for value in source)
            elif source:
                sources.add(str(source))
            for redirect in item.get("redirect_chain", []) if isinstance(item.get("redirect_chain"), list) else []:
                if str(redirect) not in redirects:
                    redirects.append(str(redirect))
            if item.get("content_hash"):
                hashes.add(str(item["content_hash"]))
            for field in ("auth_gate", "exclusion_reason", "reason", "blocker"):
                if not row.get(field) and item.get(field):
                    row[field] = item[field]
        row["sources"] = sorted(sources)
        row["redirect_chain"] = redirects
        if len(hashes) > 1:
            row["content_hashes"] = sorted(hashes)
        normalized.append(row)
    return sorted(normalized, key=lambda row: (str(row.get("url", "")), str(row.get("status", ""))))


def corpus_accounting(mode: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = normalize_corpus(rows)
    counts = {
        "discovered": len(ordered),
        "eligible": sum(row.get("status") not in {"excluded", "not_applicable"} for row in ordered),
        "attempted": sum(row.get("status") in {"passed", "failed", "blocked"} for row in ordered),
        "passed": sum(row.get("status") == "passed" for row in ordered),
        "failed": sum(row.get("status") == "failed" for row in ordered),
        "blocked": sum(row.get("status") == "blocked" for row in ordered),
        "not_run": sum(row.get("status") == "not_run" for row in ordered),
        "excluded": sum(row.get("status") in {"excluded", "not_applicable"} for row in ordered),
    }
    all_terminal = all(row.get("status") in TERMINAL_GUIDE_STATUSES for row in ordered)
    full_covered = (
        mode == "full"
        and bool(ordered)
        and all_terminal
        and counts["not_run"] == 0
        and counts["attempted"] == counts["eligible"]
    )
    frozen_payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "mode": mode,
        "frozen_sha256": hashlib.sha256(frozen_payload.encode()).hexdigest(),
        "full_documentation_covered": full_covered,
        "counts": counts,
        "rows": ordered,
    }


def _status_score(status: str) -> float | None:
    if status in {"not_applicable", "skip"}:
        return None
    return STATUS_COEFFICIENT.get(status, 0.0)


def _weighted_score(criteria: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> int:
    numerator = 0.0
    denominator = 0.0
    for criterion in criteria:
        result = results[criterion["id"]]
        coefficient = result.get("proportion")
        if coefficient is None:
            coefficient = _status_score(result["status"])
        if coefficient is None:
            continue
        weight = float(criterion["weight"])
        numerator += weight * coefficient
        denominator += weight
    return round(100 * numerator / denominator) if denominator else 0


def _journey_score(journey: dict[str, Any]) -> int:
    status = str(journey.get("status", "not_run"))
    if status == "pass" and journey.get("activation_reached") is True:
        return 100
    if status == "warn" and journey.get("activation_reached") is True:
        return 50
    return 0


def _rice(friction: dict[str, Any]) -> dict[str, Any]:
    raw = friction.get("rice") if isinstance(friction.get("rice"), dict) else {}
    values = {key: raw.get(key) for key in ("reach", "impact", "confidence", "effort")}
    missing = [key for key, value in values.items() if value is None]
    score = None
    if not missing:
        try:
            effort = float(values["effort"])
            score = round(float(values["reach"]) * float(values["impact"]) * float(values["confidence"]) / effort, 2) if effort > 0 else None
        except (TypeError, ValueError):
            score = None
    return {**values, "score": score, "missing": missing}


def build_report(rubric: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = sanitize_data(evidence, reject_keys=True)
    supplied = evidence.get("checks") if isinstance(evidence.get("checks"), dict) else {}
    results: dict[str, dict[str, Any]] = {}
    for criterion in rubric["criteria"]:
        item = supplied.get(criterion["id"], {})
        status = item.get("status", "unknown") if isinstance(item, dict) else "unknown"
        if status not in rubric["allowed_statuses"]:
            status = "unknown"
        proportion = item.get("proportion") if isinstance(item, dict) else None
        passed = item.get("passed") if isinstance(item, dict) else None
        total = item.get("total") if isinstance(item, dict) else None
        if proportion is None and isinstance(passed, (int, float)) and isinstance(total, (int, float)) and total > 0:
            proportion = passed / total
        if not isinstance(proportion, (int, float)) or not 0 <= float(proportion) <= 1:
            proportion = None
        unmet_dependencies = []
        if criterion["id"] in supplied and status != "skip":
            for expression in criterion.get("dependencies", []):
                alternatives = str(expression).split("|")
                if not any(results.get(dependency, {}).get("status") in {"pass", "warn"} for dependency in alternatives):
                    unmet_dependencies.append(str(expression))
            if unmet_dependencies:
                status = "skip"
                proportion = None
        results[criterion["id"]] = {
            "status": status,
            "evidence": item.get("evidence") if isinstance(item, dict) else None,
            "note": item.get("note") if isinstance(item, dict) else None,
            "proportion": float(proportion) if proportion is not None else None,
            "passed": passed,
            "total": total,
            "unmet_dependencies": unmet_dependencies,
        }

    by_category = {
        category: [criterion for criterion in rubric["criteria"] if criterion["category"] == category]
        for category in ("Docs", "Product")
    }
    agent_journey = evidence.get("agent_journey") if isinstance(evidence.get("agent_journey"), dict) else {}
    human_journey = evidence.get("human_journey") if isinstance(evidence.get("human_journey"), dict) else {}
    human_journey = {"mode": "primary", **human_journey}
    category_scores = {
        "Docs": _weighted_score(by_category["Docs"], results),
        "Product": _weighted_score(by_category["Product"], results),
        "Agent Journey": _journey_score(agent_journey),
        "Human Journey": _journey_score(human_journey),
    }
    category_weights = rubric["formula"]["category_weights"]
    raw_overall = round(sum(category_scores[name] * category_weights[name] for name in category_scores) / 100)
    all_required_pass = all(
        results[criterion["id"]]["status"] == "pass"
        for criterion in rubric["criteria"] if criterion.get("required")
    )
    perfect_gate = (
        all_required_pass
        and category_scores["Agent Journey"] == 100
        and category_scores["Human Journey"] == 100
    )
    overall = raw_overall if raw_overall < 100 or perfect_gate else 99

    blocker = str(agent_journey.get("blocker", "")).strip()
    if agent_journey.get("activation_reached") is not True and agent_journey.get("status") in {"blocked", "fail", "not_run"}:
        verdict_status = str(agent_journey.get("status"))
    elif any(result["status"] in {"fail", "blocked"} for result in results.values()):
        verdict_status = "blocked"
    elif any(result["status"] in {"warn", "unknown", "not_run"} for result in results.values()):
        verdict_status = "partial"
    else:
        verdict_status = "pass"

    frictions = []
    for friction in evidence.get("frictions", []) if isinstance(evidence.get("frictions"), list) else []:
        if isinstance(friction, dict):
            frictions.append({**friction, "rice": _rice(friction)})
    frictions.sort(key=lambda item: (
        item["rice"]["score"] is None,
        -(item["rice"]["score"] or 0),
        str(item.get("id", "")),
    ))

    corpus = evidence.get("corpus") if isinstance(evidence.get("corpus"), dict) else {}
    accounting = corpus_accounting(str(corpus.get("mode", "sample")), corpus.get("rows", []))
    journey = evidence.get("journey") if isinstance(evidence.get("journey"), dict) else {}

    return sanitize_data({
        "report_version": "agent-native-experience-report.v1",
        "rubric_version": rubric["rubric_version"],
        "executive_verdict": {"status": verdict_status, "blocker": blocker or None},
        "journey": journey,
        "environment": evidence.get("environment", {}),
        "score": {"overall": overall, "categories": category_scores, "formula": rubric["formula"]},
        "results": results,
        "criteria": rubric["criteria"],
        "agent_journey": agent_journey or {"status": "not_run", "activation_reached": False},
        "human_journey": human_journey or {"status": "not_run"},
        "corpus": accounting,
        "frictions": frictions,
        "provenance": evidence.get("provenance", []),
        "limitations": evidence.get("limitations", ["Unexecuted checks remain unknown or not_run."]),
        "public_artifacts": evidence.get("public_artifacts", []),
    }, reject_keys=True)


def _value(value: Any) -> str:
    return "missing" if value is None or value == "" else str(value)


def render_markdown(report: dict[str, Any]) -> str:
    journey = report["journey"]
    verdict = report["executive_verdict"]
    lines = [
        "# Agent Native Experience report",
        "",
        "## Executive verdict",
        "",
        f"- Status: **{verdict['status']}**",
        f"- Selected journey: {_value(journey.get('name'))}",
        f"- Target user or agent: {_value(journey.get('target'))}",
        f"- Activation event: {_value(journey.get('activation_event'))}",
    ]
    if verdict.get("blocker"):
        lines.append(f"- First faithful blocker: **{verdict['blocker']}**")

    lines += ["", "## Business impact", ""]
    if not report["frictions"]:
        lines.append("No measured business impact was supplied. Validate activation, time-to-first-value, support load, conversion, retention, launch risk, or partner readiness with an explicit metric owner.")
    for friction in report["frictions"]:
        lines += [
            f"- **{_value(friction.get('title'))}** — {_value(friction.get('business_consequence'))}",
            f"  - Evidence type: {_value(friction.get('impact_type'))}; metric: {_value(friction.get('metric'))}; owner: {_value(friction.get('metric_owner'))}",
        ]

    lines += [
        "", "## Scope and environment", "",
        f"- Environment: `{json.dumps(report['environment'], sort_keys=True, ensure_ascii=False)}`",
        f"- Corpus mode: {report['corpus']['mode']}",
        f"- Frozen corpus SHA-256: `{report['corpus']['frozen_sha256']}`",
        "", "## Score and rubric version", "",
        f"- Overall: **{report['score']['overall']} / 100**",
        f"- Rubric: `{report['rubric_version']}`",
    ]
    for category, score in report["score"]["categories"].items():
        lines.append(f"- {category}: {score} / 100")

    lines += [
        "", "## Source/corpus coverage", "",
        "| Discovered | Eligible | Attempted | Passed | Failed | Blocked | Not run | Excluded |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    counts = report["corpus"]["counts"]
    lines.append("| " + " | ".join(str(counts[key]) for key in ("discovered", "eligible", "attempted", "passed", "failed", "blocked", "not_run", "excluded")) + " |")
    lines.append(f"\nFull documentation covered: **{'yes' if report['corpus']['full_documentation_covered'] else 'no'}**")

    for heading, category in (("Agent-ready Docs", "Docs"), ("Agent-ready Product", "Product")):
        lines += ["", f"## {heading}", "", "| Check | Status | Evidence |", "| --- | --- | --- |"]
        for criterion in report["criteria"]:
            if criterion["category"] == category:
                result = report["results"][criterion["id"]]
                lines.append(f"| `{criterion['id']}` | {result['status']} | {_value(result.get('evidence'))} |")

    lines += ["", "## Agent quickstart trace", "", f"- Status: {report['agent_journey'].get('status', 'not_run')}", f"- Activation reached: {report['agent_journey'].get('activation_reached', False)}"]
    for step in report["agent_journey"].get("steps", []):
        lines.append(f"- {_value(step.get('source_step'))}: {_value(step.get('observation'))} (deviation: {_value(step.get('deviation'))})")

    lines += [
        "", "## Human Frictions", "",
        f"- Mode: {report['human_journey'].get('mode', 'primary')}",
        f"- Selected guide: {_value(report['human_journey'].get('selected_guide'))}",
        f"- Status: **{report['human_journey'].get('status', 'not_run')}**",
    ]
    if report["human_journey"].get("status", "not_run") == "not_run":
        lines.append(f"- Next action: {_value(report['human_journey'].get('next_action') or 'Have one representative human complete the same journey and record pre-activation observations.')}")
    for item in report["human_journey"].get("frictions", []):
        lines += [
            f"- {_value(item.get('step'))}: {_value(item.get('observation'))}",
            f"  - Severity: {_value(item.get('severity'))}",
            f"  - Evidence: {_value(item.get('evidence'))}",
            f"  - Smallest fix: {_value(item.get('smallest_fix'))}",
        ]

    lines += ["", "## Guide-by-guide coverage", "", "| URL | Sources | Redirects | Auth gate | Terminal status | Blocker or exclusion | Content hash |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["corpus"]["rows"]:
        lines.append(f"| {_value(row.get('url'))} | {_value(', '.join(row.get('sources', [])))} | {_value(' -> '.join(row.get('redirect_chain', [])))} | {_value(row.get('auth_gate'))} | {_value(row.get('status'))} | {_value(row.get('blocker') or row.get('exclusion_reason') or row.get('reason'))} | {_value(row.get('content_hash'))} |")

    lines += ["", "## Deduplicated friction evidence", ""]
    for friction in report["frictions"]:
        lines.append(f"- `{_value(friction.get('id'))}` {_value(friction.get('title'))}: {_value(friction.get('evidence'))}")
    lines += ["", "## Proposed fixes through activation", ""]
    for friction in report["frictions"]:
        lines.append(f"- `{_value(friction.get('id'))}` {_value(friction.get('smallest_fix'))}; verify: {_value(friction.get('next_verification'))}")

    lines += ["", "## RICE roadmap", "", "| ID | Reach | Impact | Confidence | Effort | Score | Missing inputs |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for friction in report["frictions"]:
        rice = friction["rice"]
        lines.append(f"| {_value(friction.get('id'))} | {_value(rice['reach'])} | {_value(rice['impact'])} | {_value(rice['confidence'])} | {_value(rice['effort'])} | {_value(rice['score'])} | {', '.join(rice['missing']) or 'none'} |")

    lines += ["", "## 30 / 60 / 90 day plan", ""]
    windows = ("30", "60", "90")
    for index, window in enumerate(windows):
        item = report["frictions"][index] if index < len(report["frictions"]) else {}
        lines.append(f"- **{window} days** — owner: {_value(item.get('owner'))}; action: {_value(item.get('smallest_fix'))}; signal: {_value(item.get('next_verification'))}; dependencies: {_value(item.get('dependencies'))}")

    lines += ["", "## Final action plan", ""]
    lines.append("1. Fix the first faithful blocker before optimizing the score.")
    lines.append("2. Re-run the exact activation journey in a clean environment.")
    lines.append("3. Turn current passing evidence into a recurring release gate.")
    lines += ["", "## Recurring-check recommendations", "", "- Re-run static agent-doc checks on docs releases and the selected first-value journey on product releases."]
    lines += ["", "## Provenance", ""]
    for source in report["provenance"]:
        lines.append(f"- {_value(source.get('url'))} — retrieved {_value(source.get('retrieved_at'))}; version {_value(source.get('version'))}")
    lines += ["", "## Limitations", ""]
    for limitation in report["limitations"]:
        lines.append(f"- {limitation}")
    lines += ["", "## Public artifact links", ""]
    for artifact in report["public_artifacts"]:
        lines.append(f"- {_value(artifact.get('name'))}: {_value(artifact.get('url'))}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    report = build_report(load_json(args.rubric), load_json(args.evidence))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["executive_verdict"]["status"], "score": report["score"]["overall"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
