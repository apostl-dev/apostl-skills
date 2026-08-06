# United report contract

Lead with the exact first faithful blocker, selected journey, target agent or
user, observable activation event, and business consequence. Keep score
secondary to evidence.

Include, in order: executive verdict; business impact; versioned business
evidence; scope/environment;
score and rubric version; source/corpus coverage; Agent-ready Docs; Agent-ready
Product; agent quickstart trace; Human Frictions; guide-by-guide coverage;
deduplicated evidence; proposed fixes; visible/editable RICE fields; sorted
roadmap; 30/60/90 plan with owner, signal, dependencies; final actions;
recurring gates; provenance; limitations; public artifacts.

Use the status vocabulary from the rubric. Preserve AFDocs `skip`, unmet
dependencies, and proportional page results in JSON even when the reader view
maps them into broader language. Preserve missing RICE inputs as
`missing`; do not synthesize reach, revenue, ROI, or human evidence. A human
journey declares `primary` or `selected` mode; every human friction includes
step, observation, severity, evidence, and smallest fix. A human journey not
completed is `not_run`. Full coverage is true only when the canonicalized,
deduplicated frozen eligible corpus has terminal accounting, no conflicting
canonical duplicates, and no not-run row. A human pass requires separately
declared `human_observation` evidence; an agent trace, reference, or hash
cannot satisfy the human record.

Markdown and JSON are public-output boundaries. Reject forbidden secret fields
and redact secret-shaped strings before either format is written. Corpus rows
retain original URLs, discovery sources, redirects, auth gates, exclusions,
and hashes after canonical URL deduplication.

## Versioned business evidence

Use `business_evidence.version: "agent-native-business-evidence.v1"` with
separate `market`, `competitors`, and `buyers` lists. Each observation needs a
`source_url` or supplied `source_id`, UTC `observed_at`, UTC `valid_until` no
more than 30 days later, `evidence_type`, `claim`, `claim_kind` (`observed`,
`derived`, or `hypothesis`), status/confidence, and either `validation_owner`
or `next_owner`. Derived
impact/RICE values also name their `metric_owner`.

Malformed, stale, unverified, redacted, or missing observations render as
`unknown` or `not_run`, retain their responsible validation owner and next
action, and receive no score credit. A hypothesis or RICE estimate must remain
an estimate; it is not a measured business fact. Do not include customer
credentials, codes, tokens, cookies, email contents, raw request/response
bodies, browser profile data, or raw browser captures.

## Execution ownership

Human evidence is distinct from agent evidence. A human `pass` needs journey
and version, role, accountable owner, due/next action, observation time,
pre-activation frictions, a sanitized evidence reference, and observed
activation. Otherwise render `not_run` with the responsible next action.

In full mode, freeze the canonicalized corpus before execution. Every eligible
guide row needs source, content hash, owner, and an execution status. `Full
documentation covered: yes` is allowed only when every owned eligible row has
a completed terminal outcome; sampled, blocked, interrupted, not-run, or
unowned rows keep coverage false and visible.
