# PR #2 security hardening

## Scope

Harden the bundled `agent-native-experience` evidence collector on the existing
`codex/agent-native-experience-v1-0-1` branch. Keep PR #2 open and unmerged.

## Acceptance criteria

- AC1: The collector rejects every initial HTTP(S) URL containing userinfo or a
  query string, including `sig`, `signature`, `auth`, `authorization`,
  `credential`, and `X-Amz-Signature`, without returning or persisting the
  credential value.
- AC2: The same rule is enforced for redirect targets before the target is
  requested or added to redirect/raw/evidence/report output.
- AC3: Discovered HTML, sitemap, and llms.txt URLs containing userinfo or query
  strings are excluded before corpus or raw metadata persistence.
- AC4: Every request resolves the hostname once, validates every returned
  address as globally routable, and connects the socket directly to one of the
  validated numeric addresses. The HTTP Host header and HTTPS SNI/certificate
  hostname remain the original hostname.
- AC5: A deterministic regression proves that a resolver returning a public IP
  on validation and a private IP on a hypothetical second lookup is called only
  once and the connection target is the validated public IP.
- AC6: The official repository tests, focused collector tests, independent
  forward test, skill validators, secret scans, and bounded W3Schools sample
  and full/overflow exercises pass on the final tree.
- AC7: Documentation accurately describes the query/userinfo rejection and
  IP-pinned connection behavior and no longer claims DNS rebinding remains
  possible between validation and connection.
- AC8: Changes are committed and pushed to the existing PR #2 branch. PR #2
  remains open; no merge, tag, or release is performed.

## Non-goals

- Supporting authenticated or signed documentation URLs.
- Adding third-party HTTP dependencies, proxies, cookies, or request methods
  other than signed-out GET.
- Merging PR #2 or publishing a release.
