#!/usr/bin/env python3
"""Deterministic Agent Native Experience evidence scorer and report renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
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
BUSINESS_EVIDENCE_VERSION = "agent-native-business-evidence.v1"
BUSINESS_CATEGORIES = ("market", "competitors", "buyers")
BUSINESS_STATUSES = {"validated", "hypothesis", "unverified", "stale", "unknown", "not_run"}
BUSINESS_CLAIM_KINDS = {"observed", "derived", "hypothesis"}
MAX_BUSINESS_EVIDENCE_WINDOW = timedelta(days=30)


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


def _valid_corpus_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
        _ = parsed.port
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


def normalize_corpus(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for supplied in rows:
        if not isinstance(supplied, dict):
            continue
        row = dict(supplied)
        original_url = str(row.get("url", "")).strip()
        row["original_url"] = original_url
        row["url_valid"] = _valid_corpus_url(original_url)
        row["url"] = canonicalize_url(original_url) if row["url_valid"] else original_url or "[missing-url]"
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
        conflicts = []
        for field in ("content_hash", "owner", "status"):
            values = {str(item[field]) for item in duplicates if item.get(field) not in (None, "")}
            if len(values) > 1:
                conflicts.append(field)
        if conflicts:
            row["duplicate_conflicts"] = conflicts
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
    incomplete_fields: dict[str, list[str]] = {}
    duplicate_conflicts = {
        str(row["url"]): list(row["duplicate_conflicts"])
        for row in ordered if row.get("duplicate_conflicts")
    }
    for row in ordered:
        missing = []
        if row.get("url_valid") is not True:
            missing.append("url")
        if not row.get("sources"):
            missing.append("source")
        if row.get("status") not in {"excluded", "not_applicable"} and not row.get("content_hash"):
            missing.append("content_hash")
        if not row.get("owner"):
            missing.append("owner")
        if row.get("status") not in TERMINAL_GUIDE_STATUSES:
            missing.append("execution_status")
        if row.get("duplicate_conflicts"):
            missing.append("duplicate_conflict")
        if row.get("status") in {"excluded", "not_applicable"} and not (row.get("exclusion_reason") or row.get("reason")):
            missing.append("exclusion_reason")
        if missing:
            incomplete_fields[str(row.get("url", "unknown"))] = missing
    full_covered = (
        mode == "full"
        and bool(ordered)
        and all_terminal
        and not incomplete_fields
        and not duplicate_conflicts
        and all(row.get("status") in {"passed", "failed", "excluded", "not_applicable"} for row in ordered)
    )
    frozen_payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "mode": mode,
        "frozen_sha256": hashlib.sha256(frozen_payload.encode()).hexdigest(),
        "full_documentation_covered": full_covered,
        "incomplete_fields": incomplete_fields,
        "duplicate_conflicts": duplicate_conflicts,
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
    if not friction.get("metric_owner"):
        missing.append("metric_owner")
    score = None
    if not missing:
        try:
            effort = float(values["effort"])
            score = round(float(values["reach"]) * float(values["impact"]) * float(values["confidence"]) / effort, 2) if effort > 0 else None
        except (TypeError, ValueError):
            score = None
    return {**values, "score": score, "missing": missing}


def _parse_rfc3339_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _has_timestamp(value: Any) -> bool:
    return _parse_rfc3339_utc(value) is not None


def _freshness_invalid_fields(observed_value: Any, valid_until_value: Any, *, now: datetime | None = None) -> list[str]:
    observed_at = _parse_rfc3339_utc(observed_value)
    valid_until = _parse_rfc3339_utc(valid_until_value)
    missing = []
    if observed_at is None:
        missing.append("observed_at")
    if valid_until is None:
        missing.append("valid_until")
    if observed_at and valid_until:
        current = now or datetime.now(timezone.utc)
        if valid_until <= observed_at or valid_until - observed_at > MAX_BUSINESS_EVIDENCE_WINDOW:
            missing.append("valid_until_window")
        elif current > valid_until:
            missing.append("stale")
        elif observed_at > current:
            missing.append("observed_at_future")
    return missing


def normalize_business_evidence(value: Any) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    version_valid = supplied.get("version") == BUSINESS_EVIDENCE_VERSION
    output: dict[str, Any] = {
        "version": supplied.get("version") if version_valid else BUSINESS_EVIDENCE_VERSION,
        "version_valid": version_valid,
    }
    for category in BUSINESS_CATEGORIES:
        records = supplied.get(category) if isinstance(supplied.get(category), list) else []
        normalized = []
        for record in records:
            item = dict(record) if isinstance(record, dict) else {}
            missing = []
            if not version_valid:
                missing.append("version")
            if not (str(item.get("source_url", "")).strip() or str(item.get("source_id", "")).strip()):
                missing.append("source_url_or_source_id")
            missing.extend(_freshness_invalid_fields(item.get("observed_at"), item.get("valid_until")))
            if not str(item.get("evidence_type", "")).strip():
                missing.append("evidence_type")
            if not str(item.get("claim", "")).strip():
                missing.append("claim")
            claim_kind = str(item.get("claim_kind", ""))
            if claim_kind not in BUSINESS_CLAIM_KINDS:
                missing.append("claim_kind")
            if not str(item.get("validation_owner", "")).strip() and not str(item.get("next_owner", "")).strip():
                missing.append("validation_owner_or_next_owner")
            status = str(item.get("status", "unknown"))
            if status not in BUSINESS_STATUSES:
                missing.append("status")
            if status in {"stale", "unverified"}:
                missing.append(status)
            if (status == "validated" and claim_kind not in {"observed", "derived"}) or (
                status == "hypothesis" and claim_kind != "hypothesis"
            ):
                missing.append("claim_kind_status")
            normalized_status = status if not missing and status in {"validated", "hypothesis"} else "unknown"
            owner = str(item.get("validation_owner") or item.get("next_owner") or "business-evidence-owner")
            next_action = str(item.get("next_action") or f"Validate {category} evidence with {owner}.")
            normalized.append({
                "source_url": item.get("source_url") or None,
                "source_id": item.get("source_id") or None,
                "observed_at": item.get("observed_at") or None,
                "valid_until": item.get("valid_until") or None,
                "evidence_type": item.get("evidence_type") or None,
                "claim": item.get("claim") or None,
                "claim_kind": claim_kind or None,
                "status": normalized_status,
                "reported_status": status,
                "confidence": item.get("confidence") or "unknown",
                "validation_owner": owner,
                "next_action": next_action,
                "limitations": item.get("limitations") or None,
                "invalid_fields": missing,
                "score_credit": False,
            })
        output[category] = normalized
    return output


def normalize_human_journey(value: Any, agent_journey: Any = None) -> dict[str, Any]:
    supplied = value if isinstance(value, dict) else {}
    human = {"mode": "primary", **supplied}
    required = ("journey", "journey_version", "role", "accountable_owner", "next_action", "observed_at", "evidence_reference")
    missing = [field for field in required if not human.get(field)]
    missing.extend(_freshness_invalid_fields(human.get("observed_at"), human.get("valid_until")))
    if human.get("activation_reached") is not True:
        missing.append("activation_reached")
    if not isinstance(human.get("pre_activation_frictions"), list):
        missing.append("pre_activation_frictions")
    if human.get("evidence_origin") != "human_observation":
        missing.append("human_evidence_origin")
    agent = agent_journey if isinstance(agent_journey, dict) else {}
    if human.get("evidence_reference") and human.get("evidence_reference") == agent.get("evidence_reference"):
        missing.append("separate_human_evidence")
    if human.get("evidence_hash") and human.get("evidence_hash") == agent.get("evidence_hash"):
        missing.append("separate_human_evidence")
    is_completed = human.get("status") == "pass" and not missing
    if not is_completed:
        human["reported_status"] = human.get("status", "not_run")
        human["status"] = "not_run"
        human["activation_reached"] = False
        human["validation_missing"] = sorted(set(missing))
        human["next_action"] = human.get("next_action") or "Have the accountable owner observe one representative human activation journey."
    return human


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
    human_journey = normalize_human_journey(evidence.get("human_journey"), agent_journey)
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
    business_evidence = normalize_business_evidence(evidence.get("business_evidence"))

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
        "business_evidence": business_evidence,
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

    lines += ["", "## Business evidence", ""]
    for category in BUSINESS_CATEGORIES:
        lines.append(f"### {category.capitalize()}")
        records = report["business_evidence"][category]
        if not records:
            lines.append("- Status: **not_run**; next action: collect a source-backed observation with a validation owner.")
        for record in records:
            source = record.get("source_url") or record.get("source_id")
            lines.append(f"- Status: **{_value(record.get('status'))}**; source: {_value(source)}; observed: {_value(record.get('observed_at'))}")
            lines.append(f"  - Claim: {_value(record.get('claim'))}; Claim kind: {_value(record.get('claim_kind'))}; confidence: {_value(record.get('confidence'))}; validation owner: {_value(record.get('validation_owner'))}")
            lines.append(f"  - Next action: {_value(record.get('next_action'))}; limitations: {_value(record.get('limitations'))}")

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

    lines += ["", "## Guide-by-guide coverage", "", "| URL | Sources | Owner | Redirects | Auth gate | Terminal status | Blocker or exclusion | Content hash |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in report["corpus"]["rows"]:
        lines.append(f"| {_value(row.get('url'))} | {_value(', '.join(row.get('sources', [])))} | {_value(row.get('owner'))} | {_value(' -> '.join(row.get('redirect_chain', [])))} | {_value(row.get('auth_gate'))} | {_value(row.get('status'))} | {_value(row.get('blocker') or row.get('exclusion_reason') or row.get('reason'))} | {_value(row.get('content_hash'))} |")

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
