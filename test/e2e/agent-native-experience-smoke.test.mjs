import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

test('local-only trigger-to-report smoke is deterministic and does not require Apostl credentials', () => {
  const runDir = join(repoRoot, '.tmp', 'agent-native-experience-e2e');
  rmSync(runDir, { recursive: true, force: true });
  mkdirSync(runDir, { recursive: true });
  const evidencePath = join(runDir, 'evidence.json');
  const outputPath = join(runDir, 'report.md');
  writeFileSync(evidencePath, JSON.stringify({
    journey: { name: 'W3Schools HTML intro', target: 'new coding agent',
      activation_event: 'rendered heading and paragraph observed' },
    checks: {},
    agent_journey: { status: 'not_run', activation_reached: false },
    human_journey: { status: 'not_run' },
    corpus: { mode: 'sample', rows: [] },
    frictions: [],
  }));
  const result = spawnSync('python3', [
    'skills/agent-native-experience/scripts/audit.py', '--evidence', evidencePath,
    '--output', outputPath,
  ], { cwd: repoRoot, encoding: 'utf8', env: { ...process.env, APOSTL_API_KEY: '' } });

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const report = readFileSync(outputPath, 'utf8');
  assert.match(report, /Executive verdict/);
  assert.match(report, /not_run/);
  assert.match(report, /W3Schools HTML intro/);
  assert.doesNotMatch(report, /FULL Documentation Covered/);
});
