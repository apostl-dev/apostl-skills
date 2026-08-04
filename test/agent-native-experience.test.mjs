import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('agent-native-experience bundled Python tests pass', () => {
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s',
    'skills/agent-native-experience/tests', '-v'], { cwd: repoRoot, encoding: 'utf8' });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});

test('skill frontmatter only contains name and trigger-rich description', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/SKILL.md'), 'utf8');
  const frontmatter = skill.match(/^---\n([\s\S]*?)\n---/u)?.[1] ?? '';
  const keys = [...frontmatter.matchAll(/^([a-z_]+):/gmu)].map((match) => match[1]);
  assert.deepEqual(keys, ['name', 'description']);
  assert.match(frontmatter, /agent readiness|agent-native|quickstart/iu);
  assert.match(frontmatter, /audit|assess|score/iu);
});

test('routing eval covers realistic positive and negative prompts', () => {
  const lines = readFileSync(resolve(repoRoot, 'skills/agent-native-experience/routing-eval.jsonl'), 'utf8')
    .trim().split('\n').map((line) => JSON.parse(line));
  assert.ok(lines.length >= 12);
  assert.ok(lines.some((row) => row.should_trigger && /quickstart|agent/iu.test(row.prompt)));
  assert.ok(lines.some((row) => !row.should_trigger));
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
