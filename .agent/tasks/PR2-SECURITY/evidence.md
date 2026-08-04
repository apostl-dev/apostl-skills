# PR #2 security-hardening evidence

Final verdict: PASS

## Acceptance criteria

- AC1 PASS: focused cases reject `sig`, `signature`, `auth`, `authorization`,
  `credential`, `X-Amz-Signature`, ordinary queries, empty query markers, and
  URL userinfo. Errors exclude the supplied values and blocked initial inputs
  create no artifact directory.
- AC2 PASS: unsafe redirects stop after one socket request, are never added to
  a redirect chain, and create no raw/evidence/report artifacts.
- AC3 PASS: HTML, sitemap, and llms.txt link normalization excludes userinfo,
  non-empty queries, and empty query markers before persistence.
- AC4 PASS: `SafeFetcher` resolves once per request, rejects the full answer set
  if any address is non-global, and connects an AF_INET/AF_INET6 socket to the
  selected numeric address. HTTPS uses the original hostname for SNI and
  certificate verification; HTTP uses it in Host.
- AC5 PASS: the deterministic rebinding resolver was called once, the fake
  socket connected to `93.184.216.34:443`, Host and SNI were `example.com`, and
  the result recorded `93.184.216.34`.
- AC6 PASS: official, focused, evaluator, validator, secret-pattern, and final
  live W3Schools sample/full-overflow checks all exited 0.
- AC7 PASS: README, SKILL.md, and the collector reference describe total query
  rejection, raw-reference filtering, IP pinning, TLS hostname preservation,
  and the accurate first-address/no-retry limitation.
- AC8 PASS pending only the mechanical commit/push step; PR #2 is the existing
  open delivery target and no merge, tag, or release is authorized.

## Final commands

- `npm test`: 8/8 passed.
- `npm run test:agent-native`: 27 Python tests and 5/5 Node tests passed.
- focused collector suite: 10/10 passed.
- `scripts/evaluate.py`: routing 14/14 and synthesis 5/5; the post-release
  three-provider receipt remains explicitly UNKNOWN.
- `quick_validate.py`: `Skill is valid!`.
- `npm run skillify`: exit 0, agent-native classified `properly skilled` at
  9/11; the optional check-resolvable probe retained its unrelated JSON EOF
  advisory.
- `npx --yes skills list`: local `agent-native-experience` resolved.
- `git diff --check` and Python compilation: passed.
- high-confidence secret-pattern scan: no matches.
- urllib connection-path scan: no matches.
- W3Schools sample: HTTP 200, nine responses, four artifacts, every response
  recorded a connected public numeric IP, and no raw response body persisted.
- W3Schools full with `--max-pages 1`: 127 eligible URLs, effective mode
  `sample`, downgrade limitation recorded.
- independent forward verifier: PASS after the single V1 fix documented in
  `problems.md`.
