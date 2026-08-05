import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_client():
    spec = importlib.util.spec_from_file_location("apostl_client", SKILL_ROOT / "scripts/apostl_client.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.client = load_client()

    def test_credential_file_is_mode_0600_and_output_is_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            self.client.save_credentials(path, "123|apostl_secret_value", "https://platform.apostl.dev/api/v1")
            mode = stat.S_IMODE(path.stat().st_mode)
            payload = json.loads(path.read_text())

            self.assertEqual(0o600, mode)
            self.assertEqual("123|apostl_secret_value", payload["api_key"])
            self.assertNotIn("apostl_secret_value", self.client.redact("failure 123|apostl_secret_value"))
            self.assertIn("[REDACTED]", self.client.redact("failure 123|apostl_secret_value"))

    def test_registration_pauses_for_human_code_and_never_echoes_full_key(self):
        responses = [
            {"data": {"pending_registration_id": "pending-1", "status": "pending"}},
            {"data": {"status": "active", "api_key": "123|apostl_secret_value", "api_key_prefix": "123|apos"}},
        ]
        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1", transport=lambda *args: responses.pop(0))
        pending = fake.request_registration("Audit Agent", "human@example.com")
        self.assertEqual("pending", pending["status"])
        self.assertFalse(fake.has_credentials)

        with tempfile.TemporaryDirectory() as directory:
            activated = fake.activate("pending-1", "123456", Path(directory) / "credentials.json")
            self.assertEqual("123|apos", activated["api_key_prefix"])
            self.assertNotIn("api_key", activated)
            self.assertTrue(fake.has_credentials)

    def test_authorize_uses_apostl_link_contract_and_persists_pending_secret_as_0600(self):
        calls = []

        def transport(method, path, payload, headers):
            calls.append((method, path, payload, headers))
            return {"data": {
                "authorization_request_id": "authorization-1",
                "device_code": "opaque-device-secret",
                "verification_uri_complete": "https://platform.apostl.dev/agent/authorize/browser-token",
                "expires_at": "2026-08-05T04:15:00Z",
                "expires_in": 600,
                "interval": 5,
                "status": "pending",
            }}

        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1", transport=transport)
        payload = {
            "agent_name": "Codex local agent",
            "skill_name": "agent-native-experience",
            "skill_version": "1.1.2",
            "device_name": "Codex local agent",
            "client_instance_id": "83e765c7-cc57-47b6-b7a6-8f59a8ab032a",
            "requested_scopes": ["agent:read", "agent:deploy", "agent:keys"],
            "intended_action": {
                "source_url": "https://www.w3schools.com/",
                "journey_url": "https://www.w3schools.com/html/html_intro.asp",
                "expected_activation": "Observe the rendered heading and paragraph.",
                "run_mode": "external_strict",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            visible = fake.request_authorization(payload, pending_path, now=lambda: 1000.0)
            stored = json.loads(pending_path.read_text())

            self.assertEqual(0o600, stat.S_IMODE(pending_path.stat().st_mode))
            self.assertEqual("opaque-device-secret", stored["device_code"])
            self.assertEqual(1600.0, stored["deadline_epoch"])
            self.assertEqual({
                "verification_url": "https://platform.apostl.dev/agent/authorize/browser-token",
                "expires_at": "2026-08-05T04:15:00Z",
                "expires_in": 600,
            }, visible)
            self.assertNotIn("device_code", visible)

        self.assertEqual("POST", calls[0][0])
        self.assertEqual("/agent/authorizations", calls[0][1])
        self.assertEqual(payload, calls[0][2])
        self.assertNotIn("Authorization", calls[0][3])
        self.assertEqual(
            "Apostl-Agent-Native-Experience/1.1.2 (+https://platform.apostl.dev)",
            calls[0][3]["User-Agent"],
        )

    def test_authorize_refuses_to_replace_a_pending_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "existing-secret", "interval": 5, "deadline_epoch": 2000,
            })
            fake = self.client.ApostlClient(
                "https://platform.apostl.dev/api/v1",
                transport=lambda *_args: self.fail("must not create a second transaction"),
            )
            with self.assertRaises(self.client.AuthorizationPending):
                fake.request_authorization({}, pending_path, now=lambda: 1000.0)

    def test_wait_authorization_obeys_retry_after_and_slow_down_then_saves_key_once(self):
        calls = []
        responses = [
            {"error": {"code": "authorization_pending", "message": "Pending"},
             "_response": {"status": 202, "headers": {"Retry-After": "7"}}},
            {"error": {"code": "slow_down", "message": "Slow down"},
             "_response": {"status": 429, "headers": {"Retry-After": "12"}}},
            {"data": {
                "status": "consumed",
                "api_key": "123|apostl_one_time_secret",
                "api_key_prefix": "123|apos",
                "api_key_created_at": "2026-08-05T04:10:00Z",
                "client_id": "client-1",
                "identity": {"id": 1},
                "workspace": {"id": 2},
                "scopes": ["agent:read", "agent:deploy", "agent:keys"],
                "balance": {"available": 100, "reserved": 0},
            }, "_response": {"status": 201, "headers": {}}},
        ]
        def transport(*args):
            calls.append(args)
            return responses.pop(0)

        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1", transport=transport)
        elapsed = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            elapsed[0] += seconds

        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            credentials = Path(directory) / "credentials.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "opaque-device-secret",
                "interval": 5,
                "deadline_epoch": 1100.0,
            })
            result = fake.wait_authorization(
                pending_path,
                credentials,
                max_wait_seconds=100,
                sleep=sleep,
                monotonic=lambda: elapsed[0],
                wall_time=lambda: 1000.0 + elapsed[0],
                jitter=lambda _upper: 0.0,
            )

            self.assertEqual([7.0, 12.0], sleeps)
            self.assertEqual("consumed", result["status"])
            self.assertEqual("123|apos", result["api_key_prefix"])
            self.assertNotIn("api_key", result)
            self.assertFalse(pending_path.exists())
            self.assertEqual(0o600, stat.S_IMODE(credentials.stat().st_mode))
            self.assertEqual("123|apostl_one_time_secret", json.loads(credentials.read_text())["api_key"])
            self.assertTrue(calls)
            self.assertTrue(all(call[3]["User-Agent"] == self.client.USER_AGENT for call in calls))

    def test_wait_authorization_obeys_retry_after_above_local_backoff_cap(self):
        responses = [
            {"error": {"code": "authorization_pending", "message": "Pending"},
             "_response": {"status": 202, "headers": {"Retry-After": "120"}}},
            {"data": {
                "status": "consumed",
                "api_key": "123|apostl_one_time_secret",
                "api_key_prefix": "123|apos",
            }, "_response": {"status": 201, "headers": {}}},
        ]
        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1", transport=lambda *_args: responses.pop(0),
        )
        elapsed = [0.0]
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            elapsed[0] += seconds

        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "opaque-device-secret",
                "interval": 5,
                "deadline_epoch": 1300.0,
            })
            fake.wait_authorization(
                pending_path,
                Path(directory) / "credentials.json",
                max_wait_seconds=300,
                sleep=sleep,
                monotonic=lambda: elapsed[0],
                wall_time=lambda: 1000.0 + elapsed[0],
                jitter=lambda _upper: 0.0,
            )

        self.assertEqual([120.0], sleeps)

    def test_wait_authorization_handles_approved_denied_expired_consumed_and_cancelled(self):
        cases = {
            "authorization_denied": self.client.AuthorizationDenied,
            "authorization_expired": self.client.AuthorizationExpired,
            "authorization_consumed": self.client.AuthorizationConsumed,
            "authorization_cancelled": self.client.AuthorizationCancelled,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for code, expected in cases.items():
                pending_path = root / f"{code}.json"
                self.client.save_pending_authorization(pending_path, {
                    "device_code": f"{code}-secret", "interval": 5, "deadline_epoch": 1100.0,
                })
                fake = self.client.ApostlClient(
                    "https://platform.apostl.dev/api/v1",
                    transport=lambda *_args, code=code: {
                        "error": {"code": code, "message": "Terminal"},
                        "_response": {"status": 400, "headers": {}},
                    },
                )
                with self.assertRaises(expected):
                    fake.wait_authorization(
                        pending_path, root / "credentials.json", max_wait_seconds=10,
                        sleep=lambda _seconds: None, monotonic=lambda: 0.0,
                        wall_time=lambda: 1000.0, jitter=lambda _upper: 0.0,
                    )
                self.assertFalse(pending_path.exists())

            approved_path = root / "approved.json"
            self.client.save_pending_authorization(approved_path, {
                "device_code": "approved-secret", "interval": 5, "deadline_epoch": 1100.0,
            })
            approved_responses = [
                {"data": {"status": "approved"}, "_response": {"status": 202, "headers": {"Retry-After": "5"}}},
                {"error": {"code": "authorization_consumed", "message": "Already redeemed"},
                 "_response": {"status": 409, "headers": {}}},
            ]
            fake = self.client.ApostlClient(
                "https://platform.apostl.dev/api/v1", transport=lambda *_args: approved_responses.pop(0),
            )
            elapsed = [0.0]
            with self.assertRaises(self.client.AuthorizationConsumed):
                fake.wait_authorization(
                    approved_path, root / "credentials.json", max_wait_seconds=10,
                    sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
                    monotonic=lambda: elapsed[0], wall_time=lambda: 1000.0 + elapsed[0],
                    jitter=lambda _upper: 0.0,
                )

    def test_wait_authorization_has_absolute_deadline_and_never_busy_loops(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "opaque-device-secret", "interval": 0, "deadline_epoch": 1004.0,
            })
            fake = self.client.ApostlClient(
                "https://platform.apostl.dev/api/v1",
                transport=lambda *_args: calls.append(True) or {
                    "error": {"code": "authorization_pending", "message": "Pending"},
                    "_response": {"status": 202, "headers": {"Retry-After": "5"}},
                },
            )
            with self.assertRaises(TimeoutError):
                fake.wait_authorization(
                    pending_path, Path(directory) / "credentials.json", max_wait_seconds=4,
                    sleep=lambda _seconds: self.fail("must not sleep past the absolute deadline"),
                    monotonic=lambda: 0.0, wall_time=lambda: 1000.0,
                    jitter=lambda _upper: 0.0,
                )
            self.assertEqual(1, len(calls))
            self.assertTrue(pending_path.exists(), "timeouts remain resumable")

    def test_wait_authorization_clears_a_locally_expired_transaction_without_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "expired-device-secret", "interval": 5, "deadline_epoch": 999.0,
            })
            fake = self.client.ApostlClient(
                "https://platform.apostl.dev/api/v1",
                transport=lambda *_args: self.fail("expired authorization must not be polled"),
            )
            with self.assertRaises(self.client.AuthorizationExpired):
                fake.wait_authorization(
                    pending_path, Path(directory) / "credentials.json",
                    monotonic=lambda: 0.0, wall_time=lambda: 1000.0,
                )
            self.assertFalse(pending_path.exists())

    def test_local_cancel_removes_pending_secret_without_a_platform_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            pending_path = Path(directory) / "authorization.json"
            self.client.save_pending_authorization(pending_path, {
                "device_code": "opaque-device-secret", "interval": 5, "deadline_epoch": 2000,
            })
            fake = self.client.ApostlClient(
                "https://platform.apostl.dev/api/v1",
                transport=lambda *_args: self.fail("local cancellation must not call Apostl"),
            )
            self.assertEqual({"status": "cancelled_locally"}, fake.cancel_authorization(pending_path))
            self.assertFalse(pending_path.exists())

    def test_cli_authorize_prints_only_verification_url_and_expiry(self):
        visible = {
            "verification_url": "https://platform.apostl.dev/agent/authorize/browser-token",
            "expires_at": "2026-08-05T04:15:00Z",
            "expires_in": 600,
        }
        fake = type("FakeClient", (), {"request_authorization": lambda *_args, **_kwargs: visible})()
        argv = [
            "authorize", "--agent-name", "Codex local agent", "--device-name", "Codex local agent",
            "--source-url", "https://www.w3schools.com/",
            "--journey-url", "https://www.w3schools.com/html/html_intro.asp",
            "--expected-activation", "Rendered heading and paragraph",
            "--run-mode", "external_strict",
        ]
        stdout = io.StringIO()
        with patch.object(self.client, "_client", return_value=fake), patch("sys.stdout", stdout):
            self.assertEqual(0, self.client.main(argv))
        output = stdout.getvalue()
        self.assertEqual(visible, json.loads(output))
        self.assertNotIn("device", output.lower())
        self.assertNotIn("api_key", output)

    def test_feedback_preview_is_local_and_submit_is_confirmed_idempotent_and_minimized(self):
        calls = []

        def transport(method, path, payload, headers):
            calls.append((method, path, payload, headers))
            return {"data": {"id": "feedback-1", **payload}}

        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1", api_key="1|token", transport=transport,
        )
        payload = {
            "target_type": "run",
            "target_public_id": "run-public-1",
            "kind": "correction",
            "message": "Use the rendered activation signal.",
            "target_revision": "report-v2",
        }
        preview = fake.preview_feedback(payload)
        self.assertEqual(0, len(calls))
        self.assertFalse(preview["mutates"])
        self.assertTrue(preview["submission_mutates"])
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(payload, preview["payload"])

        with self.assertRaises(self.client.ConfirmationRequired):
            fake.submit_feedback(payload, confirmed=False, idempotency_key="feedback-1")
        self.assertEqual(0, len(calls))

        submitted = fake.submit_feedback(payload, confirmed=True, idempotency_key="feedback-1")
        self.assertEqual("feedback-1", submitted["id"])
        self.assertEqual("POST", calls[0][0])
        self.assertEqual("/agent/feedback", calls[0][1])
        self.assertEqual({"confirmed": True, **payload}, calls[0][2])
        self.assertEqual("feedback-1", calls[0][3]["Idempotency-Key"])

    def test_feedback_rejects_local_artifacts_invalid_states_and_oversized_messages(self):
        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1", api_key="1|token",
            transport=lambda *_args: self.fail("invalid feedback must stay local"),
        )
        valid = {
            "target_type": "recommendation", "target_public_id": "rec-1",
            "kind": "accepted_fix", "message": "Accepted after review.",
        }
        for invalid in (
            {**valid, "local_diff": "secret patch"},
            {**valid, "kind": "silently_overwrite"},
            {**valid, "target_type": "local_file"},
            {**valid, "message": "x" * 4001},
        ):
            with self.subTest(invalid=invalid.get("kind", invalid.get("target_type"))):
                with self.assertRaises(ValueError):
                    fake.preview_feedback(invalid)

    def test_feedback_list_is_read_only_cursor_bounded_and_uses_apostl_only(self):
        calls = []

        def transport(method, path, payload, headers):
            calls.append((method, path, payload, headers))
            return {
                "data": [{"id": "feedback-1", "kind": "follow_up_request"}],
                "meta": {"next_cursor": 2},
            }

        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1", api_key="1|token", transport=transport,
        )
        result = fake.list_feedback(cursor=1, limit=50)
        self.assertEqual([{"id": "feedback-1", "kind": "follow_up_request"}], result["items"])
        self.assertEqual(2, result["next_cursor"])
        self.assertEqual("GET", calls[0][0])
        self.assertEqual("/agent/feedback?cursor=1&limit=50", calls[0][1])
        self.assertIsNone(calls[0][2])
        self.assertIn("Authorization", calls[0][3])

        for kwargs in ({"limit": 51}, {"cursor": -1}, {"cursor": "1"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fake.list_feedback(**kwargs)

    def test_feedback_list_cli_enforces_server_limit_and_nonnegative_integer_cursor(self):
        parser = self.client.build_parser()

        parsed = parser.parse_args(["feedback-list", "--cursor", "0", "--limit", "50"])
        self.assertEqual(0, parsed.cursor)
        self.assertEqual(50, parsed.limit)

        for argv in (
            ["feedback-list", "--cursor", "-1"],
            ["feedback-list", "--cursor", "cursor-1"],
            ["feedback-list", "--limit", "51"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                parser.parse_args(argv)

    def test_mutation_requires_explicit_confirmation_and_preview(self):
        calls = []

        def transport(method, path, payload, headers):
            calls.append((method, path, payload, headers))
            return {"data": {"ok": True}}

        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1", api_key="1|token", transport=transport)
        preview = fake.preview({"source_url": "https://example.com/docs"})
        self.assertTrue(preview["ok"])
        with self.assertRaises(self.client.ConfirmationRequired):
            fake.create_project({"source_url": "https://example.com/docs"}, confirmed=False)
        self.assertEqual(1, len(calls))
        fake.create_project({"source_url": "https://example.com/docs"}, confirmed=True,
                            idempotency_key="project-1")
        self.assertEqual("project-1", calls[-1][3]["Idempotency-Key"])

    def test_mutating_calls_require_stable_idempotency_keys(self):
        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1",
            api_key="1|token",
            transport=lambda *_args: {"data": {"ok": True}},
        )

        for call in (
            lambda: fake.create_project({"source_url": "https://example.com"}, confirmed=True),
            lambda: fake.create_workflow(1, {"journey_url": "https://example.com"}, confirmed=True),
            lambda: fake.start_run(1, confirmed=True),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_cli_exposes_preview_project_workflow_run_and_bounded_poll(self):
        parser = self.client.build_parser()
        commands = parser._subparsers._group_actions[0].choices
        self.assertTrue({"preview", "project", "workflow", "run", "poll"}.issubset(commands))

        with self.assertRaises(SystemExit):
            parser.parse_args(["project", "--source-url", "https://example.com/docs"])

    def test_http_errors_keep_machine_code_and_actionable_recovery_without_secret(self):
        def transport(*_args):
            raise self.client.ApiError(422, "unsafe_url", "Use a public HTTPS URL", "1|token-secret")

        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1", api_key="1|token-secret", transport=transport)
        with self.assertRaises(self.client.ApiError) as caught:
            fake.preview({"source_url": "http://127.0.0.1"})
        rendered = str(caught.exception)
        self.assertIn("unsafe_url", rendered)
        self.assertIn("Use a public HTTPS URL", rendered)
        self.assertNotIn("token-secret", rendered)

    def test_http_authorization_error_never_echoes_the_opaque_device_secret(self):
        device_code = "opaque-value-without-a-secret-shaped-prefix"
        body = io.BytesIO(json.dumps({"error": {
            "code": "authorization_pending",
            "message": f"Still waiting for {device_code}",
            "recovery": f"Retry {device_code}",
        }}).encode())
        error = urllib.error.HTTPError(
            "https://platform.apostl.dev/api/v1/agent/authorizations/token",
            429, "Too Many Requests", {"Retry-After": "7"}, body,
        )
        fake = self.client.ApostlClient("https://platform.apostl.dev/api/v1")
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(self.client.ApiError) as caught:
                fake._http_transport(
                    "POST", "/agent/authorizations/token", {"device_code": device_code},
                    {"Accept": "application/json", "Content-Type": "application/json"},
                )
        self.assertNotIn(device_code, str(caught.exception))
        self.assertEqual(7.0, caught.exception.retry_after)

    def test_poll_run_stops_only_at_a_terminal_state_and_is_bounded(self):
        responses = [
            {"data": {"id": 7, "status": "queued"}},
            {"data": {"id": 7, "status": "running"}},
            {"data": {"id": 7, "status": "passed", "report_url": "https://platform.apostl.dev/reports/example"}},
        ]
        fake = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1",
            api_key="1|token",
            transport=lambda *_args: responses.pop(0),
        )

        result = fake.poll_run(7, interval_seconds=0, max_attempts=3, sleep=lambda _seconds: None)
        self.assertEqual("passed", result["status"])
        self.assertEqual("https://platform.apostl.dev/reports/example", result["report_url"])

        stuck = self.client.ApostlClient(
            "https://platform.apostl.dev/api/v1",
            api_key="1|token",
            transport=lambda *_args: {"data": {"id": 8, "status": "running"}},
        )
        with self.assertRaises(TimeoutError):
            stuck.poll_run(8, interval_seconds=0, max_attempts=2, sleep=lambda _seconds: None)


if __name__ == "__main__":
    unittest.main()
