import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');

function runClient(args) {
  return new Promise((resolveRun) => {
    const child = spawn('python3', [
      'skills/agent-native-experience/scripts/apostl_client.py', ...args,
    ], { cwd: repoRoot, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (status) => resolveRun({ status, stdout, stderr }));
  });
}

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

test('mocked Apostl preview-to-terminal-report CLI path is confirmed, idempotent, and bounded', async (t) => {
  const runDir = join(repoRoot, '.tmp', 'agent-native-experience-api-e2e');
  rmSync(runDir, { recursive: true, force: true });
  mkdirSync(runDir, { recursive: true });
  const credentials = join(runDir, 'credentials.json');
  writeFileSync(credentials, JSON.stringify({ api_key: '1|synthetic_test_token', api_base: 'placeholder' }), { mode: 0o600 });

  const calls = [];
  let polls = 0;
  const server = createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => {
      const path = request.url;
      calls.push({ method: request.method, path, idempotency: request.headers['idempotency-key'], body });
      let data;
      if (path === '/api/v1/agent/deployments/preview') data = { mutates: false, requires_confirmation: true };
      else if (path === '/api/v1/agent/projects') data = { id: 10 };
      else if (path === '/api/v1/agent/projects/10/workflows') data = { id: 20 };
      else if (path === '/api/v1/agent/workflows/20/runs') data = { id: 30, status: 'queued' };
      else if (path === '/api/v1/agent/runs/30') {
        polls += 1;
        data = polls === 1
          ? { id: 30, status: 'running' }
          : { id: 30, status: 'passed', report_url: 'https://platform.apostl.dev/reports/mock-proof' };
      } else {
        response.writeHead(404); response.end(); return;
      }
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ data }));
    });
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  t.after(() => server.close());
  const { port } = server.address();
  const baseArgs = ['--base-url', `http://127.0.0.1:${port}/api/v1`, '--credentials', credentials];
  writeFileSync(credentials, JSON.stringify({
    api_key: '1|synthetic_test_token', api_base: `http://127.0.0.1:${port}/api/v1`,
  }), { mode: 0o600 });

  const invocations = [
    ['preview', '--source-url', 'https://example.com/docs', '--journey-url', 'https://example.com/docs/quickstart',
      '--expected-activation', 'Rendered result', '--run-mode', 'external_strict'],
    ['project', '--source-url', 'https://example.com/docs', '--confirm', '--idempotency-key', 'project-e2e'],
    ['workflow', '--project-id', '10', '--journey-url', 'https://example.com/docs/quickstart',
      '--expected-activation', 'Rendered result', '--run-mode', 'external_strict', '--confirm', '--idempotency-key', 'workflow-e2e'],
    ['run', '--workflow-id', '20', '--confirm', '--idempotency-key', 'run-e2e'],
    ['poll', '--run-id', '30', '--interval-seconds', '0', '--max-attempts', '2'],
  ];
  const results = [];
  for (const args of invocations) {
    const result = await runClient([...baseArgs, ...args]);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    results.push(JSON.parse(result.stdout));
  }

  assert.equal(results.at(-1).status, 'passed');
  assert.equal(results.at(-1).report_url, 'https://platform.apostl.dev/reports/mock-proof');
  assert.equal(polls, 2);
  assert.deepEqual(
    calls.filter((call) => call.idempotency).map((call) => call.idempotency),
    ['project-e2e', 'workflow-e2e', 'run-e2e'],
  );
  assert.ok(calls.every((call) => !call.body.includes('synthetic_test_token')));
});

test('mocked Apostl link authorization stores pending and one-time credentials without stdout secrets', async (t) => {
  const runDir = join(repoRoot, '.tmp', 'agent-native-experience-link-auth-e2e');
  rmSync(runDir, { recursive: true, force: true });
  mkdirSync(runDir, { recursive: true });
  const credentials = join(runDir, 'credentials.json');
  const authorization = join(runDir, 'authorization.json');
  const deviceCode = 'opaque-device-code-e2e';
  const apiKey = '123|apostl_e2e_one_time_secret';
  const calls = [];

  const server = createServer((request, response) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => {
      const payload = body ? JSON.parse(body) : {};
      calls.push({ method: request.method, path: request.url, payload });
      const { port } = server.address();
      let status;
      let data;
      if (request.url === '/api/v1/agent/authorizations') {
        status = 202;
        data = {
          authorization_request_id: 'authorization-e2e',
          device_code: deviceCode,
          verification_uri_complete: `http://127.0.0.1:${port}/agent/authorize/browser-token`,
          expires_at: '2099-08-05T04:15:00Z', expires_in: 600, interval: 5, status: 'pending',
        };
      } else if (request.url === '/api/v1/agent/authorizations/token') {
        status = 201;
        data = {
          status: 'consumed', api_key: apiKey, api_key_prefix: '123|apos',
          api_key_created_at: '2026-08-05T04:10:00Z', client_id: 'client-e2e',
          identity: { id: 1 }, workspace: { id: 2 },
          scopes: ['agent:read', 'agent:deploy', 'agent:keys', 'agent:feedback'],
          balance: { available: 100, reserved: 0 },
        };
      } else {
        response.writeHead(404); response.end(); return;
      }
      response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      response.end(JSON.stringify({ data }));
    });
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  t.after(() => server.close());
  const { port } = server.address();
  const globalArgs = [
    '--base-url', `http://127.0.0.1:${port}/api/v1`,
    '--credentials', credentials, '--authorization', authorization,
  ];
  const authorized = await runClient([...globalArgs, 'authorize',
    '--agent-name', 'Codex local agent', '--device-name', 'Codex local agent',
    '--source-url', 'https://www.w3schools.com/',
    '--journey-url', 'https://www.w3schools.com/html/html_intro.asp',
    '--expected-activation', 'Observe the rendered heading and paragraph.',
    '--run-mode', 'external_strict']);
  assert.equal(authorized.status, 0, `${authorized.stdout}\n${authorized.stderr}`);
  assert.match(authorized.stdout, /verification_url/u);
  assert.doesNotMatch(authorized.stdout + authorized.stderr, new RegExp(deviceCode, 'u'));
  assert.equal(statSync(authorization).mode & 0o777, 0o600);

  const redeemed = await runClient([...globalArgs, 'wait-authorization', '--max-wait-seconds', '30']);
  assert.equal(redeemed.status, 0, `${redeemed.stdout}\n${redeemed.stderr}`);
  assert.doesNotMatch(redeemed.stdout + redeemed.stderr, new RegExp(apiKey.replace('|', '\\|'), 'u'));
  assert.doesNotMatch(redeemed.stdout + redeemed.stderr, new RegExp(deviceCode, 'u'));
  assert.equal(statSync(credentials).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(credentials, 'utf8')).api_key, apiKey);
  assert.deepEqual(calls.map((call) => call.path), [
    '/api/v1/agent/authorizations', '/api/v1/agent/authorizations/token',
  ]);
  assert.ok(calls[0].payload.requested_scopes.includes('agent:feedback'));
  assert.equal(calls[1].payload.device_code, deviceCode);
});
