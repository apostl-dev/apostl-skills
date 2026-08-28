import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('agent-traffic-analytics Python contract tests pass', () => {
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s',
    'skills/agent-traffic-analytics/tests', '-v'], { cwd: repoRoot, encoding: 'utf8' });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});

test('skill preserves measurement, privacy, proof, and claim boundaries', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/SKILL.md'), 'utf8');
  const contract = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/references/pulse-contract.md'), 'utf8');
  const combined = `${skill}\n${contract}`;

  assert.match(combined, /origin \+ pathname/u);
  assert.match(combined, /IP address[\s\S]*User-Agent/iu);
  assert.match(combined, /GET[\s\S]*HEAD[\s\S]*2xx[\s\S]*4xx/u);
  assert.match(combined, /signed[\s\S]*real event/iu);
  assert.match(combined, /seven days/iu);
  assert.match(combined, /Auth\.md[\s\S]*oauth-protected-resource[\s\S]*oauth-authorization-server/iu);
  assert.match(combined, /anonymous[\s\S]*pulse:setup[\s\S]*claim-status/iu);
  assert.match(combined, /urn:workos:agent-auth:grant-type:claim/iu);
  assert.match(combined, /Google[\s\S]*GitHub[\s\S]*email magic link/iu);
  assert.match(combined, /heuristic[\s\S]*(?:does not|cannot) prove/iu);
  assert.doesNotMatch(combined, /password authentication is available/iu);
});
