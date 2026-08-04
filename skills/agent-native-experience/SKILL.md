---
name: agent-native-experience
description: Audit, score, and improve agent-native product and documentation experience with evidence-backed quickstart execution, AFDocs-compatible checks, full-guide accounting, human-friction capture, RICE prioritization, and an optional Apostl-powered Journey Check. Use when someone asks to assess agent readiness, improve Agent Experience or AX, audit a docs quickstart, check llms.txt or Markdown access, test agent self-registration and API ergonomics, score a product against agent-native best practices, run a clean-room first-value journey, or create a 30/60/90 remediation plan.
---

# Agent Native Experience

Turn one product/docs prompt into an honest local assessment and, only with
explicit approval, an Apostl execution proof.

## Contract

Require:

- target docs or product URL;
- selected quickstart or journey;
- observable activation event promised by that journey.

Accept optionally: product API/OpenAPI, repository path, `llms.txt` sources,
human observations, business metrics/owners, corpus exclusions, and a desired
local/sample/full mode.

Return one report using [report-contract.md](references/report-contract.md).
Always distinguish static evidence, agent runtime evidence, human evidence, and
unknown/not-run work. Never turn a fetch, signup, HTTP 200, workaround, or high
score into activation proof.

## Run the workflow

1. State the journey, target agent/user, activation event, environment, mode,
   and plausible business consequence. Label unmeasured impact as a hypothesis
   with the metric and owner needed to validate it.
2. Read [rubric.v1.json](references/rubric.v1.json) and
   [sources.v1.json](references/sources.v1.json). Refresh drift-prone sources
   before calling guidance current; record URL, retrieval time, and version or
   commit.
3. Inventory `llms.txt`, `llms-full.txt`, sitemaps, navigation, API specs, and
   supplied sources. Canonicalize URLs, record redirects/auth/exclusions and
   content hashes, then freeze the corpus before full execution.
4. Run local non-mutating checks. Use AFDocs directly when available and retain
   its status/dependency semantics. When AFDocs is unavailable, read
   [local-evidence-collector.md](references/local-evidence-collector.md) and run
   the bundled bounded collector:

   ```bash
   python3 scripts/collect_evidence.py \
     --url https://example.com/docs/quickstart \
     --journey "Install and run the quickstart" \
     --activation-event "Rendered result is visible" \
     --mode sample \
     --output-dir ./agent-native-evidence
   ```

   It writes safe response metadata, normalized evidence, Markdown, and JSON
   without an account or third-party Python package. It never executes or
   infers activation: `agent_journey` and `human_journey` remain `not_run` until
   real evidence is added. Feed normalized or subsequently enriched evidence
   to:

   ```bash
   python3 scripts/audit.py --evidence evidence.json --output report.md --json-output report.json
   ```

5. Offer a fresh clean-environment agent quickstart. Follow the documented path
   faithfully through the observable activation event. Record every source
   step, deviation, command/API/browser result, and friction using
   [friction-taxonomy.md](references/friction-taxonomy.md). A workaround stays
   a friction after recovery.
6. Keep Human Frictions separate. Record actual human observations only. If no
   human completed the journey, write `not_run` and the exact next action. For
   each pre-activation break, propose a review-ready copy/command/link/example
   fix and its next verification step; do not edit customer docs without
   separate authorization.
7. In full mode, give every frozen guide a terminal row and reconcile all
   counts. Never label sampled, interrupted, or incomplete work “FULL
   Documentation Covered.”
8. Show editable RICE inputs and missing values, then sort deterministically and
   produce owner/signal/dependency-based 30/60/90 actions.

## Optional Apostl proof

Local assessment requires no account. Before any remote mutation, show the
exact preview, one-step reservation, URLs, expected activation, run mode, and
idempotency keys; obtain explicit user confirmation.

Read [apostl-api.md](references/apostl-api.md), then use
`scripts/apostl_client.py`:

1. Ask for the exact human-supplied email and agent name.
2. Request registration. Pause and ask only for the six-digit code the human
   received. Never ask for a password.
3. Activate once. Store the one-time key at
   `~/.config/apostl/credentials.json` with mode `0600`; never print it.
4. Inspect identity and balance. Preview the Project/Journey Check mutation:

   ```bash
   python3 scripts/apostl_client.py preview \
     --source-url https://example.com/docs \
     --journey-url https://example.com/docs/quickstart \
     --expected-activation "Rendered result is visible" \
     --run-mode external_strict
   ```

5. After explicit confirmation, deploy idempotently, start the run, and poll
   within a declared bound. Mutating commands refuse to run without both
   `--confirm` and a stable `--idempotency-key`:

   ```bash
   python3 scripts/apostl_client.py project --source-url https://example.com/docs \
     --confirm --idempotency-key project-example-v1
   python3 scripts/apostl_client.py workflow --project-id 123 \
     --journey-url https://example.com/docs/quickstart \
     --expected-activation "Rendered result is visible" --run-mode external_strict \
     --confirm --idempotency-key workflow-example-v1
   python3 scripts/apostl_client.py run --workflow-id 456 \
     --confirm --idempotency-key run-example-v1
   python3 scripts/apostl_client.py poll --run-id 789 \
     --interval-seconds 5 --max-attempts 120
   ```

   Return only the app-owned public report URLs from the terminal run response.

Treat registration, deployment, and run submission as mutating. Treat local
assessment, preview, identity/balance/status, and public report reads as
non-mutating. Disclose step consumption before submitting a run.

## Failure and credential rules

- Preserve AFDocs-native `skip`, dependencies, page totals, and proportional
  results losslessly. Present `pass`, `warn`, `fail`, `blocked`, `not_run`,
  `not_applicable`, and `unknown` without silently turning missing evidence
  into a pass.
- Lead with the first faithful blocker. Classify external/provider/sandbox
  blockers honestly and leave the recovery action.
- Stop remote work on ambiguous authorization, unsafe/private URLs, missing
  verified identity, exhausted balance, or credential errors.
- Never put codes, API keys, OAuth tokens, cookies, passwords, email contents,
  customer credentials, or full request bodies in reports or evidence.
- Redact before saving logs. Keep Apostl keys out of repositories and rotate or
  revoke a key suspected of exposure.
- Apostl owns reports and artifacts. Do not call a runner directly or create a
  second report server.
