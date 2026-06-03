#!/usr/bin/env python3
"""Capture repeatable SDK onboarding audit evidence.

The script is intentionally small and generic: it snapshots source URLs,
records host tool versions, executes reviewed commands in .tmp/<run_id>, and
writes machine-readable artifacts plus a report scaffold.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


MAX_CAPTURE_CHARS = 4000
DEFAULT_CTA_MESSAGE = "Want this checked continuously on every SDK/docs release?"
DEFAULT_CTA_URL = "https://forms.fillout.com/t/pZjfKK1ELmus"


def find_repo_root(start: Path) -> Path:
    for path in [start, *start.parents]:
        if (path / ".git").exists():
            return path
        if (path / "package.json").exists() and (path / "skills").exists():
            return path
        if (path / "AGENTS.md").exists() and (path / "skills").exists():
            return path
    return Path.cwd()


ROOT = find_repo_root(Path(__file__).resolve().parent)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slugify(value: str, fallback: str = "source") -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:100] or fallback


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"config must be a JSON object: {path}")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(data, handle, sort_keys=True)
        handle.write("\n")


def run_capture(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": cmd,
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip()[:MAX_CAPTURE_CHARS],
            "stderr": proc.stderr.strip()[:MAX_CAPTURE_CHARS],
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except FileNotFoundError as exc:
        return {
            "cmd": cmd,
            "exit_code": 127,
            "stdout": "",
            "stderr": str(exc),
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "timed out",
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def host_environment() -> dict[str, Any]:
    version_cmds = [
        ["node", "--version"],
        ["npm", "--version"],
        ["bun", "--version"],
        ["pnpm", "--version"],
        ["yarn", "--version"],
        ["python3", "--version"],
        ["git", "--version"],
        ["ffmpeg", "-version"],
    ]
    return {
        "captured_at": utc_now(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "tools": {cmd[0]: run_capture(cmd) for cmd in version_cmds},
    }


def fetch_url(url: str, output_dir: Path, index: int) -> dict[str, Any]:
    safe_name = f"{index:02d}-{slugify(url)}.txt"
    out_path = output_dir / safe_name
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "apostl-sdk-onboarding-audit/1.0"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(5_000_000)
            status = getattr(response, "status", None)
            content_type = response.headers.get("content-type", "")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(body)
        return {
            "url": url,
            "status": status,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "path": str(out_path.relative_to(ROOT)),
            "duration_seconds": round(time.monotonic() - started, 3),
            "ok": True,
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "url": url,
            "error": str(exc),
            "duration_seconds": round(time.monotonic() - started, 3),
            "ok": False,
        }


def expand_value(value: str, run_dir: Path, command_cwd: Path) -> str:
    return (
        value.replace("{run_dir}", str(run_dir))
        .replace("{cwd}", str(command_cwd))
        .replace("{home}", str(run_dir / "home"))
    )


def command_env(base: dict[str, str], overrides: dict[str, str], run_dir: Path, cwd: Path) -> dict[str, str]:
    env = dict(base)
    for key, value in overrides.items():
        env[key] = expand_value(str(value), run_dir, cwd)
    return env


def execute_command(command: dict[str, Any], run_dir: Path, index: int) -> dict[str, Any]:
    cmd = command.get("cmd")
    if not isinstance(cmd, list) or not all(isinstance(part, str) for part in cmd):
        raise ValueError(f"commands[{index}].cmd must be a list of strings")

    command_id = str(command.get("id") or f"command-{index:02d}")
    relative_cwd = str(command.get("cwd") or ".")
    cwd = (run_dir / relative_cwd).resolve()
    if not str(cwd).startswith(str(run_dir.resolve())):
        raise ValueError(f"commands[{index}].cwd must stay inside run_dir: {relative_cwd}")
    cwd.mkdir(parents=True, exist_ok=True)

    stdout_path = run_dir / "logs" / f"{index:02d}-{slugify(command_id)}.stdout.txt"
    stderr_path = run_dir / "logs" / f"{index:02d}-{slugify(command_id)}.stderr.txt"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)

    env_overrides = command.get("env") or {}
    if not isinstance(env_overrides, dict):
        raise ValueError(f"commands[{index}].env must be an object")
    env = command_env(os.environ, env_overrides, run_dir, cwd)

    timeout = int(command.get("timeout_seconds") or 300)
    expected_exit = int(command.get("expected_exit", 0))
    started_at = utc_now()
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or "timed out"
        timed_out = True

    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")

    return {
        "id": command_id,
        "cmd": cmd,
        "cwd": str(cwd),
        "started_at": started_at,
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": exit_code,
        "expected_exit": expected_exit,
        "passed": exit_code == expected_exit,
        "timed_out": timed_out,
        "stdout_path": str(stdout_path.relative_to(ROOT)),
        "stderr_path": str(stderr_path.relative_to(ROOT)),
        "env_overrides": sorted(env_overrides.keys()),
        "notes": command.get("notes", ""),
    }


def source_urls(config: dict[str, Any]) -> list[str]:
    target = config.get("target") or {}
    urls: list[str] = []
    for key in ("launch_url", "repo_url", "package_url", "api_spec_url"):
        value = target.get(key)
        if isinstance(value, str) and value:
            urls.append(value)
    docs = target.get("docs_urls") or []
    if isinstance(docs, list):
        urls.extend(url for url in docs if isinstance(url, str) and url)
    extra = config.get("source_urls") or []
    if isinstance(extra, list):
        urls.extend(url for url in extra if isinstance(url, str) and url)
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def write_report(run_dir: Path, config: dict[str, Any], results: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    target = config.get("target") or {}
    cta = config.get("cta") or {}
    name = target.get("name") or run_dir.name
    failed = [result for result in results if not result.get("passed")]
    passed = [result for result in results if result.get("passed")]
    lines = [
        f"# SDK Onboarding Audit: {name}",
        "",
        "## Verdict",
        "TODO: summarize whether a fresh developer can complete the promised quickstart.",
        "",
        "## Target",
        f"- Name: {name}",
    ]
    for key in ("launch_url", "repo_url", "package", "api_spec_url"):
        if target.get(key):
            lines.append(f"- {key}: {target[key]}")
    lines.extend(
        [
            "",
            "## Source Snapshots",
        ]
    )
    for source in sources:
        status = source.get("status", source.get("error", "unknown"))
        path = source.get("path", "")
        lines.append(f"- {source.get('url')}: {status} {path}".rstrip())
    lines.extend(
        [
            "",
            "## Command Summary",
            f"- Passed: {len(passed)}",
            f"- Failed: {len(failed)}",
            "",
            "## Findings",
            "TODO: add severity-ranked findings with exact command, observed result, expected result, and fix.",
            "",
            "## Commands",
        ]
    )
    for result in results:
        status = "PASS" if result.get("passed") else "FAIL"
        cmd = " ".join(result.get("cmd") or [])
        lines.append(
            f"- {status} `{cmd}` exit={result.get('exit_code')} stdout={result.get('stdout_path')} stderr={result.get('stderr_path')}"
        )
    lines.extend(
        [
            "",
            "## Outreach Proof Snippet",
            "TODO: one concise proof-led snippet for founder/DevRel outreach.",
            "",
            "## PDF Notes",
            "TODO: if the user wants a shareable artifact, render this report to PDF after findings are finalized.",
            "",
        ]
    )
    if cta.get("enabled", True):
        message = cta.get("message") or DEFAULT_CTA_MESSAGE
        url = cta.get("url", DEFAULT_CTA_URL)
        lines.extend(["## Full Version CTA", ""])
        if url:
            lines.append(f"{message} {url}")
        else:
            lines.append(f"TODO: {message} Add the full launch-assurance loop URL before publishing.")
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Stable run identifier under .tmp/")
    parser.add_argument("--config", required=True, help="JSON audit config")
    parser.add_argument("--run-dir", help="Override output directory; defaults to .tmp/<run-id>")
    parser.add_argument("--execute", action="store_true", help="Execute commands from config")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = read_json(config_path)
    run_dir = Path(args.run_dir).resolve() if args.run_dir else ROOT / ".tmp" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": args.run_id,
        "created_at": utc_now(),
        "config_path": str(config_path),
        "run_dir": str(run_dir),
        "target": config.get("target") or {},
        "execute": args.execute,
        "environment": host_environment(),
        "commands": config.get("commands") or [],
    }
    write_json(run_dir / "audit_manifest.json", manifest)

    sources = [
        fetch_url(url, run_dir / "sources", index)
        for index, url in enumerate(source_urls(config), start=1)
    ]
    write_json(run_dir / "source_snapshots.json", sources)

    results: list[dict[str, Any]] = []
    if args.execute:
        commands = config.get("commands") or []
        if not isinstance(commands, list):
            raise ValueError("commands must be a list")
        results_path = run_dir / "command_results.jsonl"
        if results_path.exists():
            results_path.unlink()
        for index, command in enumerate(commands, start=1):
            if not isinstance(command, dict):
                raise ValueError(f"commands[{index}] must be an object")
            result = execute_command(command, run_dir, index)
            results.append(result)
            append_jsonl(results_path, result)

    write_report(run_dir, config, results, sources)
    print(json.dumps({"run_dir": str(run_dir), "commands": len(results), "sources": len(sources)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
