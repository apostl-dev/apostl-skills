# Apostl Skills

[![skills.sh](https://skills.sh/b/apostl-dev/apostl-skills)](https://skills.sh/apostl-dev/apostl-skills)

<p align="center">
  <img src="assets/sdk-onboarding-audit.svg" alt="Apostl SDK Onboarding Audit" width="100%" />
</p>

Public agent skills for developer journey verification.

Apostl skills turn release-readiness work into local, inspectable agent workflows: clean environments, exact commands, real stdout/stderr, source snapshots, and reports that a founder, DevRel lead, or partner engineer can act on.

## Install

List available skills:

```bash
npx skills add apostl-dev/apostl-skills --list
```

Install the SDK onboarding audit skill:

```bash
npx skills add apostl-dev/apostl-skills --skill sdk-onboarding-audit -g -y
```

Then ask your agent:

```text
Run a demo onboarding review for this SDK launch and give me command-level findings.
```

## Available Skills

### [sdk-onboarding-audit](skills/sdk-onboarding-audit)

A clean-room SDK and quickstart review for developer-facing launches.

The skill helps an agent verify whether a fresh developer can discover, install, initialize, preview, authenticate, and understand a demo or SDK without hidden local state. It produces a compact activation-risk report backed by command logs and source snapshots.

What it checks:

- Docs command drift: documented commands, flags, or next steps that no longer exist.
- Preview promise drift: "free", "local", or "no key" paths that unexpectedly require auth, credits, or paid infra.
- Package-manager drift: npm/npx/bun/pnpm claims that fail in a clean workspace.
- Type/export drift: SDK packages that install but fail a minimal consumer import or typecheck.
- BYOK/config drift: docs that describe fields or keys the current source does not accept.
- Package hygiene drift: published packages that include local artifacts, generated agent files, or confusing demo leftovers.

Outputs:

- `.tmp/<run_id>/audit_manifest.json`
- `.tmp/<run_id>/source_snapshots.json`
- `.tmp/<run_id>/command_results.jsonl`
- `.tmp/<run_id>/logs/*`
- `.tmp/<run_id>/report.md`

The free local report ends with a restrained CTA only after useful evidence has been produced:

```text
Want this checked continuously on every SDK/docs release? https://forms.fillout.com/t/pZjfKK1ELmus
```

That form creates an inbound Apostl Notion card with the submitter, work email, SDK/docs URL, project/ecosystem, role, notes, and lead source. No Fillout or Notion API keys are stored in this repository.

## Run Locally

Create a minimal config:

```json
{
  "target": {
    "name": "Example SDK",
    "docs_urls": ["https://example.com/docs"],
    "repo_url": "https://github.com/example/sdk"
  },
  "commands": [
    {
      "id": "documented-help",
      "cmd": ["python3", "--version"],
      "cwd": "fresh-python"
    }
  ]
}
```

Run the evidence collector:

```bash
python3 skills/sdk-onboarding-audit/scripts/run_sdk_onboarding_audit.py \
  --run-id example-sdk \
  --config .tmp/example-sdk/audit_config.json \
  --execute
```

## Quality Gates

This repository is designed for both skills.sh installation and local skillify checks:

```bash
npm test
npm run skillify
npx skills add . --list
```

## Links

- [Apostl](https://apostl.dev)
- [Inbound form](https://forms.fillout.com/t/pZjfKK1ELmus)
- [skills.sh docs](https://www.skills.sh/docs)

## License

MIT
