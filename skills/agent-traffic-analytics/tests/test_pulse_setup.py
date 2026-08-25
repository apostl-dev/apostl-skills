import importlib.util
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "pulse_setup.py"
SPEC = importlib.util.spec_from_file_location("pulse_setup", SCRIPT)
pulse_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pulse_setup)


class SetupHandler(BaseHTTPRequestHandler):
    mode = "ok"
    requests = []

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if self.__class__.mode == "conflict" and self.path == "/api/v1/pulse/setups":
            return self.respond(409, {"error": {"code": "origin_unavailable", "message": "This origin is already connected to Apostl Pulse."}})
        if self.path == "/api/v1/pulse/setups":
            return self.respond(201, {"data": {
                "setup_id": "6d878eea-e29f-4a55-a021-ac940fbf81a7",
                "status": "pending_deployment",
                "origin": "https://docs.example.com",
                "verification_url": "https://docs.example.com/llms.txt",
                "expires_at": "2026-09-01T00:00:00Z",
                "setup_token": "pulse_setup_" + "s" * 64,
                "verify_url": self.server.base_url + "/api/v1/pulse/setups/6d878eea-e29f-4a55-a021-ac940fbf81a7/verify",
                "credentials": {"api_key": "pulse_api_" + "k" * 48, "endpoint": "https://ingest.apostl.dev"},
            }})
        if self.path.endswith("/verify"):
            return self.respond(200, {"data": {
                "status": "verified",
                "claim_url": "https://platform.apostl.dev/pulse/claim/6d878eea-e29f-4a55-a021-ac940fbf81a7/claim-token",
            }})
        return self.respond(404, {"error": {"code": "not_found", "message": "Not found"}})

    def respond(self, status_code, payload):
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class PulseSetupCliTest(unittest.TestCase):
    def setUp(self):
        SetupHandler.mode = "ok"
        SetupHandler.requests = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), SetupHandler)
        self.server.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.tempdir = tempfile.TemporaryDirectory()
        self.credentials = Path(self.tempdir.name) / "pulse.json"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()

    def test_start_saves_secrets_with_mode_0600_without_printing_them(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = pulse_setup.main([
            "start",
            "--origin", "https://docs.example.com",
            "--project-name", "Example docs",
            "--verification-path", "/llms.txt",
            "--agent-name", "Codex",
            "--platform-url", self.server.base_url,
            "--credentials", str(self.credentials),
        ], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 0, stderr.getvalue())
        saved = json.loads(self.credentials.read_text())
        self.assertEqual(saved["api_key"], "pulse_api_" + "k" * 48)
        self.assertEqual(saved["setup_token"], "pulse_setup_" + "s" * 64)
        self.assertEqual(stat.S_IMODE(os.stat(self.credentials).st_mode), 0o600)
        self.assertNotIn(saved["api_key"], stdout.getvalue())
        self.assertNotIn(saved["setup_token"], stdout.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["status"], "pending_deployment")
        self.assertEqual(output["credentials_file"], str(self.credentials.resolve()))
        self.assertEqual(SetupHandler.requests[0]["body"]["origin"], "https://docs.example.com")

    def test_verify_uses_setup_token_and_returns_only_the_human_claim_handoff(self):
        self.test_start_saves_secrets_with_mode_0600_without_printing_them()
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = pulse_setup.main([
            "verify", "--credentials", str(self.credentials)
        ], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 0, stderr.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["status"], "verified")
        self.assertEqual(output["claim_url"], "https://platform.apostl.dev/pulse/claim/6d878eea-e29f-4a55-a021-ac940fbf81a7/claim-token")
        self.assertNotIn("pulse_api_", stdout.getvalue())
        verify_request = SetupHandler.requests[-1]
        self.assertEqual(verify_request["headers"]["Authorization"], "Bearer pulse_setup_" + "s" * 64)

    def test_origin_conflict_is_explicit_and_does_not_write_credentials(self):
        SetupHandler.mode = "conflict"
        stdout = io.StringIO()
        stderr = io.StringIO()

        result = pulse_setup.main([
            "start",
            "--origin", "https://docs.example.com",
            "--project-name", "Second project",
            "--platform-url", self.server.base_url,
            "--credentials", str(self.credentials),
        ], stdout=stdout, stderr=stderr)

        self.assertEqual(result, 1)
        self.assertIn("origin_unavailable", stderr.getvalue())
        self.assertIn("already connected", stderr.getvalue())
        self.assertFalse(self.credentials.exists())


if __name__ == "__main__":
    unittest.main()
