#!/usr/bin/env python3
"""Minimal standard-library client for the Apostl Agent API v1."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_BASE_URL = "https://platform.apostl.dev/api/v1"
DEFAULT_CREDENTIALS = Path.home() / ".config" / "apostl" / "credentials.json"
TOKEN_PATTERN = re.compile(r"\b\d+\|[A-Za-z0-9_-]{12,}\b")


class ConfirmationRequired(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, recovery: str, message: str):
        self.status = status
        self.code = code
        self.recovery = recovery
        super().__init__(redact(f"HTTP {status} {code}: {message}. Recovery: {recovery}"))


def redact(value: str) -> str:
    return TOKEN_PATTERN.sub("[REDACTED]", value)


def save_credentials(path: Path, api_key: str, api_base: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"api_key": api_key, "api_base": api_base}, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_credentials(path: Path) -> dict[str, str]:
    path = path.expanduser()
    if not path.exists():
        return {}
    if os.name != "nt" and (path.stat().st_mode & 0o077):
        raise PermissionError(f"Credential file must be mode 0600: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key: str(value) for key, value in payload.items() if isinstance(value, str)}


Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], dict[str, Any]]


class ApostlClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None, transport: Transport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.transport = transport or self._http_transport

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)

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

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/agent/deployments/preview", payload)

    def create_project(self, payload: dict[str, Any], *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
        return self._request("POST", "/agent/projects", payload, idempotency_key=idempotency_key)

    def create_workflow(self, project_id: int, payload: dict[str, Any], *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
        return self._request("POST", f"/agent/projects/{project_id}/workflows", payload, idempotency_key=idempotency_key)

    def start_run(self, workflow_id: int, *, confirmed: bool, idempotency_key: str | None = None) -> dict[str, Any]:
        self._confirm(confirmed)
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

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None,
                 *, authenticated: bool = True, idempotency_key: str | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authenticated:
            if not self.api_key:
                raise ApiError(401, "credentials_missing", "Register or load ~/.config/apostl/credentials.json", "No API key")
            headers["Authorization"] = f"Bearer {self.api_key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.transport(method, path, payload, headers)
        data = response.get("data", response)
        if not isinstance(data, dict):
            raise ApiError(502, "invalid_response", "Retry and inspect the API status", "Response data was not an object")
        return data

    def _http_transport(self, method: str, path: str, payload: dict[str, Any] | None,
                        headers: dict[str, str]) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status == 204:
                    return {"data": {}}
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            try:
                failure = json.loads(error.read().decode()).get("error", {})
            except (json.JSONDecodeError, UnicodeDecodeError):
                failure = {}
            raise ApiError(error.code, str(failure.get("code", "api_error")),
                           str(failure.get("recovery", "Inspect the API documentation and retry safely")),
                           str(failure.get("message", error.reason))) from None


def _client(args: argparse.Namespace) -> ApostlClient:
    credentials = load_credentials(args.credentials)
    return ApostlClient(credentials.get("api_base", args.base_url), credentials.get("api_key"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    commands = parser.add_subparsers(dest="command", required=True)
    registration = commands.add_parser("register")
    registration.add_argument("--agent-name", required=True)
    registration.add_argument("--email", required=True)
    activation = commands.add_parser("activate")
    activation.add_argument("--pending-id", required=True)
    activation.add_argument("--code", required=True)
    for name in ("me", "balance", "rotate", "revoke"):
        commands.add_parser(name)
    args = parser.parse_args()
    client = _client(args)
    if args.command == "register":
        result = client.request_registration(args.agent_name, args.email)
    elif args.command == "activate":
        result = client.activate(args.pending_id, args.code, args.credentials)
    elif args.command == "me":
        result = client.me()
    elif args.command == "balance":
        result = client.balance()
    elif args.command == "rotate":
        result = client.rotate(args.credentials)
    else:
        client.revoke(args.credentials)
        result = {"status": "revoked"}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
