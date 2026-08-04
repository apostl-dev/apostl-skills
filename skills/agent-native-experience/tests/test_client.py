import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
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
