# Apostl Agent API v1

Base: `https://platform.apostl.dev/api/v1`.

- `POST /agent/registrations` — send agent name and exact human email; returns
  a non-secret pending ID only.
- `POST /agent/registrations/{id}/activate` — send the human-provided code;
  returns a scoped key once.
- `GET /agent/me`, `GET /agent/balance` — inspect tenant-safe identity, key
  abilities, available/reserved steps, and grants.
- `POST /agent/api-key/rotate`, `DELETE /agent/api-key` — rotate or revoke the
  current key without deleting the account.
- `POST /agent/deployments/preview` — validate the intended mutation without
  changing state.
- `GET|POST /agent/projects` and
  `POST /agent/projects/{id}/workflows` — idempotent Project and versioned
  Journey Check creation.
- `POST /agent/workflows/{id}/runs` — requires explicit confirmation and an
  `Idempotency-Key`; reserves one logical step.
- `GET /agent/runs/{id}` — poll status and discover app-owned public HTML,
  Markdown, events, proof-manifest, and PDF URLs.

Use `agent:read`, `agent:deploy`, and `agent:keys` scopes. Never use an agent key
on operator import/cancel routes. Treat machine-readable `error.code` and
`error.recovery` as the retry contract. Do not send secrets in metadata,
expected activation, names, or report-visible fields.
