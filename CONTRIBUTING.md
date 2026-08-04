# Contributing

Keep skills local-first, evidence-backed, and safe to install. Add a failing
test before changing behavior, keep generated artifacts reproducible, and do
not commit credentials, activation codes, cookies, or customer data.

Run before opening a pull request:

```bash
npm test
npm run test:agent-native
python3 /path/to/skill-creator/scripts/quick_validate.py skills/agent-native-experience
```

Rubric or source changes must retain explicit versions and provenance. Missing
evidence remains `unknown` or `not_run`; do not make scores look complete by
silently excluding failed or unexecuted work.
