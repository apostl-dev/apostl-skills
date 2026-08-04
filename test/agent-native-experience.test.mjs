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
