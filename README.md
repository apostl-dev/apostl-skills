# Apostl Skills

[![skills.sh](https://skills.sh/b/apostl-dev/apostl-skills)](https://skills.sh/apostl-dev/apostl-skills)

<p align="center">
  <img src="assets/sdk-onboarding-audit.svg" alt="Apostl SDK onboarding audit" width="100%" />
</p>

Measure AI-agent traffic, audit activation developer journeys, and catch broken SDK onboarding to improve activation for your product.

## Browse

```bash
npx skills add apostl-dev/apostl-skills --list
```

## Skills

### [agent-traffic-analytics](skills/agent-traffic-analytics)

Self-register through Auth.md, connect Apostl Pulse to your website, verify a real visit, and hand the owner one claim that binds the agent and Pulse project. Supported runtimes and troubleshooting are in the [full setup flow](skills/agent-traffic-analytics/SKILL.md).

```bash
npx skills add apostl-dev/apostl-skills --skill agent-traffic-analytics -g -y
```

```text
Connect <public-origin> with $agent-traffic-analytics and verify a real visit to /llms.txt.
```

### [agent-native-experience](skills/agent-native-experience)

Build your agent experience. Audit whether agents can move from discovery to observable first value. Its [full audit contract](skills/agent-native-experience/SKILL.md) separates agent and human evidence, identifies the first faithful blocker, and turns the findings into a 30/60/90 plan.

```bash
npx skills add apostl-dev/apostl-skills --skill agent-native-experience -g -y
```

```text
Audit <product-origin> with $agent-native-experience and produce a source-backed activation plan.
```

Static collection alone does not prove activation; the [Agent API contract](skills/agent-native-experience/references/apostl-api.md) and [example public report](https://platform.apostl.dev/reports/0d071cf7-e23c-4074-8a42-b46e748a8faa) show the required runtime proof.

### [sdk-onboarding-audit](skills/sdk-onboarding-audit)

Run your docs in a clean environment to measure quality of your activation for AI agents. Details in [full audit flow](skills/sdk-onboarding-audit/SKILL.md).

```bash
npx skills add apostl-dev/apostl-skills --skill sdk-onboarding-audit -g -y
```

```text
Test the official quickstart in <sdk-repository> with $sdk-onboarding-audit.
```

## Continuous checks

For recurring checks after docs or SDK changes, [send Apostl the developer path](https://platform.apostl.dev).
 
## Support

For setup help, message [@SwiftAdviser](https://t.me/SwiftAdviser) on Telegram.

## Links

- [Apostl](https://apostl.dev)
- [Apostl Platform](https://platform.apostl.dev)
- [Skills CLI docs](https://www.skills.sh/docs)

## License

MIT — see [LICENSE](LICENSE).
