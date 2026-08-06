#!/usr/bin/env python3
"""Validate imported, sanitized browser evidence for a bounded clean-room run.

This module deliberately does not execute shell commands, start a browser, or
contact Apostl. It validates a trace produced by a browser agent and makes a
missing browser observation non-passing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from safety import SensitiveOutputError, sanitize_data  # noqa: E402


TRACE_VERSION = "agent-native-clean-room-trace.v1"
W3SCHOOLS_URL = "https://www.w3schools.com/html/html_intro.asp"
EXPECTED_OBSERVATION = {"h1": "This is a heading", "paragraph": "This is a paragraph."}


class _IntroParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._tag: str | None = None
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "p"} and tag not in self.values:
            self._tag = tag

    def handle_data(self, data: str) -> None:
        if self._tag:
            key = "h1" if self._tag == "h1" else "paragraph"
            self.values[key] = (self.values.get(key, "") + data).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == self._tag:
            self._tag = None


def _text_observation(path: Path) -> dict[str, str]:
    parser = _IntroParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.values


def _safe_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or "?" in value or ":" in value:
        return False
    return value.endswith((".json", ".png"))


def _safe_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


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


def _is_loopback_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"} and bool(parsed.path)


def _validated_artifact(root: Path, reference: str, expected_hash: str) -> bool:
    candidate = (root / reference).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return False
    return candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_hash


def _result(status: str, blocker: str | None = None, **values: Any) -> dict[str, Any]:
    return {"status": status, "blocker": blocker, **values}


def validate_cleanroom_trace(value: Any, artifact_root: Path | None = None) -> dict[str, Any]:
    trace = sanitize_data(value, reject_keys=True)
    if not isinstance(trace, dict):
        return _result("not_run", "Clean-room trace is missing or malformed.")
    required = ("trace_version", "source_url", "local_url", "selected_journey", "activation_event", "environment_identity", "steps", "started_at", "terminal_at", "terminal_status")
    missing = [field for field in required if not trace.get(field)]
    environment = trace.get("environment_identity")
    if not isinstance(environment, dict) or not all(environment.get(field) for field in ("working_directory_id", "profile_id", "environment_id")) or environment.get("fresh_working_directory") is not True:
        missing.append("fresh_environment_identity")
    steps = trace.get("steps")
    if not isinstance(steps, list) or not steps or any(not isinstance(step, dict) or not all(step.get(field) for field in ("ordinal", "action", "timestamp", "deviation")) for step in steps):
        missing.append("ordered_steps")
    elif [step["ordinal"] for step in steps] != list(range(1, len(steps) + 1)):
        missing.append("ordered_steps")
    started_at = _parse_rfc3339_utc(trace.get("started_at"))
    terminal_at = _parse_rfc3339_utc(trace.get("terminal_at"))
    step_times = [_parse_rfc3339_utc(step.get("timestamp")) for step in steps] if isinstance(steps, list) else []
    if not started_at or not terminal_at or not all(step_times) or started_at > terminal_at or any(timestamp < started_at or timestamp > terminal_at for timestamp in step_times if timestamp):
        missing.append("timestamps")
    if trace.get("trace_version") != TRACE_VERSION:
        missing.append("trace_version")
    if trace.get("source_url") != W3SCHOOLS_URL:
        missing.append("source_url")
    if not _is_loopback_url(trace.get("local_url")):
        missing.append("local_url")
    commands = trace.get("browser_commands")
    if not isinstance(commands, list) or not all(isinstance(command, str) for command in commands) or not any(command.startswith("agent-browser open") for command in commands) or not any(command.startswith("agent-browser snapshot") for command in commands):
        missing.append("agent_browser_commands")
    observation = trace.get("activation_observation")
    browser_proof = trace.get("browser_proof")
    if not isinstance(observation, dict) or not all(observation.get(key) for key in EXPECTED_OBSERVATION):
        return _result("not_run", "Clean-room trace has no declared browser activation observation.", missing=sorted(set(missing)))
    if observation != EXPECTED_OBSERVATION:
        missing.append("declared_activation_observation")
    if not isinstance(browser_proof, dict) or not _safe_reference(browser_proof.get("snapshot_ref")) or not _safe_hash(browser_proof.get("snapshot_sha256")):
        return _result("not_run", "Clean-room trace has no sanitized browser proof references.", missing=sorted(set(missing)))
    if bool(browser_proof.get("screenshot_ref")) != bool(browser_proof.get("screenshot_sha256")):
        missing.append("screenshot_proof")
    if browser_proof.get("screenshot_ref") and (not _safe_reference(browser_proof.get("screenshot_ref")) or not _safe_hash(browser_proof.get("screenshot_sha256"))):
        missing.append("screenshot_proof")
    if artifact_root is None:
        missing.append("artifact_root")
    elif not _validated_artifact(artifact_root, browser_proof["snapshot_ref"], browser_proof["snapshot_sha256"]):
        missing.append("snapshot_artifact_hash")
    elif browser_proof.get("screenshot_ref") and not _validated_artifact(artifact_root, browser_proof["screenshot_ref"], browser_proof["screenshot_sha256"]):
        missing.append("screenshot_artifact_hash")
    if "snapshot_artifact_hash" in missing or "screenshot_artifact_hash" in missing:
        return _result("not_run", "Sanitized browser-proof artifact is missing or its hash does not match.", missing=sorted(set(missing)))
    if missing:
        return _result("not_run", "Clean-room trace is incomplete.", missing=sorted(set(missing)))
    if trace.get("terminal_status") != "pass":
        return _result("blocked", "Clean-room trace did not reach a passing terminal status.")
    return _result("pass", activation_observation={key: observation[key] for key in EXPECTED_OBSERVATION}, browser_proof=browser_proof, trace=trace)


def validate_w3schools_fixture_bundle(directory: Path) -> dict[str, Any]:
    required = ("source-fixture.html", "index.html", "sha256-inventory.json", "clean-room-trace.pass.json", "browser-snapshot.json")
    missing = [name for name in required if not (directory / name).is_file()]
    if missing:
        return _result("blocked", "W3Schools fixture bundle is incomplete.", missing=missing)
    source = directory / "source-fixture.html"
    index = directory / "index.html"
    inventory = json.loads((directory / "sha256-inventory.json").read_text(encoding="utf-8"))
    for path in (source, index):
        expected_hash = inventory.get(path.name)
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected_hash != actual_hash:
            label = "Pinned source fixture" if path == source else "Pinned local index"
            return _result("blocked", f"{label} hash mismatch.")
    source_observation = _text_observation(source)
    local_observation = _text_observation(index)
    if source_observation != EXPECTED_OBSERVATION:
        return _result("blocked", "Pinned source fixture does not contain the declared activation values.")
    if local_observation != source_observation:
        return _result("blocked", "Pinned local index does not faithfully reproduce the source fixture.")
    trace = json.loads((directory / "clean-room-trace.pass.json").read_text(encoding="utf-8"))
    result = validate_cleanroom_trace(trace, artifact_root=directory)
    if result["status"] != "pass":
        return _result("blocked", result["blocker"], missing=result.get("missing", []))
    if trace.get("source_url") != W3SCHOOLS_URL:
        return _result("blocked", "Clean-room trace did not select the pinned W3Schools source URL.")
    if result["activation_observation"] != source_observation:
        return _result("blocked", "Trace activation observation does not match the pinned source fixture.")
    snapshot = json.loads((directory / "browser-snapshot.json").read_text(encoding="utf-8"))
    if snapshot.get("activation_observation") != source_observation:
        return _result("blocked", "Rendered browser DOM observation does not match the pinned local index.")
    return _result("pass", activation_observation=source_observation, browser_proof=result["browser_proof"], source_sha256=inventory["source-fixture.html"], local_index_sha256=inventory["index.html"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--w3schools-fixture-dir", type=Path)
    args = parser.parse_args(argv)
    if bool(args.trace) == bool(args.w3schools_fixture_dir):
        parser.error("supply exactly one of --trace or --w3schools-fixture-dir")
    result = (
        validate_w3schools_fixture_bundle(args.w3schools_fixture_dir)
        if args.w3schools_fixture_dir
        else validate_cleanroom_trace(
            json.loads(args.trace.read_text(encoding="utf-8")),
            artifact_root=args.artifact_root or args.trace.parent,
        )
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
