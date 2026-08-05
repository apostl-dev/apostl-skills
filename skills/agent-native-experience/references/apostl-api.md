# Apostl Agent API v1

Base: `https://platform.apostl.dev/api/v1`. Platform mode talks only to these
Apostl endpoints. GitHub is distribution only; it is not an authorization, run,
tracking, feedback, image, or runtime channel.

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
  changing state.
- `GET|POST /agent/projects` and
  `POST /agent/projects/{id}/workflows` — idempotent Project and versioned
  Journey Check creation.
- `POST /agent/workflows/{id}/runs` — requires explicit confirmation and an
  `Idempotency-Key`; reserves one logical step.
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
