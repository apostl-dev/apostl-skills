# Verification problems and fixes

## V1: relative empty-query references were normalized away

The first independent forward pass found that `urljoin()` normalized
`Location: /next?` and discovered `/docs/empty?` before validation. This could
turn a query-bearing reference into a query-free URL and allow a request or
persisted corpus URL.

Smallest safe fix:

- validate raw redirect and discovered references before `urljoin()`;
- reject any `?`, including an empty query marker, plus fragments, control
  characters, and userinfo;
- add focused regressions proving one request only for the redirect and no
  persistence for the discovered URL.

Fresh verification after the fix: PASS.
