import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('agent-native synthesis eval keeps honesty and decision-ready quality gates', () => {
  const rows = readFileSync(resolve(
    repoRoot,
    'skills/agent-native-experience/evals/synthesis-eval.jsonl',
  ), 'utf8').trim().split('\n').map((line) => JSON.parse(line));

  assert.ok(rows.length >= 5);
  assert.ok(rows.every((row) => Array.isArray(row.must_include) && row.must_include.length > 0));
  assert.ok(rows.some((row) => row.id === 'human-not-run' && row.must_include.includes('Next action')));
  assert.ok(rows.some((row) => row.must_not_include.includes('FULL Documentation Covered')));
});
