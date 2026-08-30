---
name: agent-traffic-analytics
description: Route, install, and verify Apostl Pulse server-side analytics for public AI-agent traffic using the Cloudflare Worker or server SDK. Use when someone asks how many AI agents visit a website, docs, API, llms.txt, Markdown, or other public pages; wants per-page agent analytics; wants Pulse on Cloudflare, Express, Next.js, or another server; or wants an agent to self-register through Auth.md, finish setup, and hand the owner one account claim.
---

# Agent Traffic Analytics

Answer one question with inspectable server-side evidence: how many estimated
AI agents are using this public product right now, and which pages do they use?

## Contract

Pulse measures eligible public page requests. The selected server-side
collector sends the request IP address, full User-Agent, and canonical page
identity as `origin + pathname`. It strips query strings, fragments, and URL
credentials. It never sends request bodies, cookies, authorization headers, or
query parameters.

The server SDK counts public `GET` and `HEAD` responses with status `2xx`
through `4xx`. It excludes common static assets, health checks, auth/private
paths, and mutations by default. Apostl performs traffic classification in the
analytics layer; do not configure a service type in application code.

The dashboard's Top Pages view covers 30 days and shows estimated unique agents
plus request count for each canonical page. Classification and agent counts are
heuristic estimates; IP address plus User-Agent cannot prove a unique person,
agent, model, or organization. Read [pulse-contract.md](references/pulse-contract.md)
before changing collection, verification, identity, or claim behavior.

## Fit and payoff

Use Pulse for server-rendered SaaS sites, developer docs, agent-native products,
public API surfaces, Markdown, and `llms.txt`. The owner gets a live 30-minute
agent estimate, a 30-day page ranking, and inspectable proof that the deployed
middleware produced a real event. For an existing Express or Next.js server,
the code change is one client plus one middleware or handler wrapper; budget
about ten minutes for the code edit, then add whatever test, review, and deploy
time the target normally requires. Do not promise a live dashboard before the
public verification request and its event both pass.

Starting requires a public HTTPS origin, authority over its serving code and
secret runtime, and an authorized deploy path. The server SDK additionally
requires permission to install a package; the Cloudflare path requires authority
over the exact hostname and matching Worker route. A human account is not
required until claim; the owner then uses Google, GitHub, or an email magic link.

Reserved documentation domains such as `example.com`, `example.org`,
`example.net`, `.example`, `.invalid`, and `.test` cannot prove deploy control.
If the user supplied one, explain that boundary and obtain an authorized public
origin before creating a setup. Do not use a reserved domain as a disposable
production demo.

## Choose one collector

Read this canonical public skill source and its direct reference before editing
the target:

- `https://github.com/apostl-dev/apostl-skills/tree/main/skills/agent-traffic-analytics`
- [Pulse collection and proof contract](references/pulse-contract.md)

A global skill install is optional. Reading those public files is sufficient to
make the routing decision. Inspect the exact public hostname, its live response,
the target repository, and the operator's deployment controls before installing
anything. Then choose exactly one path:

- **Confirmed Cloudflare-proxied hostname:** use the MIT-licensed
  `https://github.com/apostl-dev/pulse-cloudflare-worker` when the Cloudflare
  control plane confirms that the exact record is proxied, or when a trusted
  live response carries independently established Cloudflare edge evidence such
  as `CF-Ray`. The operator must also be able to edit the matching Worker Route.
  A spoofable header alone is only a hint; prefer the control-plane state.
- **Non-Cloudflare server:** use
  `https://github.com/apostl-dev/pulse-sdk`. This includes a Cloudflare DNS-only
  record whose requests go directly to an ordinary controlled server. Cloudflare
  nameservers are not enough because individual records can be DNS-only.
- **Existing Cloudflare Worker or Pages application:** integrate the template's
  observation logic into that controlled edge runtime, or use an explicitly
  supported non-looping Worker Route. Do not place a second Worker in front
  blindly. Stop as blocked if source authority is missing.
- **Ambiguous or unreachable hostname:** stop with the one missing fact or
  permission. Unknown proxy state, missing route authority, missing source
  authority, or an unreachable target never authorizes guessing, creating a
  substitute hostname, or silently falling back to another collector.

Exactly one Pulse collector owns each request path. Never deploy both the Worker
and SDK on the same hostname or route unless the user explicitly authorizes a
measured migration and you can show deduplication proof. For an existing origin,
use a narrow Worker Route that forwards to the current origin; never replace it
with a Worker Custom Domain that can loop back to itself.

## Start through Auth.md without an account

An agent may register itself and create an unclaimed setup without waiting for a
human. This is a real Apostl API mutation that reserves the origin for seven
days, so do it only when the user has asked to set up or install Pulse for that
origin.

The helper must discover the live Auth.md contract before mutating state. It
reads Protected Resource Metadata and Authorization Server Metadata from
`platform.apostl.dev`, fetches the canonical `https://apostl.dev/auth.md`, and
requires `anonymous` registration plus Bearer header support. It then registers
an anonymous identity, exchanges Apostl's signed assertion for a short-lived
token whose only scope is `pulse:setup`, and uses that token to create the linked
Pulse setup. Stop before registration if issuer, endpoint origin, supported
method, resource, or the Auth.md H1 does not match discovery.

Run from this skill directory:

```bash
python3 scripts/pulse_setup.py start \
  --origin https://replace-me.invalid \
  --verification-path /llms.txt \
  --project-name "My public site" \
  --agent-name "Codex" \
  --device-name "Owner workstation"
```

Replace `replace-me.invalid` before running. The helper rejects it and other
reserved documentation domains before it contacts Apostl.

The command prints non-secret registration/setup metadata and the local
credentials path. It stores the identity assertion, claim token, Auth.md access
token, Pulse API key, and Pulse setup token in one owner-only `0600` file. Never
print, paste into chat, commit, or construct a URL from a raw secret. The only
capability URL to share is the Auth.md `verification_uri` returned later by the
`claim` command; it never contains the API key. If the origin is already owned
or reserved, stop and report the explicit `origin_unavailable` response; do not
create another project or use a variant hostname to bypass it.

## Install the Cloudflare Worker

For the confirmed Cloudflare branch, follow the public Worker repository rather
than recreating its code. Preserve the origin response and behavior. Store the
saved `api_key` as the Worker secret `APOSTL_PULSE_API_KEY` and the ingest URL as
`APOSTL_PULSE_ENDPOINT`; never put either value in source, `wrangler.toml`, logs,
chat, or a Custom Domain.

Attach the Worker only to the narrow existing-origin Worker Route that the user
authorized. The template must read raw `CF-Connecting-IP` and the bounded full
User-Agent, retain only canonical host and pathname plus bounded request facts,
and exclude query data, bodies, cookies, authorization, URL credentials, and
arbitrary headers. Treat the IP address and User-Agent as personal data and
complete a privacy review for notice, legal basis, access, and retention before
production use.

Keep telemetry delivery in `ctx.waitUntil()` and fail-open: observation or
delivery failure must never delay, replace, or fail the origin response. Do not
add a local User-Agent allowlist. Submit every representable request reaching
the Worker Route so future and unknown agents can be classified centrally by
Pulse while the platform applies canonical eligibility and privacy boundaries.

After deployment, require the signed challenge proof, a genuine request,
Cloudflare invocation proof for the exact route, and a positive Pulse-side delta.
An HTTP response, Worker deploy message, log line, synthetic request, or
unchanged dashboard is not activation proof.

## Install the server SDK

For the confirmed non-Cloudflare branch, inspect the target server and use its
existing package manager. Pulse must run on the server where the raw request IP
address and User-Agent are available. Do not add it to a browser bundle.

```bash
npm install @apostl-dev/pulse-sdk
```

Load the saved `api_key` into the target's secret manager as
`APOSTL_PULSE_API_KEY`; load `ingest_endpoint` as
`APOSTL_PULSE_ENDPOINT`. Do not ask the user to paste the key if the agent can
read the owner-only setup file and use the target's authorized secret tooling.
Do not add `service`, an identity secret, or client-side fingerprinting.

Create one client:

```ts
import { createPulse } from '@apostl-dev/pulse-sdk';

const pulse = createPulse({
  endpoint: process.env.APOSTL_PULSE_ENDPOINT,
  apiKey: process.env.APOSTL_PULSE_API_KEY,
  environment: process.env.NODE_ENV,
});
```

For Express, mount `pulseExpressMiddleware(pulse)`. For a Next.js route, wrap
the handler with `withPulse(pulse, handler)`. The adapters answer the signed
deployment challenge and capture the resulting request. For another server,
pass the original URL, raw request IP, complete User-Agent, method, and final
status to `observeRequest`; use `verificationResponse` to place both returned
verification headers on the public response. Call `flush()` during graceful
shutdown.

Preserve the target's existing behavior. Add focused tests proving:

- query and fragment data never leave the process;
- both IP address and User-Agent are present in accepted events;
- public HTML, Markdown, `llms.txt`, ordinary files, and public `4xx` pages are
  eligible for `GET` and `HEAD`;
- assets, health/auth/private paths, and mutation requests are not eligible;
- the signed challenge response is emitted by the deployed public route.

Preserve framework-specific integration and run the target's focused tests.
Completion still requires signed-response proof, a genuine accepted event,
the single owner claim, and confirmation that the ingest API key remains active
after claim.

## Prove the integration

Deploy only when the user's request authorizes that target and deployment.
Then run:

```bash
python3 scripts/pulse_setup.py verify --credentials /absolute/path/to/pulse.json
```

Verification succeeds only after Apostl fetches the chosen public URL, validates
the signed response, and finds the real eligible event carrying the verifier's
IP address, User-Agent, and exact canonical page. A header, HTTP 200, SDK log,
or synthetic database row alone is not proof.

If the status is `waiting_for_event`, wait briefly for the SDK batch and rerun
the same command. Do not create a replacement setup. Once it is `verified`, ask
for the email the owner will use for Apostl and start the single Auth.md claim:

```bash
python3 scripts/pulse_setup.py claim \
  --credentials /absolute/path/to/pulse.json \
  --email owner@example.com
```

Give the owner the returned six-digit `user_code` and `verification_uri`. The
owner opens that URL, signs in with the same verified email through Google,
GitHub, or an email magic link, and enters the code there. Do not ask them to
paste the code back into agent chat. Password authentication is not available.

Poll no faster than the returned interval:

```bash
python3 scripts/pulse_setup.py claim-status --credentials /absolute/path/to/pulse.json
```

Honor `retry_after` for `authorization_pending` and `slow_down`. If the
short-lived code window expires, `claim-status` automatically obtains a fresh
ceremony and returns the new `user_code` and `verification_uri` for the same
email and registration. A successful poll writes the post-claim Agent API token
and identity assertion into the same owner-only file, removes the revoked
pre-claim token locally, and reports no raw credential. One claim binds both the
Agent API registration and verified Pulse project to the owner's workspace. The
ingest API key remains active after claim and must not be rotated merely because
the project was claimed.

To disconnect the current Auth.md access token without revealing it:

```bash
python3 scripts/pulse_setup.py revoke --credentials /absolute/path/to/pulse.json
```

API errors include a `resolution` action when the platform can prescribe a safe
recovery. Follow that action without printing the stored credentials. In
particular, `origin_unavailable` means resume with the saved setup credentials
when the reservation is yours; it never authorizes a second hostname or a
takeover attempt.

## Report the result

Return:

- origin and exact verification page;
- target integration files and tests run;
- whether the signed public response and resulting real event both passed;
- Auth.md registration ID and pre-claim scope, never raw credentials;
- claim `verification_uri`, six-digit code, and expiry only after verification;
- whether final Auth.md claim connected the registration and Pulse project;
- any privacy or deployment disclosure the owner must address;
- blockers as blockers, without claiming traffic measurement is live.

Never report a collector installation, deploy, or HTTP response as a completed
Pulse setup without the route-specific invocation evidence and real-event proof.
