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
from urllib.parse import parse_qs


SCRIPT = Path(__file__).parents[1] / "scripts" / "pulse_setup.py"
SPEC = importlib.util.spec_from_file_location("pulse_setup", SCRIPT)
pulse_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pulse_setup)


class SetupHandler(BaseHTTPRequestHandler):
    mode = "ok"
    requests = []

    def do_GET(self):
        self.__class__.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
        base = self.server.base_url
        if self.path == "/auth.md":
            return self.respond_text(200, "# auth.md test\n\nAuth.md draft 0.6 agent registration.\n", "text/markdown")
        if self.path == "/.well-known/oauth-protected-resource":
            return self.respond(200, {
                "resource": base + "/api/v1/agent",
                "authorization_servers": [base],
                "scopes_supported": ["agent:read", "pulse:setup"],
                "bearer_methods_supported": ["header"],
            })
        if self.path == "/.well-known/oauth-authorization-server":
            issuer = "https://wrong-issuer.test" if self.__class__.mode == "bad_discovery" else base
            return self.respond(200, {
                "issuer": issuer,
                "token_endpoint": base + "/oauth2/token",
                "revocation_endpoint": base + "/oauth2/revoke",
                "jwks_uri": base + "/.well-known/jwks.json",
                "agent_auth": {
                    "skill": base + "/auth.md",
                    "identity_endpoint": base + "/agent/identity",
                    "claim_endpoint": base + "/agent/identity/claim",
                    "identity_types_supported": ["anonymous", "service_auth"],
                },
            })
        return self.respond(404, {"error": "not_found", "error_description": "Not found"})

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        if "application/x-www-form-urlencoded" in self.headers.get("content-type", ""):
            body = {key: values[0] for key, values in parse_qs(raw.decode()).items()}
        else:
            body = json.loads(raw or b"{}")
        self.__class__.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})

        if self.path == "/agent/identity":
            return self.respond(201, {
                "registration_id": "reg_01AUTHMD",
                "registration_type": "anonymous",
                "claim_token": "clm_" + "c" * 40,
                "claim_token_expires": "2026-09-05T00:00:00Z",
                "identity_assertion": "header.payload.signature",
                "assertion_expires": "2026-08-29T01:00:00Z",
                "pre_claim_scopes": ["pulse:setup"],
                "post_claim_scopes": ["agent:read", "pulse:setup"],
            })
        if self.path == "/oauth2/token":
            if body.get("grant_type") == "urn:ietf:params:oauth:grant-type:jwt-bearer":
                return self.respond(200, {
                    "access_token": "authmd_" + "a" * 64,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "pulse:setup",
                })
            if self.__class__.mode == "expired_claim":
                return self.respond(400, {
                    "error": "expired_token",
                    "error_description": "The user-code window expired.",
                }, {"Retry-After": "5"})
            if self.__class__.mode == "pending_claim":
                return self.respond(400, {
                    "error": "authorization_pending",
                    "error_description": "The user has not completed claim.",
                }, {"Retry-After": "5"})
            return self.respond(200, {
                "access_token": "1|" + "p" * 64,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "agent:read agent:deploy agent:keys agent:feedback pulse:setup",
                "identity_assertion": "post.claim.signature",
                "assertion_expires": "2026-08-29T02:00:00Z",
            })
        if self.__class__.mode == "conflict" and self.path == "/api/v1/pulse/setups":
            return self.respond(409, {"error": {
                "code": "origin_unavailable",
                "message": "This origin is already connected to Apostl Pulse.",
                "resolution": "Resume with the saved setup credentials if this is your setup.",
            }})
        if self.path == "/api/v1/pulse/setups":
            return self.respond(201, {"data": {
                "setup_id": "6d878eea-e29f-4a55-a021-ac940fbf81a7",
                "status": "pending_deployment",
                "origin": "https://docs.acme.dev",
                "verification_url": "https://docs.acme.dev/llms.txt",
                "expires_at": "2026-09-05T00:00:00Z",
                "setup_token": "pulse_setup_" + "s" * 64,
                "verify_url": self.server.base_url + "/api/v1/pulse/setups/6d878eea-e29f-4a55-a021-ac940fbf81a7/verify",
                "credentials": {"api_key": "pulse_api_" + "k" * 48, "endpoint": "https://ingest.apostl.dev"},
            }})
        if self.path.endswith("/verify"):
            return self.respond(200, {"data": {
                "status": "verified",
                "claim_url": "https://platform.apostl.dev/pulse/claim/legacy-token",
            }})
        if self.path == "/agent/identity/claim":
            return self.respond(201, {
                "registration_id": "reg_01AUTHMD",
                "claim_attempt_id": "cla_01CLAIM",
                "status": "initiated",
                "expires_at": "2026-08-29T00:10:00Z",
                "claim_attempt": {
                    "user_code": "123456",
                    "expires_in": 600,
                    "verification_uri": self.server.base_url + "/agent/identity/claim/cat_secret",
                    "interval": 5,
                },
            })
        if self.path == "/oauth2/revoke":
            return self.respond(200, {})
        return self.respond(404, {"error": {"code": "not_found", "message": "Not found"}})

    def respond(self, status_code, payload, headers=None):
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("content-type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_text(self, status_code, value, content_type):
        body = value.encode()
        self.send_response(status_code)
        self.send_header("content-type", content_type)
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

    def start(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        result = pulse_setup.main([
            "start",
            "--origin", "https://docs.acme.dev",
            "--project-name", "Example docs",
            "--verification-path", "/llms.txt",
            "--agent-name", "Codex",
            "--platform-url", self.server.base_url,
            "--credentials", str(self.credentials),
        ], stdout=stdout, stderr=stderr)
        return result, stdout, stderr

    def test_start_discovers_auth_md_and_saves_every_secret_0600_without_printing_it(self):
        result, stdout, stderr = self.start()

        self.assertEqual(result, 0, stderr.getvalue())
        saved = json.loads(self.credentials.read_text())
        self.assertEqual(saved["schema_version"], 2)
        self.assertEqual(saved["auth_md"]["claim_token"], "clm_" + "c" * 40)
        self.assertEqual(saved["auth_md"]["pre_claim_access_token"], "authmd_" + "a" * 64)
        self.assertEqual(saved["pulse"]["api_key"], "pulse_api_" + "k" * 48)
        self.assertEqual(saved["pulse"]["setup_token"], "pulse_setup_" + "s" * 64)
        self.assertEqual(stat.S_IMODE(os.stat(self.credentials).st_mode), 0o600)
        for secret in (
            saved["auth_md"]["claim_token"], saved["auth_md"]["identity_assertion"],
            saved["auth_md"]["pre_claim_access_token"], saved["pulse"]["api_key"], saved["pulse"]["setup_token"],
        ):
            self.assertNotIn(secret, stdout.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["auth_md"], "registered_anonymous")
        self.assertEqual(output["scope"], "pulse:setup")
        paths = [request["path"] for request in SetupHandler.requests]
        self.assertEqual(paths[:4], [
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
            "/auth.md",
            "/agent/identity",
        ])
        setup_request = next(request for request in SetupHandler.requests if request["path"] == "/api/v1/pulse/setups")
        self.assertEqual(setup_request["headers"]["Authorization"], "Bearer authmd_" + "a" * 64)

    def test_verify_then_claim_handoff_and_poll_upgrade_one_registration(self):
        self.assertEqual(self.start()[0], 0)
        verify_stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "verify", "--credentials", str(self.credentials),
        ], stdout=verify_stdout, stderr=io.StringIO()), 0)
        verified = json.loads(verify_stdout.getvalue())
        self.assertEqual(verified["status"], "verified")
        self.assertNotIn("claim_url", verified)
        self.assertIn("run claim", verified["next"])

        claim_stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "claim", "--credentials", str(self.credentials), "--email", "Owner@Example.com",
        ], stdout=claim_stdout, stderr=io.StringIO()), 0)
        handoff = json.loads(claim_stdout.getvalue())
        self.assertEqual(handoff["status"], "authorization_pending")
        self.assertEqual(handoff["email"], "owner@example.com")
        self.assertEqual(handoff["user_code"], "123456")
        self.assertEqual(handoff["verification_uri"], self.server.base_url + "/agent/identity/claim/cat_secret")
        self.assertNotIn("clm_", claim_stdout.getvalue())

        SetupHandler.mode = "pending_claim"
        pending_stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "claim-status", "--credentials", str(self.credentials),
        ], stdout=pending_stdout, stderr=io.StringIO()), 0)
        self.assertEqual(json.loads(pending_stdout.getvalue())["retry_after"], 5)

        SetupHandler.mode = "ok"
        claimed_stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "claim-status", "--credentials", str(self.credentials),
        ], stdout=claimed_stdout, stderr=io.StringIO()), 0)
        claimed = json.loads(claimed_stdout.getvalue())
        self.assertEqual(claimed["status"], "claimed")
        saved = json.loads(self.credentials.read_text())
        self.assertIsNone(saved["auth_md"]["pre_claim_access_token"])
        self.assertEqual(saved["auth_md"]["post_claim_access_token"], "1|" + "p" * 64)
        self.assertNotIn(saved["auth_md"]["post_claim_access_token"], claimed_stdout.getvalue())

    def test_revoke_is_idempotent_and_removes_the_current_access_token_locally(self):
        self.test_verify_then_claim_handoff_and_poll_upgrade_one_registration()
        stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "revoke", "--credentials", str(self.credentials),
        ], stdout=stdout, stderr=io.StringIO()), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "revoked")
        self.assertIsNone(json.loads(self.credentials.read_text())["auth_md"]["post_claim_access_token"])
        second = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "revoke", "--credentials", str(self.credentials),
        ], stdout=second, stderr=io.StringIO()), 0)
        self.assertEqual(json.loads(second.getvalue())["status"], "already_revoked")

    def test_expired_claim_status_refreshes_the_same_ceremony_without_exposing_the_claim_token(self):
        self.assertEqual(self.start()[0], 0)
        self.assertEqual(pulse_setup.main([
            "verify", "--credentials", str(self.credentials),
        ], stdout=io.StringIO(), stderr=io.StringIO()), 0)
        self.assertEqual(pulse_setup.main([
            "claim", "--credentials", str(self.credentials), "--email", "owner@example.com",
        ], stdout=io.StringIO(), stderr=io.StringIO()), 0)

        SetupHandler.mode = "expired_claim"
        stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "claim-status", "--credentials", str(self.credentials),
        ], stdout=stdout, stderr=io.StringIO()), 0)
        refreshed = json.loads(stdout.getvalue())
        self.assertEqual(refreshed["status"], "authorization_pending")
        self.assertEqual(refreshed["email"], "owner@example.com")
        self.assertEqual(refreshed["user_code"], "123456")
        self.assertNotIn("clm_", stdout.getvalue())
        claim_requests = [request for request in SetupHandler.requests if request["path"] == "/agent/identity/claim"]
        self.assertEqual(len(claim_requests), 2)

    def test_origin_conflict_is_explicit_and_preserves_the_created_registration_for_revoke(self):
        SetupHandler.mode = "conflict"
        result, _stdout, stderr = self.start()
        self.assertEqual(result, 1)
        self.assertIn("origin_unavailable", stderr.getvalue())
        self.assertIn("Resume with the saved setup credentials", stderr.getvalue())
        self.assertIn(str(self.credentials.resolve()), stderr.getvalue())
        self.assertTrue(self.credentials.exists())
        saved = json.loads(self.credentials.read_text())
        self.assertEqual(saved["pulse"]["verification_status"], "not_created")
        self.assertEqual(saved["auth_md"]["registration_id"], "reg_01AUTHMD")
        self.assertNotIn(saved["auth_md"]["claim_token"], stderr.getvalue())

        show_stdout = io.StringIO()
        self.assertEqual(pulse_setup.main([
            "show", "--credentials", str(self.credentials),
        ], stdout=show_stdout, stderr=io.StringIO()), 0)
        redacted = json.loads(show_stdout.getvalue())
        self.assertEqual(redacted["pulse"]["verification_status"], "not_created")
        self.assertEqual(redacted["pulse"]["api_key"], "not_configured")
        self.assertEqual(redacted["pulse"]["setup_token"], "not_configured")

    def test_invalid_discovery_stops_before_registration_mutation(self):
        SetupHandler.mode = "bad_discovery"
        result, _stdout, stderr = self.start()
        self.assertEqual(result, 1)
        self.assertIn("issuer does not match", stderr.getvalue())
        self.assertNotIn("/agent/identity", [request["path"] for request in SetupHandler.requests])
        self.assertFalse(self.credentials.exists())

    def test_start_rejects_reserved_example_origin_before_network_or_state(self):
        for origin in ("https://example.com", "https://docs.your-company.invalid"):
            with self.subTest(origin=origin):
                stdout = io.StringIO()
                stderr = io.StringIO()
                result = pulse_setup.main([
                    "start", "--origin", origin, "--project-name", "Disposable demo",
                    "--platform-url", self.server.base_url, "--credentials", str(self.credentials),
                ], stdout=stdout, stderr=stderr)
                self.assertEqual(result, 1)
                self.assertIn("reserved example domain", stderr.getvalue())
                self.assertEqual(SetupHandler.requests, [])
                self.assertFalse(self.credentials.exists())


if __name__ == "__main__":
    unittest.main()
