import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { HostAdapter } from '../dist/index.js';

function installedFutureFixture(packed = false) {
  const directory = mkdtempSync(join(tmpdir(), 'love-house-future-contract-'));
  const app = join(directory, 'future app'), resources = join(app, 'resources');
  const fingerprints = JSON.parse(readFileSync('host-contract-fingerprints.json', 'utf8'));
  const version = '99.1.0-future-fixture';
  for (const [name, expected] of Object.entries(fingerprints.packages)) {
    const original = resolve('node_modules', name), destination = join(resources, 'app/dsh/node_modules', name);
    mkdirSync(destination, { recursive: true });
    const source = JSON.parse(readFileSync(join(original, 'package.json'), 'utf8'));
    const replaced = JSON.stringify(source).replaceAll(source.version, version);
    writeFileSync(join(destination, 'package.json'), replaced);
    for (const filename of Object.keys(expected.files)) {
      const target = join(destination, filename); mkdirSync(dirname(target), { recursive: true });
      writeFileSync(target, readFileSync(join(original, filename)));
    }
  }
  const cordis = join(resources, 'app/dsh/node_modules/@deepseek-ai/cordis');
  mkdirSync(cordis, { recursive: true });
  writeFileSync(join(cordis, 'package.json'), readFileSync('node_modules/@deepseek-ai/cordis/package.json'));
  if (packed) {
    const bodies = []; let offset = 0;
    const walk = directory => ({ files: Object.fromEntries(readdirSync(directory, { withFileTypes: true }).map(entry => {
      if (entry.isDirectory()) return [entry.name, walk(join(directory, entry.name))];
      const bytes = readFileSync(join(directory, entry.name)); bodies.push(bytes);
      const metadata = { size: bytes.length, offset: String(offset) }; offset += bytes.length;
      return [entry.name, metadata];
    })) });
    const json = Buffer.from(JSON.stringify(walk(join(resources, 'app'))));
    const padding = Buffer.alloc((4 - ((json.length + 4) % 4)) % 4);
    const prefix = Buffer.alloc(16); prefix.writeUInt32LE(4, 0); prefix.writeUInt32LE(8 + json.length + padding.length, 4);
    prefix.writeUInt32LE(4 + json.length + padding.length, 8); prefix.writeUInt32LE(json.length, 12);
    writeFileSync(join(resources, 'app.asar'), Buffer.concat([prefix, json, padding, ...bodies]));
    rmSync(join(resources, 'app'), { recursive: true });
  }
  const profile = join(directory, 'profile'); mkdirSync(profile);
  writeFileSync(join(profile, 'cordis.yml'), '[]\n');
  const code = `import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('contract',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nprint(json.dumps(m.detect(sys.argv[2],sys.argv[3])))`;
  const detected = spawnSync(process.env.PYTHON ?? 'python3', ['-B', '-c', code, resolve('configure.py'), app, profile], { encoding: 'utf8' });
  assert.equal(detected.status, 0, detected.stderr);
  const result = JSON.parse(detected.stdout); assert.equal(result.supported, true, JSON.stringify(result.compatibility));
  assert.equal(result.compatibility.status, 'fingerprint_match');
  const connection = join(directory, 'connection.json');
  writeFileSync(connection, JSON.stringify({ connection_id: 'future-fixture', connection_token: 'fake-token', library_id: 'default', enabled: false, runtime_dir: join(directory, 'fake-runtime') }));
  return { directory, resources, version, options: { connection_file: connection, state_dir: join(directory, 'outbox'),
    host_version: version, host_contract: result.compatibility.descriptor } };
}

test('future version with identical installed runtime contract passes Python detection and real plugin startup', async () => {
  const f = installedFutureFixture();
  try { const adapter = new HostAdapter(f.options); await adapter.dispose(); }
  finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('packed Electron ASAR metadata and runtime code receive the same compatibility checks', async () => {
  const f = installedFutureFixture(true);
  try { const adapter = new HostAdapter(f.options); await adapter.dispose(); }
  finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('unknown version without proof, altered descriptor and code changed after detection fail before plugin starts', () => {
  const f = installedFutureFixture();
  try {
    assert.throws(() => new HostAdapter({ ...f.options, host_contract: undefined }), /contract could not be verified/);
    assert.throws(() => new HostAdapter({ ...f.options, host_contract: { ...f.options.host_contract, contract_id: 'forged' } }), /contract could not be verified/);
    assert.throws(() => new HostAdapter({ ...f.options, host_version: '99.2.0-another-build' }), /contract could not be verified/);
    writeFileSync(join(f.resources, 'app/dsh/node_modules/@deepseek-ai/dsh-session/lib/index.js'), '// actual installed contract changed');
    assert.throws(() => new HostAdapter(f.options), /contract could not be verified/);
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('a later installed release with unchanged reviewed code reconnects and reports its actual version', async () => {
  const f = installedFutureFixture();
  try {
    const expected = JSON.parse(readFileSync('host-contract-fingerprints.json', 'utf8'));
    const nextVersion = '99.2.0-next-fixture';
    for (const name of Object.keys(expected.packages)) {
      const manifest = join(f.resources, 'app/dsh/node_modules', name, 'package.json');
      writeFileSync(manifest, readFileSync(manifest, 'utf8').replaceAll(f.version, nextVersion));
    }
    const adapter = new HostAdapter(f.options);
    assert.equal(adapter.config.host_version, nextVersion);
    await adapter.dispose();
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});
