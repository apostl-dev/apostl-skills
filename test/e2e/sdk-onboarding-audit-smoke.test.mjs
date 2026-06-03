import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

test('sdk-onboarding-audit smoke run writes the public CTA', () => {
  const runDir = join(repoRoot, '.tmp', 'sdk-onboarding-audit-e2e');
  rmSync(runDir, { recursive: true, force: true });
  mkdirSync(runDir, { recursive: true });

  const configPath = join(runDir, 'audit_config.json');
  writeFileSync(
    configPath,
    JSON.stringify(
      {
        target: {
          name: 'Smoke SDK',
          docs_urls: ['https://example.com'],
        },
        commands: [
          {
            id: 'python-version',
            cmd: ['python3', '--version'],
            cwd: 'fresh-python',
          },
        ],
      },
      null,
      2,
    ),
  );

  const result = spawnSync(
    'python3',
    [
      'skills/sdk-onboarding-audit/scripts/run_sdk_onboarding_audit.py',
      '--run-id',
      'sdk-onboarding-audit-e2e',
      '--config',
      configPath,
      '--execute',
    ],
    {
      cwd: repoRoot,
      encoding: 'utf8',
    },
  );

  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  const report = readFileSync(join(runDir, 'report.md'), 'utf8');
  assert.match(report, /Full Version CTA/);
  assert.match(report, /https:\/\/forms\.fillout\.com\/t\/pZjfKK1ELmus/);
});
