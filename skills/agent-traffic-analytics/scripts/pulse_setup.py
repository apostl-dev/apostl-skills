#!/usr/bin/env python3
"""Create and verify an unclaimed Apostl Pulse setup without logging secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urljoin, urlsplit


DEFAULT_PLATFORM_URL = "https://platform.apostl.dev"
USER_AGENT = "Apostl-Agent-Traffic-Analytics-Skill/1.0"


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Create an unclaimed seven-day Pulse setup")
    start.add_argument("--origin", required=True)
    start.add_argument("--project-name", required=True)
    start.add_argument("--verification-path", default="/")
    start.add_argument("--environment", choices=("production", "staging", "development"), default="production")
    start.add_argument("--agent-name")
    start.add_argument("--platform-url", default=os.environ.get("APOSTL_PLATFORM_URL", DEFAULT_PLATFORM_URL))
    start.add_argument("--credentials", type=Path)

    verify = subparsers.add_parser("verify", help="Verify the signed public response and resulting real event")
    verify.add_argument("--credentials", type=Path, required=True)

    show = subparsers.add_parser("show", help="Show redacted setup metadata")
    show.add_argument("--credentials", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_setup(args)
        elif args.command == "verify":
            result = verify_setup(args.credentials)
        else:
            result = show_setup(args.credentials)
    except ApiError as error:
        print_json({"error": {"status": error.status, "code": error.code, "message": error.message}}, stderr)
        return 1
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print_json({"error": {"code": "local_setup_error", "message": str(error)}}, stderr)
        return 1

    print_json(result, stdout)
    return 0


def start_setup(args: argparse.Namespace) -> dict[str, Any]:
    origin = canonical_origin(args.origin)
    platform_url = validated_platform_url(args.platform_url)
    credentials_path = (args.credentials or default_credentials_path(origin)).expanduser().resolve()
    if credentials_path.exists():
        raise RuntimeError(f"Credentials already exist at {credentials_path}. Resume or remove them explicitly.")

    payload: dict[str, Any] = {
        "origin": origin,
        "verification_path": canonical_path(args.verification_path),
        "project_name": required_text(args.project_name, "project name", 120),
        "environment": args.environment,
    }
    if args.agent_name:
        payload["agent_name"] = required_text(args.agent_name, "agent name", 120)

    response = api_request(urljoin(platform_url + "/", "api/v1/pulse/setups"), payload)
    data = require_object(response, "data")
    credentials = require_object(data, "credentials")
    record = {
        "schema_version": 1,
        "origin": required_string(data, "origin"),
        "verification_url": required_string(data, "verification_url"),
        "expires_at": required_string(data, "expires_at"),
        "setup_id": required_string(data, "setup_id"),
        "verify_url": required_string(data, "verify_url"),
        "setup_token": required_string(data, "setup_token"),
        "api_key": required_string(credentials, "api_key"),
        "ingest_endpoint": required_string(credentials, "endpoint"),
    }
    if not record["api_key"].startswith("pulse_api_") or not record["setup_token"].startswith("pulse_setup_"):
        raise RuntimeError("Apostl returned an unexpected credential format.")
    write_credentials(credentials_path, record)

    return {
        "status": str(data.get("status", "pending_deployment")),
        "origin": record["origin"],
        "verification_url": record["verification_url"],
        "expires_at": record["expires_at"],
        "credentials_file": str(credentials_path),
        "next": "Install the server SDK with the stored API key, deploy it, then run verify.",
    }


def verify_setup(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    response = api_request(
        required_string(record, "verify_url"),
        {},
        bearer_token=required_string(record, "setup_token"),
    )
    data = require_object(response, "data")
    result: dict[str, Any] = {
        "status": required_string(data, "status"),
        "origin": required_string(record, "origin"),
        "verification_url": required_string(record, "verification_url"),
    }
    if result["status"] == "verified":
        result["claim_url"] = required_string(data, "claim_url")
        result["next"] = "Give the one-time claim URL to the owner. The API key remains active after claim."
    else:
        result["next"] = "Wait for the verifier request to reach Pulse as a real event, then run verify again."
    return result


def show_setup(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    return {
        "origin": required_string(record, "origin"),
        "verification_url": required_string(record, "verification_url"),
        "expires_at": required_string(record, "expires_at"),
        "credentials_file": str(credentials_path.expanduser().resolve()),
        "api_key": "configured",
        "setup_token": "configured",
    }


def api_request(url: str, payload: dict[str, Any], *, bearer_token: str | None = None) -> dict[str, Any]:
    validated_api_url(url)
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"accept": "application/json", "content-type": "application/json", "user-agent": USER_AGENT}
    if bearer_token:
        headers["authorization"] = f"Bearer {bearer_token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            return decode_response(response.read())
    except urllib.error.HTTPError as error:
        payload = decode_response(error.read(), allow_empty=True)
        details = payload.get("error") if isinstance(payload, dict) else None
        code = str(details.get("code", "http_error")) if isinstance(details, dict) else "http_error"
        message = str(details.get("message", f"Apostl returned HTTP {error.code}.")) if isinstance(details, dict) else f"Apostl returned HTTP {error.code}."
        raise ApiError(error.code, code, message) from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"Apostl request failed: {error.reason}") from None


def decode_response(body: bytes, *, allow_empty: bool = False) -> dict[str, Any]:
    if allow_empty and not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Apostl returned an invalid JSON response.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("Apostl returned an unexpected response shape.")
    return payload


def write_credentials(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    handle, temporary = tempfile.mkstemp(prefix=".pulse-", dir=path.parent, text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_credentials(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    mode = stat_mode(resolved)
    if mode & 0o077:
        raise RuntimeError(f"Credentials file must be owner-only (0600): {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Credentials file is not valid JSON: {resolved}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported credentials file: {resolved}")
    return payload


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


def default_credentials_path(origin: str) -> Path:
    digest = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "apostl" / "pulse" / f"{digest}.json"


def canonical_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Origin must be a public HTTPS origin without credentials, query, or fragment.")
    if parsed.path not in ("", "/") or parsed.port not in (None, 443):
        raise ValueError("Origin must not include a path or custom port.")
    return f"https://{parsed.hostname.lower()}"


def canonical_path(value: str) -> str:
    path = value.strip() or "/"
    if not path.startswith("/") or "?" in path or "#" in path:
        raise ValueError("Verification path must start with / and contain no query or fragment.")
    return "/" if path == "/" else path.rstrip("/")


def validated_platform_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    loopback_http = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "::1")
    if (parsed.scheme != "https" and not loopback_http) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Platform URL must be HTTPS (HTTP loopback is allowed only for tests).")
    return value.rstrip("/")


def validated_api_url(value: str) -> None:
    validated_platform_url(value)


def required_text(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label.capitalize()} must be between 1 and {maximum} characters.")
    return normalized


def require_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(f"Apostl response is missing {key}.")
    return value


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Apostl response is missing {key}.")
    return value


def print_json(payload: dict[str, Any], stream: TextIO) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
