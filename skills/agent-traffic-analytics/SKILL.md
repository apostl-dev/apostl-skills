---
name: agent-traffic-analytics
description: Install and verify Apostl Pulse server-side analytics for public AI-agent traffic. Use when someone asks how many AI agents visit a website, docs, API, llms.txt, Markdown, or other public pages; wants per-page agent analytics; wants to add the Pulse SDK; or wants an agent to create an unclaimed Pulse setup and hand the owner a one-time claim link.
---

# Agent Traffic Analytics

Answer one question with inspectable server-side evidence: how many estimated
AI agents are using this public product right now, and which pages do they use?

## Contract

Pulse measures eligible public page requests. The SDK sends the request IP
address, full User-Agent, and canonical page identity as `origin + pathname`.
It strips query strings, fragments, and URL credentials. It never sends request
bodies, cookies, authorization headers, or query parameters.

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
public API surfaces, Markdown, and `llms.txt`. The owner gets a live five-minute
agent estimate, a 30-day page ranking, and inspectable proof that the deployed
middleware produced a real event. For an existing Express or Next.js server,
the code change is one client plus one middleware or handler wrapper; budget
about ten minutes for the code edit, then add whatever test, review, and deploy
time the target normally requires. Do not promise a live dashboard before the
public verification request and its event both pass.

Starting requires a public HTTPS origin, access to the server code and secret
runtime, permission to install a package, and an authorized deploy path. A human
account is not required until claim; the owner then uses Google, GitHub, or an
email magic link.

## Start without an account

An agent may create an unclaimed setup without waiting for a human. This is a
real Apostl API mutation that reserves the origin for seven days, so do it only
when the user has asked to set up or install Pulse for that origin.

Run from this skill directory:

```bash
python3 scripts/pulse_setup.py start \
  --origin https://docs.example.com \
  --verification-path /llms.txt \
  --project-name "Example docs" \
  --agent-name "Codex"
```

The command prints non-secret setup metadata and the local credentials path.
It stores the API key and opaque setup token in an owner-only `0600` file. Never
print, paste into chat, commit, or construct a URL from either raw secret. The
only capability URL to share is the one-time `claim_url` returned by Apostl
after verification; it never contains the API key. If the origin is already
owned or reserved, stop and report the explicit `origin_unavailable` response;
do not create another project or use a variant hostname to bypass it.

## Install the server SDK

Inspect the target server and use its existing package manager. Pulse must run
on the server where the raw request IP address and User-Agent are available.
Do not add it to a browser bundle.

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
the same command. Do not create a replacement setup. If it is `verified`, give
the human only the opaque one-time `claim_url`. The owner signs in with Google,
GitHub, or an email magic link; password authentication is not available. The
ingest API key remains active after claim and must not be rotated merely because
the project was claimed.

## Report the result

Return:

- origin and exact verification page;
- target integration files and tests run;
- whether the signed public response and resulting real event both passed;
- claim URL only when verified, plus its seven-day setup expiry;
- any privacy or deployment disclosure the owner must address;
- blockers as blockers, without claiming traffic measurement is live.

Never report an SDK installation, deploy, or HTTP response as a completed Pulse
setup without the real-event proof.
