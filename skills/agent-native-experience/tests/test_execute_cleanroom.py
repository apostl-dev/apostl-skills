import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = SKILL_ROOT / "tests" / "fixtures" / "w3schools-clean-room"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "agent_native_execute_cleanroom", SKILL_ROOT / "scripts" / "execute_cleanroom.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExecuteCleanroomTest(unittest.TestCase):
    def setUp(self):
        self.execution = load_module()

    def test_pinned_w3schools_fixture_bundle_is_faithful_and_machine_verifiable(self):
        result = self.execution.validate_w3schools_fixture_bundle(FIXTURES)

        self.assertEqual("pass", result["status"])
        self.assertEqual("This is a heading", result["activation_observation"]["h1"])
        self.assertEqual("This is a paragraph.", result["activation_observation"]["paragraph"])
        self.assertTrue(result["browser_proof"]["snapshot_ref"].endswith(".json"))

    def test_static_fetch_or_filename_without_observation_never_passes_activation(self):
        trace = json.loads((FIXTURES / "clean-room-trace.pass.json").read_text())
        trace.pop("activation_observation")
        trace["browser_proof"] = {"screenshot_ref": "browser-proof.png"}

        result = self.execution.validate_cleanroom_trace(trace)

        self.assertEqual("not_run", result["status"])
        self.assertIn("activation observation", result["blocker"])

    def test_spoofed_trace_without_validated_local_browser_artifacts_never_passes(self):
        trace = json.loads((FIXTURES / "clean-room-trace.pass.json").read_text())
        trace["started_at"] = "not-a-time"
        trace["source_url"] = "https://example.invalid/"
        trace["activation_observation"] = {"h1": "Wrong heading", "paragraph": "Wrong paragraph"}
        trace["browser_proof"] = {"snapshot_ref": "fake.json", "snapshot_sha256": "a" * 64}
        trace["browser_commands"] = ["curl returned 200"]

        result = self.execution.validate_cleanroom_trace(trace)

        self.assertEqual("not_run", result["status"])
        self.assertNotEqual("pass", result["status"])
        self.assertTrue(result["missing"])

    def test_fixture_rejects_missing_or_mismatched_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory)
            for item in FIXTURES.iterdir():
                (copied / item.name).write_bytes(item.read_bytes())
            trace_path = copied / "clean-room-trace.pass.json"
            trace = json.loads(trace_path.read_text())
            trace["browser_proof"]["snapshot_sha256"] = "0" * 64
            trace_path.write_text(json.dumps(trace))

            result = self.execution.validate_w3schools_fixture_bundle(copied)

        self.assertEqual("blocked", result["status"])
        self.assertIn("hash", result["blocker"])

    def test_fixture_trace_or_dom_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory)
            for item in FIXTURES.iterdir():
                (copied / item.name).write_bytes(item.read_bytes())
            local_index = copied / "index.html"
            local_index.write_text(local_index.read_text().replace("This is a paragraph.", "Different paragraph."))

            result = self.execution.validate_w3schools_fixture_bundle(copied)

        self.assertEqual("blocked", result["status"])
        self.assertIn("local index", result["blocker"])

    def test_trace_cli_uses_adjacent_or_explicit_artifact_root_and_rejects_outside_root(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = self.execution.main(["--trace", str(FIXTURES / "clean-room-trace.pass.json")])
        self.assertEqual(0, status)
        self.assertEqual("pass", json.loads(stdout.getvalue())["status"])

        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = self.execution.main([
                    "--trace", str(FIXTURES / "clean-room-trace.pass.json"),
                    "--artifact-root", directory,
                ])
        self.assertEqual(1, status)
        self.assertIn("snapshot_artifact_hash", json.loads(stdout.getvalue())["missing"])

    def test_trace_rejects_secret_bearing_browser_or_environment_data(self):
        trace = json.loads((FIXTURES / "clean-room-trace.pass.json").read_text())
        trace["environment_identity"]["cookie"] = "private-cookie"

        with self.assertRaises(self.execution.SensitiveOutputError):
            self.execution.validate_cleanroom_trace(trace)

        trace = json.loads((FIXTURES / "clean-room-trace.pass.json").read_text())
        trace["browser_proof"]["raw_response_body"] = "private browser capture"
        with self.assertRaises(self.execution.SensitiveOutputError):
            self.execution.validate_cleanroom_trace(trace)


if __name__ == "__main__":
    unittest.main()
