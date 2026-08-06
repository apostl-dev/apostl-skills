# Apostl Agent API v1

Base: `https://platform.apostl.dev/api/v1`. Platform mode talks only to these
Apostl endpoints. GitHub is distribution only; it is not an authorization, run,
tracking, feedback, image, or runtime channel.

## P1 platform prerequisite

This local skill revision does not claim platform artifact parity or live E2E
proof. Those checks remain blocked until the platform-owned signed-out identity
envelope P1 is deployed and verified. Until then, do not construct runner-direct
or GitHub artifact URLs and do not treat a mock response, historical report,
health check, or HTTP 200 as live platform acceptance.

When P1 is available, `GET /agent/runs/{id}` returns the terminal run inside a
`{ "data": { ... } }` wrapper. Its `data` object must provide positive `id`,
the run's slug-like `public_id`, terminal `status`, and exactly these app-owned
URLs: `report_url`, `markdown_url`, `events_url`, `proof_manifest_url`, and
`pdf_url`. `report_slug` is not a terminal data field: derive it only from the
validated direct platform `report_url` path. The other public URLs must use
that same derived slug, never the run `public_id`.

The events body must carry matching `run_id`, `run_public_id`, `report_slug`,
`status`, `terminal: true`, and an `events` list. The proof-manifest body must
carry matching run identity and a nonempty nested `proof_manifest` object with
a nonempty `schema_version` and `proofs` list.

The local injected-fetch tests validate this frozen shape and reject
raw-Markdown HTML, truncated Markdown, empty or mismatched identity envelopes,
HTML missing any required heading/list/table/code-block structure, and PDFs
for which `pdftotext` produces no text. Those tests are contract
coverage, not P1 or live parity proof.

## Link authorization

- `POST /agent/authorizations` — create a short-lived consent transaction from
  `agent_name`, `skill_name`, `skill_version`, `device_name`, a UUID
  `client_instance_id`, `requested_scopes`, and the intended source/journey,
  activation, and run mode. It returns `device_code`, an Apostl
  `verification_uri_complete`, expiry, and minimum polling interval. Persist the
  pending secret with mode `0600`; print only the link and expiry.
- `POST /agent/authorizations/token` — poll with `device_code` only. Obey the
  server interval and `Retry-After`, bounded jitter/backoff, and an absolute
  deadline. Handle `authorization_pending`, `slow_down`, `approved`, `denied`,
  `expired`, `consumed`, and cancellation explicitly.
- A successful redemption returns the scoped API key exactly once plus
  non-secret client, identity, workspace, scope, and balance metadata. Write the
  key directly to `~/.config/apostl/credentials.json` with mode `0600`; never
  print it, put it in a URL, or ask the user to paste it.
- `POST /agent/registrations` and
  `POST /agent/registrations/{id}/activate` are deprecated browserless
  email-code fallback routes, not the default skill UX.

Request `agent:read`, `agent:deploy`, `agent:keys`, and `agent:feedback`.
Pending, denied, expired, cancelled, or consumed-without-handoff sessions create
no client-side credential and authorize no deploy/run/feedback mutation.

## Identity, runs, and keys

- `GET /agent/me`, `GET /agent/balance` — inspect tenant-safe identity, client,
  abilities, and available/reserved step metadata.
- `POST /agent/api-key/rotate`, `DELETE /agent/api-key` — rotate or revoke the
  current key without deleting the account.
- `POST /agent/deployments/preview` — validate the intended mutation without
  changing state. Its `logical_step_reservation` is the one-step up-front hold;
  `final_charge` explains that a successful terminal run captures measured
  execution steps, may exceed that hold, and never exceeds the available
  balance at capture.
- `GET|POST /agent/projects` and
  `POST /agent/projects/{id}/workflows` — idempotent Project and versioned
  Journey Check creation.
- `POST /agent/workflows/{id}/runs` — requires explicit confirmation and an
  `Idempotency-Key`; it reserves one logical step before execution. Never call
  that reservation the final charge: use the preview's `final_charge`
  disclosure before asking for confirmation.
- `GET /agent/runs/{id}` — poll terminal status and discover app-owned public
  HTML, Markdown, events, proof-manifest, and PDF URLs.

Project, workflow, and run commands require `--confirm` plus a stable
`--idempotency-key`. Polling is bounded. Never use an agent key on privileged
operator import/cancel routes.

## Feedback

- `GET|POST /agent/feedback` — list cursor-paginated feedback or append one
  structured event. List pages accept `limit` from 1 through 50 and an optional
  nonnegative integer `cursor`. Writes require the `agent:feedback` scope,
  `confirmed: true`, and an `Idempotency-Key`.
- Targets are `project`, `workflow`, `run`, `report`, or `recommendation` with a
  stable `target_public_id`. Kinds are `accepted_fix`, `rejected_fix`,
  `correction`, `free_form_note`, and `follow_up_request`.
- Optional `message` is at most 4,000 characters and `target_revision` at most
  120. Preview and redact locally. Never attach local files, diffs, transcripts,
  or diagnostics without a different payload-level contract and approval.

Treat machine-readable `error.code` and `error.recovery` as the retry contract.
Do not send secrets in metadata, expected activation, names, feedback, or any
report-visible field. The production runner image, registry, callbacks, and
runtime hosts remain inside the Apostl perimeter and are not client APIs.
