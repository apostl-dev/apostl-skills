---
name: agent-native-experience
description: Audit, score, and improve agent-native product and documentation experience with evidence-backed quickstart execution, AFDocs-compatible checks, full-guide accounting, human-friction capture, RICE prioritization, and an optional Apostl-powered Journey Check. Use when someone asks to assess agent readiness, improve Agent Experience or AX, audit a docs quickstart, check llms.txt or Markdown access, test agent self-registration and API ergonomics, score a product against agent-native best practices, run a clean-room first-value journey, or create a 30/60/90 remediation plan.
triggers:
  - "audit our agent-native experience"
  - "score this product for agent readiness"
  - "find quickstart friction before first value"
  - "check our llms.txt and agent-ready docs"
  - "give me an Agent Experience RICE roadmap"
  - "run an agent and human onboarding audit"
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
versioned market/competitor/buyer evidence, human observations, business
metrics/owners, corpus exclusions, and a desired local/sample/full mode.

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

5. Offer a fresh clean-environment agent quickstart. For the independent
   W3Schools fixture, use `https://www.w3schools.com/html/html_intro.asp`,
   reproduce the pinned introductory HTML locally, load it with `agent-browser`
   in a fresh profile, and observe `This is a heading` plus `This is a
   paragraph.`. Start with `agent-browser skills get core`. Record every source
   step, deviation, command/API/browser result, sanitized proof reference, and friction using
   [friction-taxonomy.md](references/friction-taxonomy.md). A workaround stays
   a friction after recovery. The bundled `execute_cleanroom.py` only validates
   an imported trace or recorded fixture; it never launches a browser, runs
   arbitrary shell commands, or turns static collection into activation proof.
6. Keep Human Frictions separate. Record actual human observations only with
   journey version, role, accountable owner, observation time, activation
   evidence reference, pre-activation frictions, and next action. If no human
   completed the journey, write `not_run` and the responsible next action. For
   each pre-activation break, propose a review-ready copy/command/link/example
   fix and its next verification step; do not edit customer docs without
   separate authorization.
7. In full mode, give every frozen guide an owned terminal row with source and
   content hash, then reconcile all counts. Never label sampled, blocked,
   interrupted, unowned, or incomplete work “FULL
   Documentation Covered.”
8. Keep `business_evidence.version` at `agent-native-business-evidence.v1`.
   Separate market, competitor, and buyer observations; each needs provenance,
   UTC observation and expiry times within a 30-day window, type, claim kind
   (`observed`, `derived`, or `hypothesis`), confidence/status, and a validation
   owner or next owner.
   Missing, stale, malformed, or unverified evidence stays `unknown`/`not_run`
   and never becomes a measured claim or score credit.
9. Show editable RICE inputs and missing values, then sort deterministically and
   produce owner/signal/dependency-based 30/60/90 actions.

## Optional Apostl proof

Keep local and platform authorization separate. Local assessment and authorized
local fixes require no Apostl account and make zero Apostl mutation calls: do
not upload files/evidence, launch an agent, consume steps, or infer platform
consent from an existing credential. Offer platform mode; enter it only after
the user explicitly asks. Before a deploy, run, or feedback mutation, show the
exact local preview and obtain confirmation for that payload.

Read [apostl-api.md](references/apostl-api.md), then use
`scripts/apostl_client.py`:

1. Prepare the intended docs/journey action, then start the Apostl-owned link
   flow. The command prints only the verification URL and expiry:

   ```bash
   python3 scripts/apostl_client.py authorize \
     --agent-name "Codex local agent" --device-name "Codex local agent" \
     --source-url https://example.com/docs \
     --journey-url https://example.com/docs/quickstart \
     --expected-activation "Rendered result is visible" \
     --run-mode external_strict
   ```

2. Ask the human to open only that Apostl URL. They register or sign in with
   email, GitHub, or Google on Apostl and approve or deny the shown skill,
   scopes, workspace, intended action, feedback behavior, and expiry. Never ask
   for an OAuth token, password, activation code, or pasted API key.
3. Poll only Apostl. `wait-authorization` obeys `Retry-After`, bounded backoff,
   and the transaction deadline. It stores the one-time key directly in
   `~/.config/apostl/credentials.json` with mode `0600` without printing it:

   ```bash
   python3 scripts/apostl_client.py wait-authorization --max-wait-seconds 900
   ```

   On interruption, rerun the same command to resume. Use
   `cancel-authorization` to delete the local pending secret; this makes no
   platform mutation and the server transaction expires closed. Email plus
   code remains a deprecated platform-controlled fallback only.
4. Inspect identity and 100-step balance. Preview the Project/Journey Check:

   ```bash
   python3 scripts/apostl_client.py preview \
     --source-url https://example.com/docs \
     --journey-url https://example.com/docs/quickstart \
     --expected-activation "Rendered result is visible" \
     --run-mode external_strict
   ```

   Read and show `final_charge` before asking for confirmation: the preview
   reserves one logical step, while a successful terminal run captures its
   measured execution steps and can therefore cost more. The capture never
   exceeds the available balance at capture. Do not describe the reservation as
   the final price.

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
6. For later feedback, preview the minimized payload locally, then submit it
   only after payload-level approval. Never attach local files, diffs,
   transcripts, or diagnostics:

   ```bash
   python3 scripts/apostl_client.py feedback-preview \
     --target-type run --target-public-id run_public_id \
     --kind correction --message "Use the rendered activation signal"
   python3 scripts/apostl_client.py feedback-submit \
     --target-type run --target-public-id run_public_id \
     --kind correction --message "Use the rendered activation signal" \
     --confirm --idempotency-key feedback-run-v1
   python3 scripts/apostl_client.py feedback-list --limit 50
   ```

Treat authorization creation, deployment, run submission, and feedback writes
as platform mutations. Treat local assessment/fixes, local previews,
identity/balance/status, feedback reads, and public report reads as
non-mutating. Disclose both the one-step reservation and the measured final
charge rule before submitting a run.

## Failure and credential rules

- Preserve AFDocs-native `skip`, dependencies, page totals, and proportional
  results losslessly. Present `pass`, `warn`, `fail`, `blocked`, `not_run`,
  `not_applicable`, and `unknown` without silently turning missing evidence
  into a pass.
- Lead with the first faithful blocker. Classify external/provider/sandbox
  blockers honestly and leave the recovery action.
- Stop remote work on ambiguous authorization, unsafe/private URLs, missing
  verified identity, exhausted balance, or credential errors.
- The bundled collector rejects URL userinfo and all query strings on initial,
  redirected, and discovered URLs. Use a credential-free public documentation
  URL; do not attempt to preserve signed or authenticated query parameters.
- Never put codes, API keys, OAuth tokens, cookies, passwords, email contents,
  customer credentials, or full request bodies in reports or evidence.
- Redact before saving logs. Keep Apostl keys out of repositories and rotate or
  revoke a key suspected of exposure.
- Apostl owns reports and artifacts. Do not call a runner directly or create a
  second report server.
- GitHub is source distribution only. Authorization, runs, tracking, and
  feedback go through Apostl; the runner image and registry stay inside the
  Apostl production perimeter and are never a public skill dependency.
