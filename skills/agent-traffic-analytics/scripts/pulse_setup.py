#!/usr/bin/env python3
"""Register through Auth.md, create and verify Pulse, then hand off one claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urljoin, urlsplit


DEFAULT_PLATFORM_URL = "https://platform.apostl.dev"
AUTH_MD_VERSION = "0.6"
SKILL_VERSION = "1.2.0"
USER_AGENT = f"Apostl-Agent-Traffic-Analytics-Skill/{SKILL_VERSION}"


class ApiError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        resolution: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.resolution = resolution
        self.retry_after = retry_after


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Register with Auth.md and create an unclaimed Pulse setup")
    start.add_argument("--origin", required=True)
    start.add_argument("--project-name", required=True)
    start.add_argument("--verification-path", default="/")
    start.add_argument("--environment", choices=("production", "staging", "development"), default="production")
    start.add_argument("--agent-name")
    start.add_argument("--device-name")
    start.add_argument("--platform-url", default=os.environ.get("APOSTL_PLATFORM_URL", DEFAULT_PLATFORM_URL))
    start.add_argument("--credentials", type=Path)

    verify = subparsers.add_parser("verify", help="Verify the signed public response and resulting real event")
    verify.add_argument("--credentials", type=Path, required=True)

    claim = subparsers.add_parser("claim", help="Start the one-time human claim ceremony after setup")
    claim.add_argument("--credentials", type=Path, required=True)
    claim.add_argument("--email", required=True)

    claim_status = subparsers.add_parser("claim-status", help="Poll Auth.md claim without exposing credentials")
    claim_status.add_argument("--credentials", type=Path, required=True)

    revoke = subparsers.add_parser("revoke", help="Revoke the current Auth.md access token")
    revoke.add_argument("--credentials", type=Path, required=True)

    show = subparsers.add_parser("show", help="Show redacted Auth.md and Pulse setup metadata")
    show.add_argument("--credentials", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO = sys.stdout, stderr: TextIO = sys.stderr) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "start":
            result = start_setup(args)
        elif args.command == "verify":
            result = verify_setup(args.credentials)
        elif args.command == "claim":
            result = start_claim(args.credentials, args.email)
        elif args.command == "claim-status":
            result = poll_claim(args.credentials)
        elif args.command == "revoke":
            result = revoke_token(args.credentials)
        else:
            result = show_setup(args.credentials)
    except ApiError as error:
        details: dict[str, Any] = {"status": error.status, "code": error.code, "message": error.message}
        if error.resolution:
            details["resolution"] = error.resolution
        if error.retry_after is not None:
            details["retry_after"] = error.retry_after
        print_json({"error": details}, stderr)
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

    discovery = discover_auth_md(platform_url)
    identity_endpoint = required_same_origin_url(discovery["authorization"], "identity_endpoint", platform_url)
    token_endpoint = required_same_origin_url(discovery["authorization"], "token_endpoint", platform_url)
    resource = required_string(discovery["resource"], "resource")
    identity_payload: dict[str, Any] = {
        "type": "anonymous",
        "skill_name": "agent-traffic-analytics",
        "skill_version": SKILL_VERSION,
    }
    if args.agent_name:
        identity_payload["agent_name"] = required_text(args.agent_name, "agent name", 255)
    if args.device_name:
        identity_payload["device_name"] = required_text(args.device_name, "device name", 255)
    identity = request_json(identity_endpoint, identity_payload)
    assertion = required_string(identity, "identity_assertion")
    claim_token = required_string(identity, "claim_token")
    token = request_form(token_endpoint, {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
        "resource": resource,
    })
    if required_string(token, "scope") != "pulse:setup":
        raise RuntimeError("Apostl returned a pre-claim token with an unexpected scope.")
    pre_claim_access_token = required_string(token, "access_token")
    auth_record = {
        "version": AUTH_MD_VERSION,
        "skill_url": discovery["skill_url"],
        "resource": resource,
        "identity_endpoint": identity_endpoint,
        "claim_endpoint": required_same_origin_url(discovery["authorization"], "claim_endpoint", platform_url),
        "token_endpoint": token_endpoint,
        "revocation_endpoint": required_same_origin_url(discovery["authorization"], "revocation_endpoint", platform_url),
        "registration_id": required_string(identity, "registration_id"),
        "claim_token": claim_token,
        "claim_token_expires": required_string(identity, "claim_token_expires"),
        "identity_assertion": assertion,
        "assertion_expires": required_string(identity, "assertion_expires"),
        "pre_claim_access_token": pre_claim_access_token,
        "pre_claim_access_token_expires": expires_after(token),
        "claim": None,
        "post_claim_access_token": None,
        "post_claim_access_token_expires": None,
        "post_claim_identity_assertion": None,
        "post_claim_assertion_expires": None,
    }

    pulse_payload: dict[str, Any] = {
        "origin": origin,
        "verification_path": canonical_path(args.verification_path),
        "project_name": required_text(args.project_name, "project name", 120),
        "environment": args.environment,
    }
    if args.agent_name:
        pulse_payload["agent_name"] = required_text(args.agent_name, "agent name", 120)
    try:
        response = request_json(
            urljoin(platform_url + "/", "api/v1/pulse/setups"),
            pulse_payload,
            bearer_token=pre_claim_access_token,
        )
    except ApiError as error:
        write_credentials(credentials_path, {
            "schema_version": 2,
            "platform_url": platform_url,
            "auth_md": auth_record,
            "pulse": {
                "origin": origin,
                "verification_status": "not_created",
            },
        })
        preserved = f"Auth.md credentials were preserved at {credentials_path}; run revoke before deleting or restarting."
        error.resolution = f"{error.resolution} {preserved}" if error.resolution else preserved
        raise
    data = require_object(response, "data")
    pulse_credentials = require_object(data, "credentials")
    record = {
        "schema_version": 2,
        "platform_url": platform_url,
        "auth_md": auth_record,
        "pulse": {
            "origin": required_string(data, "origin"),
            "verification_url": required_string(data, "verification_url"),
            "expires_at": required_string(data, "expires_at"),
            "setup_id": required_string(data, "setup_id"),
            "verify_url": required_string(data, "verify_url"),
            "setup_token": required_string(data, "setup_token"),
            "api_key": required_string(pulse_credentials, "api_key"),
            "ingest_endpoint": required_string(pulse_credentials, "endpoint"),
            "verification_status": str(data.get("status", "pending_deployment")),
        },
    }
    if not record["pulse"]["api_key"].startswith("pulse_api_") or not record["pulse"]["setup_token"].startswith("pulse_setup_"):
        raise RuntimeError("Apostl returned an unexpected Pulse credential format.")
    write_credentials(credentials_path, record)

    return {
        "status": record["pulse"]["verification_status"],
        "auth_md": "registered_anonymous",
        "registration_id": record["auth_md"]["registration_id"],
        "scope": "pulse:setup",
        "origin": record["pulse"]["origin"],
        "verification_url": record["pulse"]["verification_url"],
        "expires_at": record["pulse"]["expires_at"],
        "credentials_file": str(credentials_path),
        "next": "Install the server SDK with the stored API key, deploy it, then run verify.",
    }


def discover_auth_md(platform_url: str) -> dict[str, Any]:
    protected = request_json(urljoin(platform_url + "/", ".well-known/oauth-protected-resource"))
    authorization_servers = protected.get("authorization_servers")
    if not isinstance(authorization_servers, list) or platform_url not in authorization_servers:
        raise RuntimeError("Protected Resource Metadata does not advertise the selected platform issuer.")
    if "header" not in protected.get("bearer_methods_supported", []):
        raise RuntimeError("Protected Resource Metadata does not advertise Bearer header credentials.")
    authorization = request_json(urljoin(platform_url + "/", ".well-known/oauth-authorization-server"))
    if required_string(authorization, "issuer") != platform_url:
        raise RuntimeError("Authorization Server issuer does not match the selected platform.")
    agent_auth = require_object(authorization, "agent_auth")
    methods = agent_auth.get("identity_types_supported")
    if not isinstance(methods, list) or "anonymous" not in methods:
        raise RuntimeError("Authorization Server metadata does not advertise anonymous Auth.md registration.")
    skill_url = required_string(agent_auth, "skill")
    if not urlsplit(skill_url).path.endswith("/auth.md"):
        raise RuntimeError("Authorization Server metadata does not point to an auth.md file.")
    skill = request_text(skill_url)
    if not re.search(r"^#\s+.*auth\.md", skill, flags=re.IGNORECASE | re.MULTILINE):
        raise RuntimeError("The advertised Auth.md file has no Auth.md H1 heading.")
    return {
        "resource": protected,
        "authorization": {**authorization, **agent_auth},
        "skill_url": skill_url,
    }


def verify_setup(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    pulse = require_object(record, "pulse")
    response = request_json(
        required_string(pulse, "verify_url"),
        {},
        bearer_token=required_string(pulse, "setup_token"),
    )
    data = require_object(response, "data")
    status = required_string(data, "status")
    pulse["verification_status"] = status
    write_credentials(credentials_path.expanduser().resolve(), record)
    result: dict[str, Any] = {
        "status": status,
        "origin": required_string(pulse, "origin"),
        "verification_url": required_string(pulse, "verification_url"),
        "credentials_file": str(credentials_path.expanduser().resolve()),
    }
    if status in ("verified", "claimed"):
        result["next"] = (
            "Ask for the owner's Apostl email, run claim, show the returned code and verification URI, then poll claim-status."
            if status == "verified"
            else "The linked Auth.md registration and Pulse project are already claimed."
        )
    else:
        result["next"] = "Wait for the verifier request to reach Pulse as a real event, then run verify again."
    return result


def start_claim(credentials_path: Path, email: str) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    auth = require_object(record, "auth_md")
    pulse = require_object(record, "pulse")
    if pulse.get("verification_status") not in ("verified", "claimed"):
        raise RuntimeError("Verify the signed public response and real Pulse event before starting claim.")
    existing = auth.get("claim")
    if (isinstance(existing, dict)
            and existing.get("status") == "initiated"
            and timestamp_is_future(existing.get("expires_at"))):
        return claim_handoff(existing, credentials_path)
    response = request_json(required_string(auth, "claim_endpoint"), {
        "claim_token": required_string(auth, "claim_token"),
        "email": normalized_email(email),
    })
    attempt = require_object(response, "claim_attempt")
    claim = {
        "status": "initiated",
        "email": normalized_email(email),
        "user_code": required_string(attempt, "user_code"),
        "verification_uri": required_string(attempt, "verification_uri"),
        "expires_at": required_string(response, "expires_at"),
        "interval": required_positive_int(attempt, "interval"),
    }
    auth["claim"] = claim
    write_credentials(credentials_path.expanduser().resolve(), record)
    return claim_handoff(claim, credentials_path)


def claim_handoff(claim: dict[str, Any], credentials_path: Path) -> dict[str, Any]:
    return {
        "status": "authorization_pending",
        "email": required_string(claim, "email"),
        "user_code": required_string(claim, "user_code"),
        "verification_uri": required_string(claim, "verification_uri"),
        "expires_at": required_string(claim, "expires_at"),
        "interval": required_positive_int(claim, "interval"),
        "credentials_file": str(credentials_path.expanduser().resolve()),
        "next": "The owner opens verification_uri, signs in with the same verified email, and enters user_code there. Then run claim-status after interval seconds.",
    }


def poll_claim(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    auth = require_object(record, "auth_md")
    if auth.get("post_claim_access_token"):
        return {
            "status": "claimed",
            "scope": "agent:read agent:deploy agent:keys agent:feedback pulse:setup",
            "credentials_file": str(credentials_path.expanduser().resolve()),
            "next": "Auth.md and the verified Pulse project are connected to the owner account.",
        }
    claim = auth.get("claim")
    if not isinstance(claim, dict):
        raise RuntimeError("Start claim before polling claim-status.")
    try:
        token = request_form(required_string(auth, "token_endpoint"), {
            "grant_type": "urn:workos:agent-auth:grant-type:claim",
            "claim_token": required_string(auth, "claim_token"),
        })
    except ApiError as error:
        if error.code == "expired_token":
            claim["status"] = "expired"
            write_credentials(credentials_path.expanduser().resolve(), record)
            return start_claim(credentials_path, required_string(claim, "email"))
        if error.code not in ("authorization_pending", "slow_down"):
            raise
        retry_after = error.retry_after or required_positive_int(claim, "interval")
        return {
            "status": error.code,
            "retry_after": retry_after,
            "credentials_file": str(credentials_path.expanduser().resolve()),
            "next": f"Wait at least {retry_after} seconds, then run claim-status again.",
        }
    auth["post_claim_access_token"] = required_string(token, "access_token")
    auth["post_claim_access_token_expires"] = expires_after(token)
    auth["post_claim_identity_assertion"] = required_string(token, "identity_assertion")
    auth["post_claim_assertion_expires"] = required_string(token, "assertion_expires")
    auth["pre_claim_access_token"] = None
    auth["pre_claim_access_token_expires"] = None
    claim["status"] = "claimed"
    write_credentials(credentials_path.expanduser().resolve(), record)
    return {
        "status": "claimed",
        "scope": required_string(token, "scope"),
        "credentials_file": str(credentials_path.expanduser().resolve()),
        "next": "Auth.md and the verified Pulse project are connected to the owner account.",
    }


def revoke_token(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    auth = require_object(record, "auth_md")
    token = auth.get("post_claim_access_token") or auth.get("pre_claim_access_token")
    if not isinstance(token, str) or not token:
        return {"status": "already_revoked", "credentials_file": str(credentials_path.expanduser().resolve())}
    request_form(required_string(auth, "revocation_endpoint"), {
        "token": token,
        "token_type_hint": "access_token",
    }, allow_empty=True)
    if auth.get("post_claim_access_token") == token:
        auth["post_claim_access_token"] = None
        auth["post_claim_access_token_expires"] = None
    if auth.get("pre_claim_access_token") == token:
        auth["pre_claim_access_token"] = None
        auth["pre_claim_access_token_expires"] = None
    write_credentials(credentials_path.expanduser().resolve(), record)
    return {"status": "revoked", "credentials_file": str(credentials_path.expanduser().resolve())}


def show_setup(credentials_path: Path) -> dict[str, Any]:
    record = read_credentials(credentials_path)
    auth = require_object(record, "auth_md")
    pulse = require_object(record, "pulse")
    claim = auth.get("claim")
    pulse_summary = {
        "origin": required_string(pulse, "origin"),
        "verification_status": required_string(pulse, "verification_status"),
        "api_key": "configured" if pulse.get("api_key") else "not_configured",
        "setup_token": "configured" if pulse.get("setup_token") else "not_configured",
    }
    for key in ("verification_url", "expires_at"):
        value = pulse.get(key)
        if isinstance(value, str) and value:
            pulse_summary[key] = value

    return {
        "auth_md": {
            "version": required_string(auth, "version"),
            "registration_id": required_string(auth, "registration_id"),
            "claim_status": claim.get("status") if isinstance(claim, dict) else "not_started",
            "pre_claim_access_token": "configured" if auth.get("pre_claim_access_token") else "not_configured",
            "post_claim_access_token": "configured" if auth.get("post_claim_access_token") else "not_configured",
        },
        "pulse": pulse_summary,
        "credentials_file": str(credentials_path.expanduser().resolve()),
    }


def request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    bearer_token: str | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"accept": "application/json", "user-agent": USER_AGENT}
    if body is not None:
        headers["content-type"] = "application/json"
    return request(url, body, headers, "GET" if body is None else "POST", bearer_token=bearer_token)


def request_form(url: str, payload: dict[str, str], *, allow_empty: bool = False) -> dict[str, Any]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    return request(
        url,
        body,
        {"accept": "application/json", "content-type": "application/x-www-form-urlencoded", "user-agent": USER_AGENT},
        "POST",
        allow_empty=allow_empty,
    )


def request_text(url: str) -> str:
    validated_api_url(url)
    request_object = urllib.request.Request(url, headers={"accept": "text/markdown", "user-agent": USER_AGENT}, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request_object, timeout=15) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise ApiError(error.code, "auth_md_unavailable", f"Auth.md returned HTTP {error.code}.") from None
    except (UnicodeDecodeError, urllib.error.URLError) as error:
        raise RuntimeError(f"Auth.md request failed: {error}") from None


def request(
    url: str,
    body: bytes | None,
    headers: dict[str, str],
    method: str,
    *,
    bearer_token: str | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    validated_api_url(url)
    if bearer_token:
        headers["authorization"] = f"Bearer {bearer_token}"
    request_object = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request_object, timeout=15) as response:
            raw = response.read()
            return decode_response(raw, allow_empty=allow_empty)
    except urllib.error.HTTPError as error:
        payload = decode_response(error.read(), allow_empty=True)
        details = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(details, dict):
            code = str(details.get("code", "http_error"))
            message = str(details.get("message", f"Apostl returned HTTP {error.code}."))
            resolution = str(details.get("resolution")) if details.get("resolution") else None
        else:
            code = str(details or "http_error")
            message = str(payload.get("error_description", f"Apostl returned HTTP {error.code}."))
            resolution = None
        retry_header = error.headers.get("Retry-After")
        retry_after = int(retry_header) if retry_header and retry_header.isdigit() else None
        raise ApiError(error.code, code, message, resolution, retry_after) from None
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
    mode = os.stat(resolved, follow_symlinks=False).st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"Credentials file must be owner-only (0600): {resolved}")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Credentials file is not valid JSON: {resolved}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise RuntimeError(f"Unsupported credentials file: {resolved}")
    return payload


def expires_after(token: dict[str, Any]) -> str:
    seconds = token.get("expires_in")
    if not isinstance(seconds, int) or seconds <= 0:
        raise RuntimeError("Apostl token response has no valid expires_in.")
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def timestamp_is_future(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc)


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
    host = parsed.hostname.lower()
    if host in ("example", "invalid", "test", "example.com", "example.org", "example.net") or host.endswith((
        ".example", ".invalid", ".test", ".example.com", ".example.org", ".example.net",
    )):
        raise ValueError("Origin uses a reserved example domain. Replace it with a public HTTPS origin you can deploy to.")
    return f"https://{host}"


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


def required_same_origin_url(payload: dict[str, Any], key: str, platform_url: str) -> str:
    value = required_string(payload, key)
    endpoint = urlsplit(value)
    platform = urlsplit(platform_url)
    if (endpoint.scheme, endpoint.netloc) != (platform.scheme, platform.netloc):
        raise RuntimeError(f"Auth.md discovery returned a cross-origin {key}.")
    return value


def normalized_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 255:
        raise ValueError("Email must be a syntactically valid address.")
    return email


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


def required_positive_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"Apostl response is missing {key}.")
    return value


def print_json(payload: dict[str, Any], stream: TextIO) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
