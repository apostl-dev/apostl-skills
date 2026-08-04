# Security

Please do not open a public issue for a suspected vulnerability or exposed
credential. Email `security@apostl.dev` with the affected skill, a minimal
reproduction, and the impact. Do not include live customer credentials.

The Agent Native Experience skill redacts Apostl API keys, writes credentials
outside repositories with mode `0600`, and requires explicit confirmation
before remote deployment or run submission. Rotate or revoke any credential
that may have been exposed.
