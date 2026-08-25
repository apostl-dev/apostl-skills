# Apostl Skills

[![skills.sh](https://skills.sh/b/apostl-dev/apostl-skills)](https://skills.sh/apostl-dev/apostl-skills)

<p align="center">
  <img src="assets/sdk-onboarding-audit.svg" alt="Apostl SDK Onboarding Audit" width="100%" />
</p>

Find broken SDK quickstarts before they leak developer activation.

Apostl skills run release-readiness checks locally with clean environments, exact commands, stdout/stderr, source snapshots, and reports for DevRel, SDK, product, or partner engineering teams.

Start free: run the documented path from a clean workspace and turn command-level proof into an activation-risk report.

## Install

List available skills:

```bash
npx skills add apostl-dev/apostl-skills --list
```

Install the SDK onboarding audit skill:

```bash
npx skills add apostl-dev/apostl-skills --skill sdk-onboarding-audit -g -y
```

Then ask your agent:

```text
Run a clean-env onboarding audit for this SDK launch. Test the documented quickstart first and give me command-level findings.
```

## Available Skills

### [agent-traffic-analytics](skills/agent-traffic-analytics)

Server-side analytics for one concrete question: how many estimated AI agents
use your public product, and which pages do they visit?

Install it from this monorepo:

```bash
npx skills add apostl-dev/apostl-skills --skill agent-traffic-analytics -g -y
```

Then ask your agent:

```text
Use $agent-traffic-analytics to instrument https://docs.example.com and verify
a real visit to /llms.txt before giving me the one-time claim link.
```

Before account creation, the skill can create a seven-day setup, keep its API key and setup token in an owner-only local file, and install the server SDK without a service type or browser fingerprinting. Verification requires a signed public response plus an eligible event with IP address, User-Agent, and canonical `origin + pathname`. The owner then claims via Google, GitHub, or an email magic link.

Pulse counts public `GET` and `HEAD` responses from `2xx` through `4xx`, excluding assets, health/auth/private routes, and mutations by default. Agent counts are heuristic estimates, not proof of a unique agent, model, company, or person. Because Pulse collects IP addresses and User-Agent strings, the owner must set an appropriate notice and retention policy.

### [agent-native-experience](skills/agent-native-experience)

An evidence-backed audit of how well a product and its docs work for agents through an observable first-value event. It combines AFDocs-compatible checks, product/API criteria, a clean-room agent journey, separate human evidence, full-corpus accounting, and editable RICE priorities.

Install it from this monorepo:

```bash
npx skills add apostl-dev/apostl-skills --skill agent-native-experience -g -y
```

Then ask your agent:

```text
Use $agent-native-experience to audit this product's documented quickstart,
identify the first faithful blocker, and give me a 30/60/90 improvement plan.
```

Local mode needs no Apostl account or mutation calls. It produces deterministic Markdown and JSON and keeps missing evidence as `unknown` or `not_run`. File fixes need separate approval and do not authorize uploads, agent runs, steps, or feedback. Platform mode starts only when the user requests an Apostl authorization link.

The report includes:

- executive verdict, selected journey, activation event, and environment;
- weighted Docs/Product/Agent/Human score with rubric version;
- command-level agent friction and separately sourced human friction;
- frozen corpus counts, exclusions, source provenance, and limitations;
- review-ready fixes, visible RICE assumptions, and a 30/60/90 plan.

#### First audit in 60 seconds

1. Install the skill with the command above.
2. Provide the docs URL, documented journey, and observable activation event;
   a fetch or HTTP 200 does not count.
3. Run local/sample mode and review `report.md` and `report.json`; no Apostl
   account or customer credentials are required.

Run the self-contained bounded collector when AFDocs is unavailable:

```bash
python3 skills/agent-native-experience/scripts/collect_evidence.py \
  --url https://www.w3schools.com/html/html_intro.asp \
  --journey "Reproduce the introductory HTML example locally" \
  --activation-event "The documented heading and paragraph are visible" \
  --mode sample \
  --output-dir .tmp/agent-native-w3schools
```

The collector writes `raw-evidence.json`, `evidence.json`, `report.md`, and `report.json` with the Python standard library and GET-only checks. It rejects URL userinfo and queries, validates public DNS, connects to the validated IP while preserving the HTTP Host and HTTPS certificate hostname, disables environment proxies, and limits requests, redirects, response size, time, and pages. The same URL rules cover redirects and discovered links; raw bodies are not stored. Static collection does not prove activation: execute the journey, add its agent trace to `evidence.json`, and rerun `audit.py`.

#### W3Schools clean-room browser proof

The collector is not browser activation proof. For the independent fixture at `https://www.w3schools.com/html/html_intro.asp`, reproduce the pinned HTML in a fresh directory, then use `agent-browser` with a fresh profile to verify the rendered H1 `This is a heading` and paragraph `This is a paragraph.`. Start with `agent-browser skills get core`; record only clean-room identity, ordered actions/deviations, timestamps, observed text, and sanitized snapshot/screenshot references.

The checked-in fixture is a non-network validator:

```bash
python3 skills/agent-native-experience/scripts/execute_cleanroom.py \
  --w3schools-fixture-dir skills/agent-native-experience/tests/fixtures/w3schools-clean-room
```

It rejects source/local-index/trace/browser-DOM mismatches and static-only evidence; it does not open a browser, persist a profile, or run during installation.

Required inputs are the target URL, journey, activation event, and environment. Optional inputs include a repository or OpenAPI spec, frozen corpus, human observations, and business metrics. Business evidence uses `agent-native-business-evidence.v1`; each market, competitor, or buyer record needs provenance, UTC observation and expiry within 30 days, type, claim kind, confidence/status, and a validation owner or next owner. Missing, stale, malformed, or unverified records remain `unknown`/`not_run` and earn no credit. Outputs include the report, normalized checks, corpus counts and hashes, provenance, friction taxonomy, editable RICE assumptions, and the 30/60/90 plan.

The score is `40% Docs + 30% Product + 20% Agent Journey + 10% Human Journey`. Missing evidence scores zero, `not_applicable` is removed from the relevant denominator, and a nominal 100 is capped at 99 unless every required criterion and both journeys reach the declared activation event.

Example verdict:

```text
Status: blocked
Selected journey: Install the SDK and render the documented example
First faithful blocker: The package name in the quickstart does not resolve
Coverage: 12 eligible / 12 attempted / 1 failed / 0 not_run
Next action: Correct the install command, then rerun in a fresh directory
```

#### Optional Apostl-powered proof

Start platform mode with an Apostl-owned link:

```bash
python3 skills/agent-native-experience/scripts/apostl_client.py authorize \
  --agent-name "Codex local agent" --device-name "Codex local agent" \
  --source-url https://example.com/docs \
  --journey-url https://example.com/docs/quickstart \
  --expected-activation "Rendered result is visible" \
  --run-mode external_strict
python3 skills/agent-native-experience/scripts/apostl_client.py \
  wait-authorization --max-wait-seconds 900
```

`authorize` prints only an Apostl verification URL and expiry. The human signs in through email, GitHub, or Google, reviews the skill/device, scopes, workspace, journey, feedback behavior, and expiry, then approves or denies. `wait-authorization` talks only to Apostl, follows `Retry-After` and the hard deadline, and writes the one-time API key to `~/.config/apostl/credentials.json` with mode `0600` without printing it. Email plus code is deprecated fallback behavior.

Approval exposes identity, scope, workspace, and the existing exactly-once 100-step first-proof grant; it does not authorize a run. The skill still previews the Project/Journey Check, step impact, URLs, and idempotency keys, then asks for explicit confirmation before deploy/run. Apostl owns tracking and the public HTML, Markdown, events, proof manifest, and PDF URLs.

Feedback uses the same boundary: `feedback-preview` is local; `feedback-submit` requires `--confirm` and an idempotency key; `feedback-list` is a scoped read capped at 50 items with an optional nonnegative integer cursor. The client accepts only a small structured payload and never uploads local files, diffs, transcripts, or diagnostics.

GitHub is source distribution only. Authorization, runs, tracking, and feedback go through Apostl; the runner image and registry stay inside the production perimeter, so public GHCR is not a launch dependency.

Do not put customer secrets in target fields. Reports exclude codes, keys, tokens, cookies, email contents, and environment values. Unexecuted work stays visible; sampled runs cannot claim full coverage, workarounds remain friction, and provider or sandbox blockers are reported.

Human and full-corpus proof stay separate from static checks. A human pass needs an accountable owner, journey/version, observation time, activation reference, and next action. Full coverage requires every frozen eligible guide to have an owned terminal row with source and content hash; blocked, sampled, or unowned rows keep it false.

The open `skills` CLI supports this format in Codex and Claude Code; runtime behavior still depends on available shell/browser tools and network policy.

Test the package locally:

```bash
npm run test:agent-native
python3 /path/to/skill-creator/scripts/quick_validate.py skills/agent-native-experience
```

Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md); report sensitive issues through [SECURITY.md](SECURITY.md). See [Apostl](https://apostl.dev), the [platform](https://platform.apostl.dev), and the [Agent API contract](skills/agent-native-experience/references/apostl-api.md). This [example public report](https://platform.apostl.dev/reports/0d071cf7-e23c-4074-8a42-b46e748a8faa) includes signed-out HTML, Markdown, events, proof manifest, artifacts, and PDF.

### [sdk-onboarding-audit](skills/sdk-onboarding-audit)

A clean-room review for SDK releases, launch posts, partner onboarding, and docs quickstarts. It tests whether a fresh developer can discover, install, initialize, preview, authenticate, and understand the documented path without hidden local state, then reports activation risks from command logs and source snapshots.

What it checks:

- Docs command drift: documented commands, flags, or next steps that no longer exist.
- Preview promise drift: "free", "local", or "no key" paths that unexpectedly require auth, credits, or paid infra.
- Package-manager drift: npm/npx/bun/pnpm claims that fail in a clean workspace.
- Type/export drift: SDK packages that install but fail a minimal consumer import or typecheck.
- BYOK/config drift: docs that describe fields or keys the current source does not accept.
- Package hygiene drift: published packages that include local artifacts, generated agent files, or confusing demo leftovers.

Outputs:

- `.tmp/<run_id>/audit_manifest.json`
- `.tmp/<run_id>/source_snapshots.json`
- `.tmp/<run_id>/command_results.jsonl`
- `.tmp/<run_id>/logs/*`
- `.tmp/<run_id>/report.md`

After the report has useful evidence, it adds one restrained CTA:

```text
Want this running on every SDK/docs release? Send us the path to monitor: https://forms.fillout.com/t/pZjfKK1ELmus
```

Use the form for real blockers, ambiguous launch gates, or continuous checks. It creates an inbound Apostl Notion card with submitter, work email, SDK/docs URL, project or SDK family, role, notes, and lead source. No Fillout or Notion API keys are stored here.

## Run Locally

Create a minimal config:

```json
{
  "target": {
    "name": "Example SDK",
    "docs_urls": ["https://example.com/docs"],
    "repo_url": "https://github.com/example/sdk"
  },
  "commands": [
    {
      "id": "documented-help",
      "cmd": ["python3", "--version"],
      "cwd": "fresh-python"
    }
  ]
}
```

Run the evidence collector:

```bash
python3 skills/sdk-onboarding-audit/scripts/run_sdk_onboarding_audit.py \
  --run-id example-sdk \
  --config .tmp/example-sdk/audit_config.json \
  --execute
```

## Quality Gates

This repository is designed for both skills.sh installation and local skillify checks:

```bash
npm test
npm run skillify
npx skills add . --list
```

## Links

- [Apostl](https://apostl.dev)
- [Inbound form](https://forms.fillout.com/t/pZjfKK1ELmus)
- [skills.sh docs](https://www.skills.sh/docs)

## License

MIT
