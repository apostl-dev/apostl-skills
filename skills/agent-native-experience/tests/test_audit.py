import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.audit = load_module("agent_native_audit", "scripts/audit.py")
        self.rubric = json.loads((SKILL_ROOT / "references/rubric.v1.json").read_text())

    def test_rubric_preserves_all_current_afdocs_checks_and_product_checks(self):
        afdocs_ids = {
            "llms-txt-exists", "llms-txt-valid", "llms-txt-size",
            "llms-txt-links-resolve", "llms-txt-links-markdown",
            "llms-txt-directive-html", "llms-txt-directive-md",
            "markdown-url-support", "content-negotiation", "rendering-strategy",
            "page-size-markdown", "page-size-html", "content-start-position",
            "tabbed-content-serialization", "section-header-quality",
            "markdown-code-fence-validity", "http-status-codes", "redirect-behavior",
            "llms-txt-coverage", "markdown-content-parity", "cache-header-hygiene",
            "auth-gate-detection", "auth-alternative-access",
        }
        criteria = {criterion["id"]: criterion for criterion in self.rubric["criteria"]}
        self.assertEqual(afdocs_ids, {key for key in criteria if key in afdocs_ids})
        self.assertEqual(23, len(afdocs_ids))
        for criterion in criteria.values():
            self.assertIn("source", criterion)
            self.assertGreater(criterion["weight"], 0)
            self.assertTrue(criterion["evidence_method"])
            self.assertTrue(criterion["fix_guidance"])
        for product_id in {
            "product-self-registration", "product-human-activation", "product-api-errors",
            "product-status-polling", "product-key-lifecycle", "product-identity-linking",
            "product-balance-visibility", "product-idempotent-deploy",
            "product-first-value", "product-human-fallback",
        }:
            self.assertIn(product_id, criteria)

    def test_missing_evidence_is_unknown_and_blocker_prevents_perfect_score(self):
        evidence = {
            "journey": {
                "name": "Install API client",
                "target": "new coding agent",
                "activation_event": "resource appears in status API",
            },
            "checks": {criterion["id"]: {"status": "pass", "evidence": "fixture"}
                       for criterion in self.rubric["criteria"]},
            "agent_journey": {"status": "blocked", "activation_reached": False,
                              "blocker": "Credential was required before the documented first value."},
            "human_journey": {"status": "not_run"},
            "corpus": {"mode": "sample", "rows": []},
            "frictions": [],
        }
        evidence["checks"].pop("llms-txt-exists")

        report = self.audit.build_report(self.rubric, evidence)

        self.assertEqual("unknown", report["results"]["llms-txt-exists"]["status"])
        self.assertLess(report["score"]["overall"], 100)
        self.assertEqual("blocked", report["executive_verdict"]["status"])
        self.assertIn("Credential was required", report["executive_verdict"]["blocker"])
        self.assertIn("Human Journey", report["score"]["categories"])

    def test_local_report_build_makes_zero_apostl_or_other_network_calls(self):
        evidence = {
            "journey": {"name": "Local docs review", "target": "coding agent",
                        "activation_event": "local result observed"},
            "checks": {},
            "agent_journey": {"status": "not_run", "activation_reached": False},
            "human_journey": {"status": "not_run"},
            "corpus": {"mode": "sample", "rows": []},
            "frictions": [],
        }
        with patch("urllib.request.urlopen", side_effect=AssertionError("local mode must not call a platform")) as network:
            report = self.audit.build_report(self.rubric, evidence)

        network.assert_not_called()
        self.assertEqual("not_run", report["agent_journey"]["status"])

    def test_full_corpus_accounting_is_honest_and_deterministic(self):
        rows = [
            {"url": "https://example.com/a", "status": "passed", "content_hash": "a" * 64},
            {"url": "https://example.com/b", "status": "not_run", "blocker": "provider quota", "content_hash": "b" * 64},
            {"url": "https://example.com/c", "status": "excluded", "reason": "duplicate", "content_hash": "c" * 64},
        ]
        first = self.audit.corpus_accounting("full", rows)
        second = self.audit.corpus_accounting("full", list(reversed(rows)))

        self.assertEqual(first, second)
        self.assertFalse(first["full_documentation_covered"])
        self.assertEqual({"discovered": 3, "eligible": 2, "attempted": 1, "passed": 1,
                          "failed": 0, "blocked": 0, "not_run": 1, "excluded": 1}, first["counts"])

    def test_corpus_is_canonicalized_deduplicated_and_retains_provenance(self):
        rows = [
            {"url": "HTTPS://EXAMPLE.COM:443/docs/#one", "status": "passed",
             "source": "sitemap", "content_hash": "a" * 64,
             "redirect_chain": ["https://example.com/old", "https://example.com/docs/"],
             "auth_gate": "none"},
            {"url": "https://example.com/docs#two", "status": "passed",
             "source": "llms.txt", "content_hash": "a" * 64,
             "exclusion_reason": None},
        ]

        corpus = self.audit.corpus_accounting("full", rows)

        self.assertEqual(1, corpus["counts"]["discovered"])
        row = corpus["rows"][0]
        self.assertEqual("https://example.com/docs", row["url"])
        self.assertEqual(["llms.txt", "sitemap"], row["sources"])
        self.assertEqual(2, len(row["original_urls"]))
        self.assertEqual("none", row["auth_gate"])
        self.assertEqual(2, len(row["redirect_chain"]))

    def test_afdocs_skip_dependencies_and_proportional_scoring_are_lossless(self):
        evidence = {
            "checks": {
                "llms-txt-exists": {"status": "fail", "evidence": "404"},
                "llms-txt-valid": {"status": "pass", "evidence": "not executable"},
                "rendering-strategy": {
                    "status": "warn", "proportion": 0.75,
                    "passed": 3, "total": 4, "evidence": "three of four pages",
                },
                "section-header-quality": {"status": "skip", "evidence": "upstream skipped"},
            },
            "agent_journey": {"status": "not_run", "activation_reached": False},
            "human_journey": {"status": "not_run"},
            "corpus": {"mode": "sample", "rows": []},
        }

        report = self.audit.build_report(self.rubric, evidence)

        dependent = report["results"]["llms-txt-valid"]
        self.assertEqual("skip", dependent["status"])
        self.assertEqual(["llms-txt-exists"], dependent["unmet_dependencies"])
        proportional = report["results"]["rendering-strategy"]
        self.assertEqual(0.75, proportional["proportion"])
        self.assertEqual(3, proportional["passed"])
        self.assertEqual(4, proportional["total"])
        self.assertEqual("skip", report["results"]["section-header-quality"]["status"])

        lower_evidence = json.loads(json.dumps(evidence))
        lower_evidence["checks"]["rendering-strategy"]["proportion"] = 0.25
        lower = self.audit.build_report(self.rubric, lower_evidence)
        self.assertGreater(report["score"]["categories"]["Docs"], lower["score"]["categories"]["Docs"])

    def test_human_modes_render_all_required_friction_fields_and_not_run(self):
        base = {
            "checks": {}, "agent_journey": {"status": "not_run", "activation_reached": False},
            "corpus": {"mode": "sample", "rows": []}, "frictions": [],
        }
        selected = self.audit.build_report(self.rubric, {**base, "human_journey": {
            "mode": "selected", "selected_guide": "Install guide", "status": "blocked",
            "frictions": [{"step": "Install", "observation": "Command fails", "severity": "high",
                           "evidence": "exit 1", "smallest_fix": "Correct the package name"}],
        }})
        markdown = self.audit.render_markdown(selected)
        self.assertIn("Mode: selected", markdown)
        self.assertIn("Selected guide: Install guide", markdown)
        self.assertIn("Severity: high", markdown)
        self.assertIn("Evidence: exit 1", markdown)

        primary = self.audit.build_report(self.rubric, {**base, "human_journey": {"status": "not_run"}})
        primary_markdown = self.audit.render_markdown(primary)
        self.assertIn("Mode: primary", primary_markdown)
        self.assertIn("Next action:", primary_markdown)

    def test_report_outputs_redact_secret_shaped_text_and_reject_secret_fields(self):
        evidence = {
            "checks": {}, "agent_journey": {"status": "not_run", "activation_reached": False},
            "human_journey": {"status": "not_run"}, "corpus": {"mode": "sample", "rows": []},
            "frictions": [{"id": "F-1", "evidence": "api_key=123|apostl_secret_value"}],
        }
        report = self.audit.build_report(self.rubric, evidence)
        rendered = self.audit.render_markdown(report)
        serialized = json.dumps(report)
        self.assertNotIn("apostl_secret_value", rendered)
        self.assertNotIn("apostl_secret_value", serialized)
        self.assertIn("[REDACTED]", rendered)

        evidence["frictions"][0]["api_key"] = "123|apostl_secret_value"
        with self.assertRaises(self.audit.SensitiveOutputError):
            self.audit.build_report(self.rubric, evidence)

    def test_sanitizer_rejects_opaque_secret_field_variants_and_redacts_them_in_lenient_mode(self):
        canaries = {
            "client_secret": "opaque-client-value",
            "refresh_token": "opaque-refresh-value",
            "CUSTOM_ENV": "opaque-env-value",
            "private_key_material": "opaque-key-value",
            "recovery_code": "opaque-code-value",
            "session_cookie_value": "opaque-cookie-value",
            "nested": {"database_password_value": "opaque-password-value"},
        }

        with self.assertRaises(self.audit.SensitiveOutputError):
            self.audit.sanitize_data(canaries)

        sanitized = self.audit.sanitize_data(canaries, reject_keys=False)
        serialized = json.dumps(sanitized)
        for canary in [
            "opaque-client-value", "opaque-refresh-value", "opaque-env-value",
            "opaque-key-value", "opaque-code-value", "opaque-cookie-value",
            "opaque-password-value",
        ]:
            self.assertNotIn(canary, serialized)

    def test_report_contains_decision_ready_sections_and_visible_rice_assumptions(self):
        evidence = {
            "journey": {"name": "Quickstart", "target": "agent", "activation_event": "hello rendered"},
            "checks": {},
            "agent_journey": {"status": "not_run", "activation_reached": False},
            "human_journey": {"status": "not_run"},
            "corpus": {"mode": "sample", "rows": []},
            "frictions": [{
                "id": "F-1", "title": "Missing command", "severity": "high",
                "step": "Install", "observation": "No executable command", "evidence": "docs snapshot",
                "smallest_fix": "Add npm install example", "business_consequence": "Slower activation",
                "impact_type": "hypothesis", "metric": "time_to_first_value", "metric_owner": "DevRel",
                "rice": {"reach": None, "impact": 2, "confidence": 0.8, "effort": 1},
            }],
        }
        report = self.audit.build_report(self.rubric, evidence)
        markdown = self.audit.render_markdown(report)

        for heading in ["Executive verdict", "Business impact", "Scope and environment",
                        "Agent-ready Docs", "Agent-ready Product", "Agent quickstart trace",
                        "Human Frictions", "Guide-by-guide coverage", "RICE roadmap",
                        "30 / 60 / 90 day plan", "Final action plan", "Provenance", "Limitations"]:
            self.assertIn(heading, markdown)
        self.assertIn("missing", markdown.lower())
        self.assertNotIn("$100,000", markdown)

    def test_report_sections_follow_the_published_contract_order(self):
        evidence = {
            "journey": {"name": "Quickstart", "target": "agent", "activation_event": "hello rendered"},
            "checks": {},
            "agent_journey": {"status": "not_run", "activation_reached": False},
            "human_journey": {"status": "not_run"},
            "corpus": {"mode": "sample", "rows": []},
            "frictions": [],
        }

        markdown = self.audit.render_markdown(self.audit.build_report(self.rubric, evidence))
        headings = [line.removeprefix("## ") for line in markdown.splitlines() if line.startswith("## ")]

        self.assertEqual([
            "Executive verdict",
            "Business impact",
            "Scope and environment",
            "Score and rubric version",
            "Source/corpus coverage",
            "Agent-ready Docs",
            "Agent-ready Product",
            "Agent quickstart trace",
            "Human Frictions",
            "Guide-by-guide coverage",
            "Deduplicated friction evidence",
            "Proposed fixes through activation",
            "RICE roadmap",
            "30 / 60 / 90 day plan",
            "Final action plan",
            "Recurring-check recommendations",
            "Provenance",
            "Limitations",
            "Public artifact links",
        ], headings)


if __name__ == "__main__":
    unittest.main()
