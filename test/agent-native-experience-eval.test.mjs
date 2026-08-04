import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('agent-native routing and synthesis eval cases execute their resolver and renderer', () => {
  const result = spawnSync('python3', [
    'skills/agent-native-experience/scripts/evaluate.py',
  ], { cwd: repoRoot, encoding: 'utf8' });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const receipt = JSON.parse(result.stdout);
  assert.ok(receipt.routing.executed >= 12);
  assert.equal(receipt.routing.failed, 0);
  assert.ok(receipt.synthesis.executed >= 5);
  assert.equal(receipt.synthesis.failed, 0);
});
