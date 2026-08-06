import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('agent-native-experience bundled Python tests pass', () => {
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s',
    'skills/agent-native-experience/tests', '-v'], { cwd: repoRoot, encoding: 'utf8' });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});

test('skill frontmatter exposes supported trigger phrases', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/SKILL.md'), 'utf8');
  const frontmatter = skill.match(/^---\n([\s\S]*?)\n---/u)?.[1] ?? '';
  const keys = [...frontmatter.matchAll(/^([a-z_]+):/gmu)].map((match) => match[1]);
  assert.deepEqual(keys, ['name', 'description', 'triggers']);
  assert.match(frontmatter, /agent readiness|agent-native|quickstart/iu);
  assert.match(frontmatter, /audit|assess|score/iu);
  assert.match(frontmatter, /audit our agent-native experience/iu);
  assert.match(frontmatter, /check our llms\.txt and agent-ready docs/iu);
});

test('routing eval covers realistic positive and negative prompts', () => {
  const lines = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/routing-eval.jsonl'), 'utf8')
    .trim().split('\n').map((line) => JSON.parse(line));
  assert.ok(lines.length >= 12);
  assert.ok(lines.some((row) => row.should_trigger && /quickstart|agent/iu.test(row.prompt)));
  assert.ok(lines.some((row) => !row.should_trigger));
  for (const row of lines) {
    assert.equal(row.intent, row.prompt);
    assert.equal(
      row.expected_skill,
      row.should_trigger ? 'agent-native-experience' : null,
    );
  }
});

test('released source registry identifies the pinned current AFDocs revision', () => {
  const registry = JSON.parse(readFileSync(resolve(
    repoRoot,
    'skills/agent-native-experience/references/sources.v1.json',
  ), 'utf8'));
  const afdocs = registry.sources.find((source) => source.id === 'afdocs-checks');

  assert.equal(afdocs.commit, 'fa688db9628d4b68e58bd90bb8625fb1d2c9a29d');
  assert.match(afdocs.version, /AFDocs v0\.18\.7/u);
});

test('repository resolver and README expose the public skill journey', () => {
  const resolver = readFileSync(resolve(repoRoot, 'skills/RESOLVER.md'), 'utf8');
  const readme = readFileSync(resolve(repoRoot, 'README.md'), 'utf8');
  const resolverRows = resolver.split('\n')
    .filter((line) => line.includes('skills/agent-native-experience/SKILL.md'));

  assert.ok(resolverRows.length >= 5, `expected at least five resolver rows, got ${resolverRows.length}`);
  assert.match(resolver, /agent-native|agent readiness|quickstart friction/iu);
  assert.match(readme, /\[Agent API contract\]\(skills\/agent-native-experience\/references\/apostl-api\.md\)/u);
  assert.match(readme, /\[example public report\]\(https:\/\/platform\.apostl\.dev\/reports\/[0-9a-f-]+\)/u);
  assert.doesNotMatch(readme, /github\.com\/apostl-dev\/apostl-app/u);
});

test('skill and README preserve the local boundary and Apostl-owned link flow', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/SKILL.md'), 'utf8');
  const readme = readFileSync(resolve(repoRoot, 'README.md'), 'utf8');
  const api = readFileSync(resolve(
    repoRoot, 'skills/agent-native-experience/references/apostl-api.md',
  ), 'utf8');
  const combined = `${skill}\n${readme}`;

  assert.match(combined, /authorize[\s\S]*wait-authorization/iu);
  assert.match(combined, /local[^\n]*(?:zero|no) Apostl|no Apostl account/iu);
  assert.match(combined, /GitHub[^\n]*(?:distribution|source)/iu);
  assert.match(combined, /(?:runner|image)[^\n]*(?:inside|internal|production perimeter)/iu);
  assert.match(combined, /feedback/iu);
  assert.match(api, /POST `?\/agent\/authorizations`?/u);
  assert.match(api, /POST `?\/agent\/authorizations\/token`?/u);
  assert.match(api, /GET\|POST `?\/agent\/feedback`?/u);
  assert.doesNotMatch(combined, /Registration uses email plus a human-supplied six-digit code/iu);
});

test('published guidance distinguishes recorded W3 browser proof, ownership gates, and P1 live proof', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/SKILL.md'), 'utf8');
  const readme = readFileSync(resolve(repoRoot, 'README.md'), 'utf8');
  const contract = readFileSync(resolve(
    repoRoot, 'skills/agent-native-experience/references/report-contract.md',
  ), 'utf8');
  const collector = readFileSync(resolve(
    repoRoot, 'skills/agent-native-experience/references/local-evidence-collector.md',
  ), 'utf8');
  const api = readFileSync(resolve(
    repoRoot, 'skills/agent-native-experience/references/apostl-api.md',
  ), 'utf8');
  const combined = `${skill}\n${readme}\n${contract}\n${collector}`;

  assert.match(combined, /agent-native-business-evidence\.v1/u);
  assert.match(combined, /https:\/\/www\.w3schools\.com\/html\/html_intro\.asp/u);
  assert.match(combined, /execute_cleanroom\.py/u);
  assert.match(combined, /agent-browser/u);
  assert.match(combined, /static collection[^.]*does not prove activation/iu);
  assert.match(combined, /accountable owner|responsible next action/iu);
  assert.match(combined, /full documentation covered[^.]*only/iu);
  assert.match(api, /P1|identity envelope/iu);
});

test('skills CLI installs only into an isolated project and leaves its global snapshot unchanged', (t) => {
  const root = join(tmpdir(), `agent-native-skill-install-${process.pid}-${Date.now()}`);
  const project = join(root, 'project');
  const isolatedHome = join(root, 'home');
  mkdirSync(project, { recursive: true });
  mkdirSync(isolatedHome, { recursive: true });
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = {
    ...process.env,
    HOME: isolatedHome,
    XDG_CONFIG_HOME: join(isolatedHome, '.config'),
  };
  const snapshot = () => spawnSync('npx', ['skills', 'list', '--global', '--json'], {
    cwd: project, encoding: 'utf8', env,
  });
  const before = snapshot();
  assert.equal(before.status, 0, `${before.stdout}\n${before.stderr}`);

  const install = spawnSync('npx', ['skills', 'add', repoRoot, '--agent', 'codex',
    '--skill', 'agent-native-experience', '--yes', '--copy'], {
    cwd: project, encoding: 'utf8', env,
  });
  assert.equal(install.status, 0, `${install.stdout}\n${install.stderr}`);
  assert.ok(existsSync(join(project, '.agents', 'skills', 'agent-native-experience', 'SKILL.md')));
  assert.ok(!existsSync(join(isolatedHome, '.agents', 'skills', 'agent-native-experience')));

  const after = snapshot();
  assert.equal(after.status, 0, `${after.stdout}\n${after.stderr}`);
  assert.equal(after.stdout, before.stdout);
});
