import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeFetcher:
    def __init__(self, collector, mapping, max_requests=20):
        self.collector = collector
        self.mapping = mapping
        self.budget = collector.RequestBudget(max_requests)
        self.calls = []

    def fetch(self, url, accept=None):
        self.budget.take()
        self.calls.append((url, accept))
        response = self.mapping.get((url, accept)) or self.mapping.get((url, None))
        if response:
            return response
        return self.collector.FetchResult(
            requested_url=url,
            final_url=url,
            status=404,
            headers={"content-type": "text/html"},
            body=b"not found",
            redirect_chain=[],
        )


class FakeSocket:
    def __init__(self, response_bytes):
        self.response_bytes = response_bytes
        self.connected_to = None
        self.sent = b""
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        self.connected_to = address

    def sendall(self, data):
        self.sent += data

    def makefile(self, *_args, **_kwargs):
        return io.BytesIO(self.response_bytes)

    def close(self):
        return None


class FakeTlsContext:
    def __init__(self):
        self.server_hostname = None

    def wrap_socket(self, sock, *, server_hostname):
        self.server_hostname = server_hostname
        return sock


class CollectEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.collector = load_module("agent_native_collect_evidence", "scripts/collect_evidence.py")
        self.rubric = json.loads((SKILL_ROOT / "references/rubric.v1.json").read_text())

    def response(self, url, status=200, content_type="text/html", body=b"", headers=None):
        return self.collector.FetchResult(
            requested_url=url,
            final_url=url,
            status=status,
            headers={"content-type": content_type, **(headers or {})},
            body=body,
            redirect_chain=[],
        )

    def test_public_url_validation_rejects_private_credentials_and_non_http_schemes(self):
        public_resolver = lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]

        self.assertEqual(
            "https://example.com/docs",
            self.collector.validate_public_url("https://example.com/docs", resolver=public_resolver),
        )
        self.assertEqual(
            "https://example.com:8443/docs",
            self.collector.validate_public_url("https://example.com:8443/docs", resolver=public_resolver),
        )
        for unsafe in (
            "file:///etc/passwd",
            "https://user:pass@example.com/docs",
            "http://127.0.0.1/docs",
            "http://localhost/docs",
            "http://169.254.169.254/latest/meta-data",
            "https://example.com/docs?api_key=do-not-fetch",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(self.collector.UnsafeTargetError):
                self.collector.validate_public_url(unsafe, resolver=public_resolver)

    def test_initial_url_rejects_every_query_and_never_echoes_credential_values(self):
        public_resolver = lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]
        unsafe_urls = (
            "https://example.com/docs?sig=secret-sig-value",
            "https://example.com/docs?signature=secret-signature-value",
            "https://example.com/docs?auth=secret-auth-value",
            "https://example.com/docs?authorization=secret-authorization-value",
            "https://example.com/docs?credential=secret-credential-value",
            "https://example.com/docs?X-Amz-Signature=secret-amz-value",
            "https://example.com/docs?ordinary=still-not-persisted",
            "https://example.com/docs?",
            "https://secret-user:secret-password@example.com/docs",
        )

        for unsafe in unsafe_urls:
            secret = unsafe.split("=", 1)[-1] if "=" in unsafe else "secret-password"
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(self.collector.UnsafeTargetError) as raised:
                    self.collector.validate_public_url(unsafe, resolver=public_resolver)
                self.assertNotIn(secret, str(raised.exception))

        artifact_secret = "initial-artifact-secret"
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "must-not-exist"
            with self.assertRaises(self.collector.UnsafeTargetError) as raised:
                self.collector.run_collection(
                    output_dir=output_dir,
                    target_url=f"https://example.com/docs?authorization={artifact_secret}",
                    journey_name="Read docs",
                    activation_event="Docs understood",
                    target_agent="new coding agent",
                    mode="sample",
                    max_pages=10,
                    fetcher=FakeFetcher(self.collector, {}),
                )
            self.assertNotIn(artifact_secret, str(raised.exception))
            self.assertFalse(output_dir.exists(), "blocked initial URLs must not create evidence artifacts")

    def test_redirect_with_query_secret_is_rejected_before_request_or_persistence(self):
        secret = "redirect-secret-value"
        response = (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: https://example.com/next?X-Amz-Signature=" + secret.encode() + b"\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        sockets = []

        def socket_factory(*_args):
            sock = FakeSocket(response)
            sockets.append(sock)
            return sock

        fetcher = self.collector.SafeFetcher(
            self.collector.CollectionLimits(max_requests=4),
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
            socket_factory=socket_factory,
            ssl_context_factory=FakeTlsContext,
        )

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "must-not-exist"
            with self.assertRaises(self.collector.UnsafeTargetError) as raised:
                self.collector.run_collection(
                    output_dir=output_dir,
                    target_url="https://example.com/start",
                    journey_name="Read docs",
                    activation_event="Docs understood",
                    target_agent="new coding agent",
                    mode="sample",
                    max_pages=10,
                    fetcher=fetcher,
                )
            self.assertFalse(output_dir.exists(), "blocked redirects must not create evidence artifacts")

        self.assertNotIn(secret, str(raised.exception))
        self.assertEqual(1, len(sockets), "unsafe redirect must not trigger another request")
        self.assertNotIn(secret.encode(), sockets[0].sent)

    def test_redirect_with_empty_query_marker_is_rejected_before_second_request(self):
        response = b"HTTP/1.1 302 Found\r\nLocation: /next?\r\nContent-Length: 0\r\n\r\n"
        sockets = []

        def socket_factory(*_args):
            sock = FakeSocket(response)
            sockets.append(sock)
            return sock

        fetcher = self.collector.SafeFetcher(
            self.collector.CollectionLimits(max_requests=4),
            resolver=lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
            socket_factory=socket_factory,
            ssl_context_factory=FakeTlsContext,
        )

        with self.assertRaises(self.collector.UnsafeTargetError):
            fetcher.fetch("https://example.com/start")
        self.assertEqual(1, len(sockets), "an empty query marker must be rejected before a second request")

    def test_https_connects_to_once_validated_public_ip_and_preserves_tls_hostname(self):
        resolver_calls = []

        def rebinding_resolver(*args, **kwargs):
            resolver_calls.append((args, kwargs))
            address = "93.184.216.34" if len(resolver_calls) == 1 else "127.0.0.1"
            return [(2, 1, 6, "", (address, 443))]

        fake_socket = FakeSocket(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
        )
        tls_context = FakeTlsContext()
        fetcher = self.collector.SafeFetcher(
            self.collector.CollectionLimits(max_requests=2),
            resolver=rebinding_resolver,
            socket_factory=lambda *_args: fake_socket,
            ssl_context_factory=lambda: tls_context,
        )

        result = fetcher.fetch("https://example.com/docs")

        self.assertEqual(200, result.status)
        self.assertEqual(1, len(resolver_calls), "the connect path must not resolve the hostname again")
        self.assertEqual(("93.184.216.34", 443), fake_socket.connected_to)
        self.assertEqual("example.com", tls_context.server_hostname)
        self.assertIn(b"Host: example.com\r\n", fake_socket.sent)
        self.assertEqual("93.184.216.34", result.connected_ip)

    def test_discovered_query_and_userinfo_links_are_never_persisted(self):
        links = self.collector._absolute_links(
            "https://example.com/docs/",
            [
                "/docs/safe",
                "/docs/private?authorization=do-not-store-this",
                "/docs/empty?",
                "https://user:password@example.com/docs/private",
            ],
        )

        self.assertEqual(["https://example.com/docs/safe"], links)
        self.assertNotIn("do-not-store-this", json.dumps(links))
        self.assertNotIn("password", json.dumps(links))

    def test_request_budget_is_hard_bounded(self):
        budget = self.collector.RequestBudget(2)
        budget.take()
        budget.take()
        with self.assertRaises(self.collector.CollectionLimitError):
            budget.take()

    def test_collector_outputs_every_docs_check_and_normalized_report_inputs_without_afdocs(self):
        target = "https://example.com/docs/intro"
        html = b"""<!doctype html><html><head><title>Intro</title></head><body>
        <h1>HTML Introduction</h1><p>Learn HTML by rendering this example.</p>
        <pre>&lt;h1&gt;Hello&lt;/h1&gt;</pre></body></html>"""
        mapping = {
            (target, None): self.response(target, body=html, headers={"cache-control": "max-age=300"}),
            (target, "text/markdown"): self.response(target, body=html, headers={"cache-control": "max-age=300"}),
            ("https://example.com/robots.txt", None): self.response(
                "https://example.com/robots.txt", content_type="text/plain", body=b"User-agent: *\nAllow: /\n"
            ),
        }
        fetcher = FakeFetcher(self.collector, mapping)

        evidence, raw = self.collector.collect_evidence(
            target_url=target,
            journey_name="Render the documented example",
            activation_event="Hello heading is visible",
            target_agent="new coding agent",
            mode="sample",
            max_pages=10,
            fetcher=fetcher,
            retrieved_at="2026-08-05T00:00:00Z",
        )

        docs_ids = {item["id"] for item in self.rubric["criteria"] if item["category"] == "Docs"}
        self.assertEqual(docs_ids, set(evidence["checks"]))
        self.assertEqual("fail", evidence["checks"]["llms-txt-exists"]["status"])
        self.assertEqual("fail", evidence["checks"]["markdown-url-support"]["status"])
        self.assertEqual("fail", evidence["checks"]["content-negotiation"]["status"])
        self.assertEqual("pass", evidence["checks"]["rendering-strategy"]["status"])
        self.assertEqual("not_run", evidence["agent_journey"]["status"])
        self.assertEqual("not_run", evidence["human_journey"]["status"])
        self.assertEqual("agent-native-business-evidence.v1", evidence["business_evidence"]["version"])
        self.assertEqual({"market", "competitors", "buyers"}, set(evidence["business_evidence"]) - {"version"})
        self.assertTrue(all(not evidence["business_evidence"][kind] for kind in ("market", "competitors", "buyers")))
        self.assertEqual("sample", evidence["corpus"]["mode"])
        self.assertLessEqual(len(fetcher.calls), 12)
        self.assertEqual(len(fetcher.calls), len(raw["responses"]))
        self.assertTrue(all("body" not in item for item in raw["responses"]))
        self.assertEqual(20, raw["limits"]["max_requests"])
        self.assertEqual(10, raw["limits"]["max_pages"])

    def test_full_mode_overflow_downgrades_to_sample_and_never_claims_full_coverage(self):
        target = "https://example.com/docs/intro"
        sitemap = b"""<?xml version="1.0"?><urlset>
        <url><loc>https://example.com/docs/a</loc></url>
        <url><loc>https://example.com/docs/b</loc></url>
        <url><loc>https://example.com/docs/c</loc></url>
        </urlset>"""
        mapping = {
            (target, None): self.response(target, body=b"<html><body><h1>Intro</h1><p>Useful content here.</p></body></html>"),
            (target, "text/markdown"): self.response(target, body=b"<html><body><h1>Intro</h1></body></html>"),
            ("https://example.com/sitemap.xml", None): self.response(
                "https://example.com/sitemap.xml", content_type="application/xml", body=sitemap
            ),
        }
        fetcher = FakeFetcher(self.collector, mapping)

        evidence, _raw = self.collector.collect_evidence(
            target_url=target,
            journey_name="Read intro",
            activation_event="Intro is understood",
            target_agent="new coding agent",
            mode="full",
            max_pages=2,
            fetcher=fetcher,
            retrieved_at="2026-08-05T00:00:00Z",
        )

        self.assertEqual("sample", evidence["corpus"]["mode"])
        self.assertEqual("full", evidence["environment"]["requested_mode"])
        self.assertTrue(any("max-pages" in item for item in evidence["limitations"]))

    def test_cli_writes_raw_metadata_evidence_and_both_report_formats(self):
        target = "https://example.com/docs/intro"
        fetcher = FakeFetcher(self.collector, {
            (target, None): self.response(target, body=b"<html><body><h1>Intro</h1><p>Useful content.</p></body></html>"),
            (target, "text/markdown"): self.response(target, body=b"<html><body><h1>Intro</h1></body></html>"),
        })
        with tempfile.TemporaryDirectory() as directory:
            outputs = self.collector.run_collection(
                output_dir=Path(directory),
                target_url=target,
                journey_name="Read intro",
                activation_event="Intro is understood",
                target_agent="new coding agent",
                mode="sample",
                max_pages=10,
                fetcher=fetcher,
                retrieved_at="2026-08-05T00:00:00Z",
            )

            self.assertEqual(
                {"evidence", "raw", "report", "report_json"},
                set(outputs),
            )
            for path in outputs.values():
                self.assertTrue(path.is_file(), path)
            self.assertIn("Source/corpus coverage", outputs["report"].read_text())
            raw = json.loads(outputs["raw"].read_text())
            self.assertTrue(all("body" not in response for response in raw["responses"]))


if __name__ == "__main__":
    unittest.main()
