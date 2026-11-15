'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const http = require('node:http');
const { backendType, supportedNode, fingerprint, verifyChecksum, mavenProxySettings, availablePort, httpReady, Launcher } = require('./start.cjs');

test('accepts only one supported backend, without shell interpretation', () => {
  assert.equal(backendType(['java']), 'java');
  assert.equal(backendType(['PYTHON']), 'python');
  for (const args of [[], ['ruby'], ['java', 'python'], ['java; echo injected'], ['']]) {
    assert.throws(() => backendType(args), /Usage:/);
  }
});

test('checks Vite-supported Node versions', () => {
  for (const version of ['20.19.0', '22.12.0', '24.0.0']) assert.equal(supportedNode(version), true);
  for (const version of ['18.20.0', '20.18.0', '22.11.0', '21.0.0']) assert.equal(supportedNode(version), false);
});

test('dependency stamp changes with manifest content and runtime', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qa-stamp-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'package.json');
  fs.writeFileSync(file, '{}');
  const before = fingerprint([file], '24.0.0');
  assert.notEqual(before, fingerprint([file], '24.1.0'));
  fs.writeFileSync(file, '{"changed":true}');
  assert.notEqual(before, fingerprint([file], '24.0.0'));
});

test('refuses corrupt Maven archives', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qa-checksum-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'archive');
  fs.writeFileSync(file, 'verified download');
  const checksum = crypto.createHash('sha512').update(fs.readFileSync(file)).digest('hex');
  verifyChecksum(file, checksum + '\n');
  verifyChecksum(file, checksum + '  archive\n');
  fs.appendFileSync(file, 'corrupted');
  assert.throws(() => verifyChecksum(file, checksum), /checksum verification failed/);
  assert.throws(() => verifyChecksum(file, 'invalid'), /checksum verification failed/);
});

test('proxy settings never copy credentials', () => {
  assert.match(mavenProxySettings({ HTTPS_PROXY: 'http://proxy.example.com:8080' }), /<host>proxy.example.com<\/host><port>8080<\/port>/);
  assert.throws(() => mavenProxySettings({ HTTPS_PROXY: 'http://user:secret@proxy.example.com' }), /secure Maven settings/);
  assert.equal(mavenProxySettings({}), '<settings/>\n');
});

test('occupied ports produce an actionable error without killing the server', async t => {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  await assert.rejects(availablePort(server.address().port), /Stop the existing service/);
  assert.equal(server.listening, true);
});

test('readiness requires a successful response with the expected content', async t => {
  const server = http.createServer((req, res) => {
    res.writeHead(req.url === '/failed' ? 500 : 200, { 'Content-Type': 'application/json' });
    res.end('{"status":"ok"}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const port = server.address().port;
  assert.equal(await httpReady(port, '/', body => JSON.parse(body).status === 'ok'), true);
  assert.equal(await httpReady(port, '/failed', () => true), false);
  assert.equal(await httpReady(port, '/', () => false), false);
});

test('runner preserves arguments containing spaces and reports command failure', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qa arguments '));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const launcher = new Launcher();
  const output = path.join(dir, 'arguments.json');
  await launcher.command(process.execPath,
    ['-e', 'require("fs").writeFileSync(process.argv[1], JSON.stringify(process.argv.slice(2)))', output, 'with spaces', 'literal & symbol'], dir);
  assert.deepEqual(JSON.parse(fs.readFileSync(output)), ['with spaces', 'literal & symbol']);
  await assert.rejects(launcher.command(process.execPath, ['-e', 'process.exit(7)'], dir), /exit 7/);
  await launcher.stop();
});

test('cleanup terminates launched children', async () => {
  const launcher = new Launcher();
  const child = launcher.child(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], os.tmpdir());
  await new Promise(resolve => child.once('spawn', resolve));
  await launcher.stop();
  await child.done;
  assert.equal(launcher.children.size, 0);
});
