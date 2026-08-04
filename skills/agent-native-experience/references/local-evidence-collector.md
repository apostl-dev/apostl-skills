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

## Safety and bounds

The collector performs signed-out `GET` requests only. It rejects:

- schemes other than HTTP or HTTPS;
- usernames or passwords embedded in URLs;
- localhost, `.local`, `.internal`, loopback, private, link-local, reserved,
  multicast, and otherwise non-global IP addresses;
- redirects to those targets.

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
- Public DNS is checked before each request and redirect, but the Python
  standard-library HTTP stack cannot fully pin DNS against rebinding between
  validation and connection.
- Drift-prone rubric sources are not refreshed automatically. Refresh them
  before describing guidance as current.
