import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_sdk_onboarding_audit.py"
SPEC = importlib.util.spec_from_file_location("run_sdk_onboarding_audit", SCRIPT)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class SdkOnboardingAuditRunnerTests(unittest.TestCase):
    def setUp(self):
        self.run_dir = audit.ROOT / ".tmp" / "sdk-onboarding-audit-unit"
        if self.run_dir.exists():
            shutil.rmtree(self.run_dir)
        self.run_dir.mkdir(parents=True)

    def tearDown(self):
        if self.run_dir.exists():
            shutil.rmtree(self.run_dir)

    def test_source_urls_dedupes_target_and_extra_urls(self):
        config = {
            "target": {
                "launch_url": "https://example.com/launch",
                "docs_urls": ["https://example.com/docs", "https://example.com/docs"],
                "repo_url": "https://github.com/example/sdk",
            },
            "source_urls": ["https://example.com/docs", "https://example.com/openapi.yaml"],
        }

        self.assertEqual(
            audit.source_urls(config),
            [
                "https://example.com/launch",
                "https://github.com/example/sdk",
                "https://example.com/docs",
                "https://example.com/openapi.yaml",
            ],
        )

    def test_execute_command_blocks_cwd_escape(self):
        with self.assertRaisesRegex(ValueError, "cwd must stay inside run_dir"):
            audit.execute_command(
                {
                    "id": "escape",
                    "cmd": [sys.executable, "--version"],
                    "cwd": "../outside",
                },
                self.run_dir,
                1,
            )

    def test_execute_command_records_logs_and_result(self):
        result = audit.execute_command(
            {
                "id": "print-ok",
                "cmd": [sys.executable, "-c", "print('ok')"],
                "cwd": "fresh-python",
            },
            self.run_dir,
            1,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["exit_code"], 0)
        stdout_path = audit.ROOT / result["stdout_path"]
        stderr_path = audit.ROOT / result["stderr_path"]
        self.assertEqual(stdout_path.read_text(encoding="utf-8").strip(), "ok")
        self.assertEqual(stderr_path.read_text(encoding="utf-8").strip(), "")

    def test_write_report_creates_expected_sections(self):
        result = {
            "passed": True,
            "cmd": [sys.executable, "--version"],
            "exit_code": 0,
            "stdout_path": ".tmp/out.txt",
            "stderr_path": ".tmp/err.txt",
        }
        audit.write_report(
            self.run_dir,
            {"target": {"name": "Example SDK", "repo_url": "https://github.com/example/sdk"}},
            [result],
            [{"url": "https://example.com/docs", "status": 200, "path": ".tmp/source.txt"}],
        )

        report = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("# SDK Onboarding Audit: Example SDK", report)
        self.assertIn("## Command Summary", report)
        self.assertIn("## Outreach Proof Snippet", report)
        self.assertIn("## PDF Notes", report)
        self.assertIn("## Full Version CTA", report)
        self.assertIn("https://forms.fillout.com/t/pZjfKK1ELmus", report)


if __name__ == "__main__":
    unittest.main()
