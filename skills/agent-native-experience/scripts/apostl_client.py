#!/usr/bin/env python3
"""Minimal standard-library client for the Apostl Agent API v1."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
import sys


SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from safety import redact_text, sanitize_data  # noqa: E402


DEFAULT_BASE_URL = "https://platform.apostl.dev/api/v1"
DEFAULT_CREDENTIALS = Path.home() / ".config" / "apostl" / "credentials.json"
DEFAULT_PENDING_AUTHORIZATION = Path.home() / ".config" / "apostl" / "authorization.json"
DEFAULT_SCOPES = ("agent:read", "agent:deploy", "agent:keys", "agent:feedback")
SKILL_NAME = "agent-native-experience"
SKILL_VERSION = "1.1.4"
USER_AGENT = f"Apostl-Agent-Native-Experience/{SKILL_VERSION} (+https://platform.apostl.dev)"
IDEMPOTENCY_PATTERN = re.compile(r"\A[A-Za-z0-9._:-]{1,120}\Z")
MAX_AUTHORIZATION_INTERVAL_SECONDS = 60.0
FEEDBACK_TARGET_TYPES = {"project", "workflow", "run", "report", "recommendation"}
FEEDBACK_KINDS = {"accepted_fix", "rejected_fix", "correction", "free_form_note", "follow_up_request"}
FEEDBACK_FIELDS = {"target_type", "target_public_id", "kind", "message", "target_revision"}


class ConfirmationRequired(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    pass


class AuthorizationPending(AuthorizationError):
    pass


class AuthorizationDenied(AuthorizationError):
    pass


class AuthorizationExpired(AuthorizationError):
    pass


class AuthorizationConsumed(AuthorizationError):
    pass


class AuthorizationCancelled(AuthorizationError):
    pass


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, recovery: str, message: str,
                 *, retry_after: float | None = None):
        self.status = status
        self.code = code
        self.recovery = recovery
        self.retry_after = retry_after
        super().__init__(redact(f"HTTP {status} {code}: {message}. Recovery: {recovery}"))


def redact(value: str) -> str:
    return redact_text(value)


def _redact_request_values(value: str, payload: dict[str, Any] | None) -> str:
    redacted = value
    if isinstance(payload, dict):
        for key in ("device_code", "code", "api_key", "token", "password"):
            secret = payload.get(key)
            if isinstance(secret, str) and secret:
                redacted = redacted.replace(secret, "[REDACTED]")
    return redact(redacted)


def _save_private_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_credentials(path: Path, api_key: str, api_base: str) -> None:
    _save_private_json(path, {"api_key": api_key, "api_base": api_base})


def save_pending_authorization(path: Path, payload: dict[str, Any]) -> None:
    _save_private_json(path, payload)


def reserve_pending_authorization(path: Path) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise AuthorizationPending(
            "A pending Apostl authorization already exists; resume it or cancel it locally before starting another."
        ) from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"status": "creating"}, handle)
        handle.write("\n")


def _load_private_json(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if not path.exists():
        return {}
    if os.name != "nt" and (path.stat().st_mode & 0o077):
        raise PermissionError(f"{label} file must be mode 0600: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} file must contain a JSON object: {path}")
    return payload


def load_credentials(path: Path) -> dict[str, str]:
    payload = _load_private_json(path, "Credential")
    return {key: str(value) for key, value in payload.items() if isinstance(value, str)}


def load_pending_authorization(path: Path) -> dict[str, Any]:
    return _load_private_json(path, "Pending authorization")


Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], dict[str, Any]]


class ApostlClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None, transport: Transport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or self._http_transport

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def request_authorization(
        self,
        payload: dict[str, Any],
        pending_path: Path = DEFAULT_PENDING_AUTHORIZATION,
        *,
        now: Callable[[], float] = time.time,
    ) -> dict[str, Any]:
        reserve_pending_authorization(pending_path)
        data = self._request("POST", "/agent/authorizations", payload, authenticated=False)
        required = ("authorization_request_id", "device_code", "verification_uri_complete",
                    "expires_at", "expires_in", "interval", "status")
        if any(not data.get(field) for field in required) or data.get("status") != "pending":
            raise ApiError(502, "invalid_authorization_response", "Retry without creating a second transaction",
                           "A required pending authorization field was missing")
        expires_in = _positive_float(data["expires_in"], "expires_in")
        interval = _positive_float(data["interval"], "interval")
        verification_url = str(data["verification_uri_complete"])
        self._validate_verification_url(verification_url)
        save_pending_authorization(pending_path, {
            "authorization_request_id": str(data["authorization_request_id"]),
            "device_code": str(data["device_code"]),
            "interval": min(interval, MAX_AUTHORIZATION_INTERVAL_SECONDS),
            "expires_at": str(data["expires_at"]),
            "deadline_epoch": now() + expires_in,
        })
        return {
            "verification_url": verification_url,
            "expires_at": str(data["expires_at"]),
            "expires_in": int(expires_in) if expires_in.is_integer() else expires_in,
        }

    def wait_authorization(
        self,
        pending_path: Path = DEFAULT_PENDING_AUTHORIZATION,
        credential_path: Path = DEFAULT_CREDENTIALS,
        *,
        max_wait_seconds: float = 900,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        jitter: Callable[[float], float] = lambda upper: random.uniform(0, upper),
    ) -> dict[str, Any]:
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be greater than zero")
        pending = load_pending_authorization(pending_path)
        device_code = str(pending.get("device_code", ""))
        if not device_code:
            raise AuthorizationError("No resumable Apostl authorization was found. Run authorize first.")
        interval = min(MAX_AUTHORIZATION_INTERVAL_SECONDS,
                       max(1.0, float(pending.get("interval", 5))))
        remaining = max(0.0, float(pending.get("deadline_epoch", 0)) - wall_time())
        if remaining <= 0:
            pending_path.expanduser().unlink(missing_ok=True)
            raise AuthorizationExpired("Apostl authorization expired before polling; no API key was stored.")
        started = monotonic()
        deadline = started + min(float(max_wait_seconds), remaining)

        while monotonic() < deadline:
            try:
                response = self.transport(
                    "POST", "/agent/authorizations/token", {"device_code": device_code},
                    self._request_headers(),
                )
            except ApiError as error:
                action = self._authorization_error_action(error.code, pending_path)
                if action is not None:
                    raise action from None
                if error.code not in {"authorization_pending", "slow_down"}:
                    raise
                retry_after = error.retry_after
                state = error.code
            else:
                metadata = response.get("_response", {}) if isinstance(response, dict) else {}
                headers = metadata.get("headers", {}) if isinstance(metadata, dict) else {}
                retry_after = _retry_after_seconds(headers)
                error_payload = response.get("error", {}) if isinstance(response, dict) else {}
                data = response.get("data", {}) if isinstance(response, dict) else {}
                if isinstance(error_payload, dict) and error_payload.get("code"):
                    code = str(error_payload["code"])
                    action = self._authorization_error_action(code, pending_path)
                    if action is not None:
                        raise action
                    if code not in {"authorization_pending", "slow_down"}:
                        raise ApiError(int(metadata.get("status", 400)), code,
                                       "Inspect the Apostl authorization page and retry safely",
                                       str(error_payload.get("message", "Authorization failed")),
                                       retry_after=retry_after)
                    state = code
                elif isinstance(data, dict):
                    state = str(data.get("status", ""))
                    if state == "consumed" and data.get("api_key"):
                        result = dict(data)
                        api_key = str(result.pop("api_key"))
                        save_credentials(credential_path, api_key, self.base_url)
                        self.api_key = api_key
                        pending_path.expanduser().unlink(missing_ok=True)
                        return result
                    action = self._authorization_error_action(state, pending_path)
                    if action is not None:
                        raise action
                    if state not in {"pending", "authorization_pending", "approved", "slow_down"}:
                        raise ApiError(502, "invalid_authorization_response",
                                       "Keep the pending file and retry after inspecting API status",
                                       "Authorization status was not recognized")
                else:
                    raise ApiError(502, "invalid_authorization_response", "Retry safely",
                                   "Authorization response was not an object")

            if state == "slow_down":
                interval = min(MAX_AUTHORIZATION_INTERVAL_SECONDS, interval + 5.0)
            jitter_upper = min(1.0, interval * 0.1)
            jitter_value = min(jitter_upper, max(0.0, float(jitter(jitter_upper))))
            delay = min(MAX_AUTHORIZATION_INTERVAL_SECONDS, interval + jitter_value)
            if retry_after is not None:
                delay = max(delay, retry_after)
            if monotonic() + delay >= deadline:
                break
            sleep(delay)

        raise TimeoutError("Apostl authorization did not complete before the absolute deadline; rerun wait-authorization to resume if it has not expired.")

    def cancel_authorization(self, pending_path: Path = DEFAULT_PENDING_AUTHORIZATION) -> dict[str, str]:
        pending_path.expanduser().unlink(missing_ok=True)
        return {"status": "cancelled_locally"}

    def _authorization_error_action(self, code: str, pending_path: Path) -> AuthorizationError | None:
        mapping = {
            "denied": AuthorizationDenied,
            "authorization_denied": AuthorizationDenied,
            "expired": AuthorizationExpired,
            "authorization_expired": AuthorizationExpired,
            "consumed": AuthorizationConsumed,
            "authorization_consumed": AuthorizationConsumed,
            "cancelled": AuthorizationCancelled,
            "authorization_cancelled": AuthorizationCancelled,
        }
        exception = mapping.get(code)
        if exception is None:
            return None
        pending_path.expanduser().unlink(missing_ok=True)
        return exception(f"Apostl authorization ended with status {code}; no API key was stored.")

    def _validate_verification_url(self, value: str) -> None:
        verification = urllib.parse.urlsplit(value)
        api = urllib.parse.urlsplit(self.base_url)
        loopback = {"127.0.0.1", "::1", "localhost"}
        if verification.hostname != api.hostname or verification.port != api.port:
            raise ApiError(502, "invalid_verification_url", "Do not open the link; retry authorization",
                           "Verification URL was not owned by the configured Apostl platform")
        if verification.scheme != "https" and not ({verification.hostname, api.hostname} <= loopback):
            raise ApiError(502, "invalid_verification_url", "Do not open the link; retry authorization",
                           "Verification URL was not HTTPS")

    def request_registration(self, agent_name: str, email: str) -> dict[str, Any]:
        return self._request("POST", "/agent/registrations", {"agent_name": agent_name, "email": email}, authenticated=False)

    def activate(self, pending_id: str, code: str, credential_path: Path = DEFAULT_CREDENTIALS) -> dict[str, Any]:
        data = self._request("POST", f"/agent/registrations/{pending_id}/activate", {"code": code}, authenticated=False)
        api_key = str(data.pop("api_key"))
        save_credentials(credential_path, api_key, self.base_url)
        self.api_key = api_key
        return data

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/agent/me")

    def balance(self) -> dict[str, Any]:
        return self._request("GET", "/agent/balance")

    def preview_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare_feedback(payload)
        return {
            "endpoint": "/agent/feedback",
            "mutates": False,
            "submission_mutates": True,
            "requires_confirmation": True,
            "payload": prepared,
        }

    def submit_feedback(
        self,
        payload: dict[str, Any],
        *,
        confirmed: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        prepared = self._prepare_feedback(payload)
        self._confirm(confirmed)
        self._idempotency_key(idempotency_key)
        return self._request(
            "POST", "/agent/feedback", {"confirmed": True, **prepared},
            idempotency_key=idempotency_key,
        )

    def list_feedback(self, *, cursor: int | None = None, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 50:
            raise ValueError("feedback limit must be between 1 and 50")
        if cursor is not None and (
            isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0
        ):
            raise ValueError("feedback cursor must be a nonnegative integer")
        if not self.api_key:
            raise ApiError(401, "credentials_missing", "Authorize or load ~/.config/apostl/credentials.json",
                           "No API key")
        query: list[tuple[str, str | int]] = []
        if cursor is not None:
            query.append(("cursor", cursor))
        query.append(("limit", limit))
        path = "/agent/feedback?" + urllib.parse.urlencode(query)
        response = self.transport("GET", path, None, self._request_headers(authenticated=True))
        data = response.get("data") if isinstance(response, dict) else None
        if isinstance(data, dict):
            items = data.get("items", [])
        else:
            items = data
        metadata = response.get("meta", {}) if isinstance(response, dict) else {}
        if not isinstance(items, list) or not isinstance(metadata, dict):
            raise ApiError(502, "invalid_response", "Retry and inspect the API status",
                           "Feedback list was not a cursor response")
        return {"items": items, "next_cursor": metadata.get("next_cursor")}

    def _prepare_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or set(payload) - FEEDBACK_FIELDS:
            raise ValueError("Feedback accepts only target, kind, message, and target revision; local files, diffs, transcripts, and diagnostics are not accepted.")
        target_type = payload.get("target_type")
        kind = payload.get("kind")
        target_public_id = payload.get("target_public_id")
        message = payload.get("message")
        target_revision = payload.get("target_revision")
        if target_type not in FEEDBACK_TARGET_TYPES:
            raise ValueError("Unsupported feedback target_type")
        if kind not in FEEDBACK_KINDS:
            raise ValueError("Unsupported feedback kind")
        if not isinstance(target_public_id, str) or not target_public_id.strip():
            raise ValueError("target_public_id is required")
        if message is not None and (not isinstance(message, str) or len(message) > 4000):
            raise ValueError("feedback message must be at most 4000 characters")
        if target_revision is not None and (not isinstance(target_revision, str) or len(target_revision) > 120):
            raise ValueError("target_revision must be at most 120 characters")
        return sanitize_data(payload, reject_keys=True)

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agent/deployments/preview", payload)

    def create_project(self, payload: dict[str, Any], *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
        self._idempotency_key(idempotency_key)
        return self._request("POST", "/agent/projects", payload, idempotency_key=idempotency_key)

    def create_workflow(self, project_id: int, payload: dict[str, Any], *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
        self._idempotency_key(idempotency_key)
        return self._request("POST", f"/agent/projects/{project_id}/workflows", payload, idempotency_key=idempotency_key)

    def start_run(self, workflow_id: int, *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
        self._idempotency_key(idempotency_key)
        return self._request("POST", f"/agent/workflows/{workflow_id}/runs", {"confirmed": True}, idempotency_key=idempotency_key)

    def run_status(self, run_id: int) -> dict[str, Any]:
        return self._request("GET", f"/agent/runs/{run_id}")

    def poll_run(
        self,
        run_id: int,
        *,
        interval_seconds: float = 5,
        max_attempts: int = 120,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        terminal = {"passed", "blocked", "stalled", "failed", "cancelled", "superseded"}
        for attempt in range(max_attempts):
            result = self.run_status(run_id)
            if str(result.get("status")) in terminal:
                return result
            if attempt + 1 < max_attempts:
                sleep(interval_seconds)

        raise TimeoutError(f"Run {run_id} did not reach a terminal state after {max_attempts} polls")

    def rotate(self, credential_path: Path = DEFAULT_CREDENTIALS) -> dict[str, Any]:
        data = self._request("POST", "/agent/api-key/rotate", {})
        api_key = str(data.pop("api_key"))
        save_credentials(credential_path, api_key, self.base_url)
        self.api_key = api_key
        return data

    def revoke(self, credential_path: Path = DEFAULT_CREDENTIALS) -> None:
        self._request("DELETE", "/agent/api-key")
        self.api_key = None
        try:
            credential_path.expanduser().unlink()
        except FileNotFoundError:
            pass

    def _confirm(self, confirmed: bool) -> None:
        if not confirmed:
            raise ConfirmationRequired("Preview the mutation and obtain explicit user confirmation first.")

    def _idempotency_key(self, value: str | None) -> str:
        if not isinstance(value, str) or IDEMPOTENCY_PATTERN.fullmatch(value) is None:
            raise ValueError("A stable idempotency key using letters, numbers, dot, underscore, colon, or dash is required.")
        return value

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                 *, authenticated: bool = True, idempotency_key: str | None = None) -> dict[str, Any]:
        headers = self._request_headers(authenticated=authenticated, idempotency_key=idempotency_key)
        response = self.transport(method, path, payload, headers)
        data = response.get("data", response)
        if not isinstance(data, dict):
            raise ApiError(502, "invalid_response", "Retry and inspect the API status", "Response data was not an object")
        return data

    def _request_headers(self, *, authenticated: bool = False,
                         idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        if authenticated:
            if not self.api_key:
                raise ApiError(401, "credentials_missing", "Authorize or load ~/.config/apostl/credentials.json", "No API key")
            headers["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _http_transport(self, method: str, path: str, payload: dict[str, Any] | None,
                        headers: dict[str, str]) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status == 204:
                    result = {"data": {}}
                else:
                    result = json.loads(response.read().decode())
                if not isinstance(result, dict):
                    raise ApiError(502, "invalid_response", "Retry and inspect the API status",
                                   "Response body was not a JSON object")
                result["_response"] = {"status": response.status, "headers": dict(response.headers.items())}
                return result
        except urllib.error.HTTPError as error:
            try:
                failure = json.loads(error.read().decode()).get("error", {})
            except (json.JSONDecodeError, UnicodeDecodeError):
                failure = {}
            recovery = _redact_request_values(
                str(failure.get("recovery", "Inspect the API documentation and retry safely")), payload,
            )
            message = _redact_request_values(str(failure.get("message", error.reason)), payload)
            raise ApiError(
                error.code,
                str(failure.get("code", "api_error")),
                recovery,
                message,
                retry_after=_retry_after_seconds(dict(error.headers.items())) if error.headers else None,
            ) from None


def _client(args: argparse.Namespace) -> ApostlClient:
    credentials = load_credentials(args.credentials)
    return ApostlClient(credentials.get("api_base", args.base_url), credentials.get("api_key"))


def _positive_float(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ApiError(502, "invalid_authorization_response", "Retry authorization safely",
                       f"{name} was not numeric") from None
    if parsed <= 0:
        raise ApiError(502, "invalid_authorization_response", "Retry authorization safely",
                       f"{name} must be greater than zero")
    return parsed


def _retry_after_seconds(headers: dict[str, Any]) -> float | None:
    value = next((item for key, item in headers.items() if str(key).lower() == "retry-after"), None)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 1:
        return 1.0
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    parser.add_argument("--authorization", type=Path, default=DEFAULT_PENDING_AUTHORIZATION)
    commands = parser.add_subparsers(dest="command", required=True)
    authorization = commands.add_parser("authorize")
    authorization.add_argument("--agent-name", required=True)
    authorization.add_argument("--device-name", required=True)
    authorization.add_argument("--client-instance-id")
    authorization.add_argument("--skill-version", default=SKILL_VERSION)
    authorization.add_argument("--scope", action="append", dest="scopes")
    _add_journey_arguments(authorization, include_source=True)
    waiting = commands.add_parser("wait-authorization")
    waiting.add_argument("--max-wait-seconds", type=_bounded_float(1, 1800), default=900)
    commands.add_parser("cancel-authorization")

    registration = commands.add_parser("register", help="Deprecated browserless email-code fallback")
    registration.add_argument("--agent-name", required=True)
    registration.add_argument("--email", required=True)
    activation = commands.add_parser("activate", help="Deprecated browserless email-code fallback")
    activation.add_argument("--pending-id", required=True)
    activation.add_argument("--code", required=True)
    for name in ("me", "balance", "rotate", "revoke"):
        commands.add_parser(name)

    preview = commands.add_parser("preview")
    _add_journey_arguments(preview, include_source=True)

    feedback_preview = commands.add_parser("feedback-preview")
    _add_feedback_arguments(feedback_preview)
    feedback_submit = commands.add_parser("feedback-submit")
    _add_feedback_arguments(feedback_submit)
    _add_mutation_arguments(feedback_submit)
    feedback_list = commands.add_parser("feedback-list")
    feedback_list.add_argument("--cursor", type=_nonnegative_int)
    feedback_list.add_argument("--limit", type=_bounded_int(1, 50), default=50)

    project = commands.add_parser("project")
    project.add_argument("--source-url", required=True)
    project.add_argument("--name")
    project.add_argument("--description")
    _add_mutation_arguments(project)

    workflow = commands.add_parser("workflow")
    workflow.add_argument("--project-id", required=True, type=int)
    _add_journey_arguments(workflow, include_source=False)
    workflow.add_argument("--name")
    workflow.add_argument("--description")
    _add_mutation_arguments(workflow)

    run = commands.add_parser("run")
    run.add_argument("--workflow-id", required=True, type=int)
    _add_mutation_arguments(run)

    poll = commands.add_parser("poll")
    poll.add_argument("--run-id", required=True, type=int)
    poll.add_argument("--interval-seconds", type=_bounded_float(0, 60), default=5)
    poll.add_argument("--max-attempts", type=_bounded_int(1, 600), default=120)
    return parser


def _add_journey_arguments(parser: argparse.ArgumentParser, *, include_source: bool) -> None:
    if include_source:
        parser.add_argument("--source-url", required=True)
    parser.add_argument("--journey-url", required=True)
    parser.add_argument("--expected-activation", required=True)
    parser.add_argument("--run-mode", choices=("external_strict", "partner_self_healing"), required=True)


def _add_mutation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirm", action="store_true", required=True)
    parser.add_argument("--idempotency-key", required=True)


def _add_feedback_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-type", choices=sorted(FEEDBACK_TARGET_TYPES), required=True)
    parser.add_argument("--target-public-id", required=True)
    parser.add_argument("--kind", choices=sorted(FEEDBACK_KINDS), required=True)
    parser.add_argument("--message")
    parser.add_argument("--target-revision")


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        parsed = int(value)
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return parsed
    return parse


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def _bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        parsed = float(value)
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError(f"must be between {minimum} and {maximum}")
        return parsed
    return parse


def _compact_payload(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = _client(args)
    if args.command == "authorize":
        result = client.request_authorization({
            "agent_name": args.agent_name,
            "skill_name": SKILL_NAME,
            "skill_version": args.skill_version,
            "device_name": args.device_name,
            "client_instance_id": args.client_instance_id or str(uuid.uuid4()),
            "requested_scopes": args.scopes or list(DEFAULT_SCOPES),
            "intended_action": {
                "source_url": args.source_url,
                "journey_url": args.journey_url,
                "expected_activation": args.expected_activation,
                "run_mode": args.run_mode,
            },
        }, args.authorization)
    elif args.command == "wait-authorization":
        result = client.wait_authorization(
            args.authorization, args.credentials, max_wait_seconds=args.max_wait_seconds,
        )
    elif args.command == "cancel-authorization":
        result = client.cancel_authorization(args.authorization)
    elif args.command == "register":
        result = client.request_registration(args.agent_name, args.email)
    elif args.command == "activate":
        result = client.activate(args.pending_id, args.code, args.credentials)
    elif args.command == "me":
        result = client.me()
    elif args.command == "balance":
        result = client.balance()
    elif args.command == "feedback-preview":
        result = client.preview_feedback(_compact_payload(
            target_type=args.target_type, target_public_id=args.target_public_id,
            kind=args.kind, message=args.message, target_revision=args.target_revision,
        ))
    elif args.command == "feedback-submit":
        result = client.submit_feedback(
            _compact_payload(
                target_type=args.target_type, target_public_id=args.target_public_id,
                kind=args.kind, message=args.message, target_revision=args.target_revision,
            ),
            confirmed=args.confirm, idempotency_key=args.idempotency_key,
        )
    elif args.command == "feedback-list":
        result = client.list_feedback(cursor=args.cursor, limit=args.limit)
    elif args.command == "preview":
        result = client.preview(_compact_payload(
            source_url=args.source_url, journey_url=args.journey_url,
            expected_activation=args.expected_activation, run_mode=args.run_mode,
        ))
    elif args.command == "project":
        result = client.create_project(
            _compact_payload(source_url=args.source_url, name=args.name, description=args.description),
            confirmed=args.confirm, idempotency_key=args.idempotency_key,
        )
    elif args.command == "workflow":
        result = client.create_workflow(
            args.project_id,
            _compact_payload(journey_url=args.journey_url, expected_activation=args.expected_activation,
                             run_mode=args.run_mode, name=args.name, description=args.description),
            confirmed=args.confirm, idempotency_key=args.idempotency_key,
        )
    elif args.command == "run":
        result = client.start_run(
            args.workflow_id, confirmed=args.confirm, idempotency_key=args.idempotency_key,
        )
    elif args.command == "poll":
        result = client.poll_run(
            args.run_id, interval_seconds=args.interval_seconds, max_attempts=args.max_attempts,
        )
    elif args.command == "rotate":
        result = client.rotate(args.credentials)
    else:
        client.revoke(args.credentials)
        result = {"status": "revoked"}
    print(json.dumps(sanitize_data(result, reject_keys=False), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
