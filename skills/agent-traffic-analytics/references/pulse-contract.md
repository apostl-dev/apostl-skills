# Apostl Pulse contract

Use this reference when implementing or reviewing an Apostl Pulse integration.
The hosted platform owns classification, retention configuration, claims, and
dashboards. The open-source SDK owns bounded server-side request collection and
delivery.

## Event boundary

Schema version 2 events contain:

- a random event ID and UTC occurrence time;
- an hourly HMAC-derived session ID;
- request IP address and complete User-Agent;
- `page_url`, canonicalized as `origin + pathname`;
- `page_path`, equal to that URL's pathname;
- method, final status, duration, surface hints, and bounded classification
  fields.

The SDK must remove URL credentials, query strings, and fragments before an
event enters its queue. It must reject an event when the IP address,
User-Agent, or canonical page is missing. It never captures bodies, cookies,
authorization headers, or query parameters.

The default eligibility rule is:

- method is `GET` or `HEAD`;
- final response status is `2xx`, `3xx`, or `4xx`;
- page is public;
- page is not a common asset, health check, login/logout/register/password
  route, account/settings/admin/dashboard/projects route, or API path.

Public HTML, Markdown, `llms.txt`, text files, documentation URLs, and ordinary
public `404` pages are eligible. Application input cannot override this rule:
ingest recomputes eligibility from the method, status, and canonical path before
storing every schema-version-2 event.

## Identity and interpretation

The API key is the HTTPS bearer credential and the server-only HMAC key. The
SDK derives a rotating hourly session identifier from environment, IP address,
and User-Agent. It does not transmit the API key in the event payload. No
separate identity secret or service type belongs in application configuration.

The dashboard estimates unique agents from classified sessions. This is a
heuristic segmentation of requests; it does not and cannot prove a unique
human, autonomous agent, model, company, or paying customer. Top Pages uses a
30-day window and ranks canonical pages by estimated agents, with request count
shown alongside it.

## Auth.md registration and agent-first setup API

The canonical instructions are `https://apostl.dev/auth.md`. The platform hosts
Protected Resource Metadata at
`/.well-known/oauth-protected-resource`, Authorization Server Metadata at
`/.well-known/oauth-authorization-server`, and the advertised JWKS. Discover and
validate those documents before registration. The current supported identity
types are `anonymous` and `service_auth`; Pulse autonomous setup uses
`anonymous`.

Anonymous `POST /agent/identity` returns a service-signed identity assertion and
one-time claim token. Exchange the assertion at the advertised token endpoint
with `urn:ietf:params:oauth:grant-type:jwt-bearer` and the exact Agent API
resource. Before claim, the resulting short-lived Bearer credential must have
only `pulse:setup` scope. There is no refresh token.

Create the linked unclaimed setup with that pre-claim credential:

```http
POST https://platform.apostl.dev/api/v1/pulse/setups
Content-Type: application/json
Authorization: Bearer <authmd_pre_claim_access_token>

{
  "origin": "https://replace-me.invalid",
  "verification_path": "/llms.txt",
  "project_name": "Example docs",
  "environment": "production",
  "agent_name": "Codex"
}
```

`replace-me.invalid` is an intentionally rejected placeholder. Before sending
the request, replace it with an authorized public HTTPS origin where the Pulse
server middleware can be deployed. Apostl rejects reserved documentation
domains such as `example.com`, `.example`, `.invalid`, and `.test` before
issuing credentials.

The response returns the API key, ingest endpoint, opaque setup token, verify
URL, public verification URL, and expiry once. The registration response also
contains the claim token and assertion. Store every credential locally with
owner-only `0600` permissions and never print them. The setup and registration
expire after seven days if not claimed. An origin already owned or reserved
returns HTTP `409` with `error.code = origin_unavailable`; no second project is
created. Error responses also include a human-readable `resolution` action.

## Verification and claim

The verifier sends a random challenge in `X-Apostl-Pulse-Challenge` to the exact
public verification URL. The server SDK responds with:

- `X-Apostl-Pulse-Page`: the canonical verification page URL;
- `X-Apostl-Pulse-Proof`: `v1:` plus the hex HMAC-SHA256 of
  `pulse-verify-v1`, the challenge, and canonical page URL, newline-separated,
  keyed by the API key.

The same request must produce a real accepted event with the verifier
User-Agent, a present IP address, the exact page URL, and `eligible = true`.
Verification requires both the signed public response and resulting real event.

Poll the returned verify URL with `Authorization: Bearer <setup_token>`. Before
the event arrives it returns `waiting_for_event`; afterward it returns
`verified`. Then use the Auth.md claim endpoint with the stored claim token and
the owner's intended Apostl email. Show the returned six-digit user code and
verification URI only to that owner. Claim requires the same verified email via
Google, GitHub, or an email magic link.

Poll the token endpoint no faster than the advertised interval using
`urn:workos:agent-auth:grant-type:claim`. Honor `authorization_pending`,
`slow_down`, and `Retry-After`. Successful claim revokes pre-claim access,
creates the post-claim Agent API credential, and moves every linked verified
Pulse installation into the same owner workspace. The ingest key remains active
after claim; claiming does not rotate it. OAuth revocation is idempotent.

## Operational limits

- Node.js 20 or newer.
- Up to 50 events and 256 KiB per batch.
- Up to 16 KiB per event and 500 queued events.
- One-second delivery timeout.
- At most three delivery attempts, only for HTTP `429` and `5xx`.
- No persistent local event queue and no request-path delivery wait.

Treat IP address and User-Agent collection as personal-data processing where
applicable. The site owner is responsible for notice, legal basis, access
controls, and the retention policy configured in analytics.
