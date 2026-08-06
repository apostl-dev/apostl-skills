# Bounded local evidence collector

Use `scripts/collect_evidence.py` when AFDocs is unavailable or when a portable,
standard-library-only static baseline is useful. It produces normalized input
for `audit.py`; it does not replace the clean-environment activation journey.

## Quick start

```bash
python3 scripts/collect_evidence.py \
  --url https://example.com/docs/quickstart \
  --journey "Install and run the documented quickstart" \
  --activation-event "The documented result is visible" \
  --target-agent "new coding agent" \
  --mode sample \
  --output-dir ./agent-native-evidence
```

Outputs:

- `raw-evidence.json`: bounded response metadata only—safe headers, statuses,
  redirect chains, byte counts, content hashes, errors, and truncation state;
- `evidence.json`: all 23 normalized documentation checks plus explicit
  `not_run` agent and human journeys;
- `report.md`: deterministic reader report;
- `report.json`: deterministic structured report.

Raw response bodies are analyzed in memory and are not written to disk. Add the
real command/browser/API trace, frictions, product checks, and human evidence to
`evidence.json`, then rerender if needed:

```bash
python3 scripts/audit.py \
  --evidence ./agent-native-evidence/evidence.json \
  --output ./agent-native-evidence/report.md \
  --json-output ./agent-native-evidence/report.json
```

## Clean-room W3Schools browser activation proof

The collector is static-only. For a separately executed browser proof, use the
credential-free fixture source `https://www.w3schools.com/html/html_intro.asp`.
In a fresh temporary directory, reproduce the pinned introductory HTML locally,
then use the project-standard `agent-browser` workflow with a fresh profile to
observe exactly `This is a heading` in the H1 and `This is a paragraph.` in the
paragraph. Start the browser workflow with `agent-browser skills get core`.
Record ordered actions, deviations, timestamps, clean-room directory/profile
identity, the activation observation, and only sanitized snapshot/screenshot
references. Do not save browser cookies, profiles, raw snapshots, or raw
screenshots.

The repository's recorded non-network fixture is a validator contract, not a
claim that this machine opened a browser. Validate it with:

```bash
python3 scripts/execute_cleanroom.py \
  --w3schools-fixture-dir tests/fixtures/w3schools-clean-room
```

It rejects a static fetch, status code, screenshot filename, or source/local
HTML/trace/browser-DOM mismatch. A real browser run remains separately
evidenced and is never started by installation or the default test suite.

## Safety and bounds

The collector performs signed-out `GET` requests only. It rejects:

- schemes other than HTTP or HTTPS;
- usernames or passwords embedded in URLs;
- every query string, including signed, authenticated, and ordinary query
  parameters;
- localhost, `.local`, `.internal`, loopback, private, link-local, reserved,
  multicast, and otherwise non-global IP addresses;
- redirects to those targets or to URLs with userinfo/query strings.

The rule also excludes discovered HTML, sitemap, and llms.txt links with
userinfo or query strings before corpus or raw metadata is created. Each
request resolves its hostname once, validates every answer, and connects the
TCP socket directly to a validated public numeric IP. HTTPS still verifies the
certificate and sends SNI for the original hostname; HTTP sends the original
Host header. The connect path does not perform a second hostname resolution.

It disables environment HTTP proxies and records only a safe response-header
allowlist. Defaults and hard caps are:

| Limit | Default | Hard range |
| --- | ---: | ---: |
| Requests | 32 | 1-64 |
| Bytes captured per response | 1,000,000 | 1,024-2,000,000 |
| Timeout per request | 10 seconds | 1-30 seconds |
| Redirects per request | 4 | 0-5 |
| Guides in one frozen execution set | 10 | 1-50 |

Override them with `--max-requests`, `--max-bytes`, `--timeout-seconds`,
`--max-redirects`, and `--max-pages`. Exceeding a network limit stops the run.
If `--mode full` discovers more eligible same-section URLs than `--max-pages`,
the collector records the count, downgrades the effective corpus to `sample`,
and leaves a limitation. It never truncates a corpus and calls it full.

## Checks and semantics

The collector fills every documentation criterion in `rubric.v1.json` and
preserves `skip`, `not_run`, `not_applicable`, proportions, and dependency
semantics for `audit.py`. It inventories canonical `llms.txt` candidates,
`sitemap.xml`, `robots.txt`, same-origin navigation, deterministic Markdown
variants, Markdown content negotiation, invalid-path status behavior,
rendered/static content structure, sizes, headers, redirects, and auth gates.

This is an AFDocs-compatible bounded fallback, not the AFDocs implementation.
Use AFDocs directly when installed, especially for platform-specific HTML to
Markdown conversion, deeper sitemap/index traversal, and exact AFDocs
diagnostics. The fallback records its collector version and limitations so its
measurements are not confused with native AFDocs output.

## Remaining boundaries

- Static collection never proves the promised activation event.
- Product/API criteria remain `unknown` until supplied or executed evidence is
  added; the collector does not mark them `not_applicable` on the user's behalf.
- Human Frictions remain `not_run` until a human completes the journey.
- Human evidence needs the accountable owner, journey version, observation
  time, activation evidence reference, and responsible next action; agent
  evidence cannot substitute for it.
- Full documentation covered is possible only after every frozen eligible guide
  has an owned terminal row with source and content hash. Blocked or unowned
  rows remain visible and keep coverage false.
- A request uses the first validated public address and does not retry alternate
  addresses, so a transient failure on that address can block collection.
- Drift-prone rubric sources are not refreshed automatically. Refresh them
  before describing guidance as current.
