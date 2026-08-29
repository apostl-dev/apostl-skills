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

test('skill routes Cloudflare and non-Cloudflare origins before installation', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/SKILL.md'), 'utf8');
  const contract = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/references/pulse-contract.md'), 'utf8');
  const combined = `${skill}\n${contract}`;

  assert.match(skill, /description:.*Cloudflare.*server SDK/iu);
  assert.ok(
    skill.indexOf('## Choose one collector') < skill.indexOf('## Start through Auth.md'),
    'collector routing must happen before setup or installation',
  );
  assert.match(skill, /https:\/\/github\.com\/apostl-dev\/apostl-skills\/tree\/main\/skills\/agent-traffic-analytics/u);
  assert.match(combined, /Cloudflare[\s-]+control[\s-]+plane[\s\S]*CF-Ray/iu);
  assert.match(combined, /nameservers[\s\S]*(?:insufficient|not enough)/iu);
  assert.match(combined, /DNS-only[\s\S]*server SDK/iu);
  assert.match(combined, /unreachable[\s\S]*(?:blocked|stop)/iu);
  assert.match(combined, /missing[\s\S]*(?:route|source)[\s\S]*authority[\s\S]*(?:blocked|stop)/iu);
  assert.match(combined, /https:\/\/github\.com\/apostl-dev\/pulse-cloudflare-worker/u);
  assert.match(combined, /https:\/\/github\.com\/apostl-dev\/pulse-sdk/u);
});

test('Cloudflare branch is private, fail-open, non-looping, and proof-backed', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/SKILL.md'), 'utf8');
  const contract = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/references/pulse-contract.md'), 'utf8');
  const combined = `${skill}\n${contract}`;

  assert.match(combined, /MIT[- ]licensed/iu);
  assert.match(combined, /APOSTL_PULSE_API_KEY[\s\S]*Worker secret/iu);
  assert.match(combined, /Worker Route[\s\S]*(?:existing|current) origin/iu);
  assert.match(combined, /Custom Domain[\s\S]*(?:loop|do not|never)/iu);
  assert.match(combined, /Worker or Pages[\s\S]*(?:integrate|controlled edge runtime)/iu);
  assert.match(combined, /CF-Connecting-IP[\s\S]*(?:bounded|limit)[\s\S]*(?:full|complete) User-Agent/iu);
  assert.match(combined, /ctx\.waitUntil\(\)[\s\S]*fail[- ]open/iu);
  assert.match(combined, /query[\s\S]*bod(?:y|ies)[\s\S]*cookies[\s\S]*authorization/iu);
  assert.match(combined, /every representable request[\s\S]*centrally/iu);
  assert.match(combined, /privacy review/iu);
  assert.match(combined, /signed challenge[\s\S]*genuine request[\s\S]*Cloudflare invocation[\s\S]*positive Pulse/iu);
});

test('one collector owns each request path and SDK proof remains complete', () => {
  const skill = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/SKILL.md'), 'utf8');
  const contract = readFileSync(resolve(repoRoot, 'skills/agent-traffic-analytics/references/pulse-contract.md'), 'utf8');
  const combined = `${skill}\n${contract}`;

  assert.match(combined, /exactly one Pulse collector[\s\S]*(?:request path|hostname\/route)/iu);
  assert.match(combined, /(?:never|do not)[\s\S]*(?:Worker\s+and\s+SDK|SDK\s+and\s+Worker)[\s\S]*(?:same hostname|same route)/iu);
  assert.match(combined, /measured migration[\s\S]*deduplication proof/iu);
  assert.match(combined, /framework-specific/iu);
  assert.match(combined, /focused tests[\s\S]*signed[\s\S]*genuine[\s\S]*claim/iu);
  assert.match(combined, /ingest (?:API )?key remains active after claim/iu);
});

test('routing evals cover every collector decision and blocker', () => {
  const rows = readFileSync(
    resolve(repoRoot, 'skills/agent-traffic-analytics/routing-eval.jsonl'),
    'utf8',
  ).trim().split('\n').map((line) => JSON.parse(line));
  const routes = new Map(rows.filter((row) => row.routing_case).map((row) => [row.routing_case, row]));

  assert.deepEqual(
    [...routes.keys()].sort(),
    [
      'ambiguous-unreachable',
      'cloudflare-dns-only',
      'cloudflare-proxied',
      'double-instrumentation',
      'existing-cloudflare-runtime',
      'ordinary-server',
    ],
  );
  assert.equal(routes.get('cloudflare-proxied').expected_collector, 'cloudflare-worker');
  assert.equal(routes.get('cloudflare-dns-only').expected_collector, 'server-sdk');
  assert.equal(routes.get('existing-cloudflare-runtime').expected_collector, 'existing-cloudflare-runtime');
  assert.equal(routes.get('ordinary-server').expected_collector, 'server-sdk');
  assert.equal(routes.get('ambiguous-unreachable').expected_outcome, 'blocked');
  assert.equal(routes.get('double-instrumentation').expected_outcome, 'do-not-install-second');
});
