import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, readdirSync, cpSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { HostAdapter } from '../dist/index.js';

const profile = JSON.parse(readFileSync('host-capabilities.json', 'utf8'));
const legacy = JSON.parse(readFileSync('host-contract-fingerprints.json', 'utf8'));

function installedFutureFixture({ packed = false, stripped = false, npm = false } = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'love-house-future-contract-'));
  const app = npm ? join(directory, 'node_modules/@deepseek-ai/dsh') : join(directory, 'future app');
  const resources = npm ? join(directory, 'node_modules') : join(app, 'resources');
  const modules = npm ? resources : join(resources, 'app/dsh/node_modules');
  const version = '99.1.0-future-fixture';
  for (const name of Object.keys(profile.packages)) {
    const original = resolve('node_modules', name), destination = join(modules, name);
    mkdirSync(destination, { recursive: true });
    const source = JSON.parse(readFileSync(join(original, 'package.json'), 'utf8'));
    writeFileSync(join(destination, 'package.json'), JSON.stringify(source).replaceAll(source.version, version));
    // Only public compiled SDK artifacts; no user configuration or profile.
    cpSync(join(original, 'lib'), join(destination, 'lib'), { recursive: true });
    if (stripped) {
      const prune = path => {
        for (const entry of readdirSync(path, { withFileTypes: true })) {
          const child = join(path, entry.name);
          if (entry.isDirectory()) prune(child);
          else if (entry.name.endsWith('.d.ts')) rmSync(child);
        }
      };
      prune(join(destination, 'lib'));
    }
  }
  const cordis = join(modules, '@deepseek-ai/cordis');
  mkdirSync(cordis, { recursive: true });
  writeFileSync(join(cordis, 'package.json'), JSON.stringify({ name: '@deepseek-ai/cordis', version: '4.1.0' }));
  if (npm) {
    mkdirSync(join(app, 'lib'), { recursive: true });
    writeFileSync(join(app, 'package.json'), JSON.stringify({ name: '@deepseek-ai/dsh', version, bin: { dsh: 'lib/bin.js' } }));
    writeFileSync(join(app, 'lib/bin.js'), '// synthetic CLI entry; never executed\n');
  }
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
  const privateProfile = join(directory, 'profile'); mkdirSync(privateProfile);
  writeFileSync(join(privateProfile, 'cordis.yml'), '[]\n');
  const code = `import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('contract',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nprint(json.dumps(m.detect(sys.argv[2],sys.argv[3])))`;
  const detected = spawnSync(process.env.PYTHON ?? 'python3', ['-B', '-c', code, resolve('configure.py'), app, privateProfile], { encoding: 'utf8' });
  assert.equal(detected.status, 0, detected.stderr);
  const result = JSON.parse(detected.stdout); assert.equal(result.supported, true, JSON.stringify(result.compatibility));
  assert.equal(result.compatibility.status, 'capability_match');
  const connection = join(directory, 'connection.json');
  writeFileSync(connection, JSON.stringify({ connection_id: 'future-fixture', connection_token: 'fake-token', library_id: 'default', enabled: false, runtime_dir: join(directory, 'fake-runtime') }));
  return { directory, resources, modules, version, options: { connection_file: connection, state_dir: join(directory, 'outbox'),
    host_version: version, host_contract: result.compatibility.descriptor } };
}

for (const options of [{}, { packed: true }, { stripped: true }, { packed: true, stripped: true }, { npm: true }]) {
  test(`compatible future public APIs pass Python detection and plugin startup ${JSON.stringify(options)}`, async () => {
    const f = installedFutureFixture(options);
    try { const adapter = new HostAdapter(f.options); assert.equal(adapter.config.host_version, f.version); await adapter.dispose(); }
    finally { rmSync(f.directory, { recursive: true, force: true }); }
  });
}

test('unknown version without capability proof and forged descriptor fail before startup', () => {
  const f = installedFutureFixture();
  try {
    assert.throws(() => new HostAdapter({ ...f.options, host_contract: undefined }), /contract could not be verified/);
    for (const changes of [{ contract_id: 'forged' }, { schema: 'other' }, { resources_path: 'relative/install' }, { layout: 'arbitrary' }]) {
      assert.throws(() => new HostAdapter({ ...f.options, host_contract: { ...f.options.host_contract, ...changes } }), /contract could not be verified/);
    }
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('changed required public declarations are rejected even when runtime markers remain', () => {
  const f = installedFutureFixture();
  try {
    const path = join(f.modules, '@deepseek-ai/dsh-session/lib/types/index.d.ts');
    writeFileSync(path, readFileSync(path, 'utf8').replaceAll("'session/event'", "'session/changed'"));
    assert.throws(() => new HostAdapter(f.options), /contract could not be verified/);
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('packaged SDK without declarations still requires actual consumed runtime hooks', () => {
  const f = installedFutureFixture({ stripped: true });
  try {
    writeFileSync(join(f.modules, '@deepseek-ai/dsh-session/lib/index.js'), '// incompatible SDK: required hooks removed\n');
    assert.throws(() => new HostAdapter(f.options), /contract could not be verified/);
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('unrelated implementation changes and additive public fields do not invalidate compatibility', async () => {
  const f = installedFutureFixture();
  try {
    const runtime = join(f.modules, '@deepseek-ai/dsh-session/lib/index.js');
    writeFileSync(runtime, readFileSync(runtime, 'utf8') + '\n// independently changed implementation detail\n');
    const declaration = join(f.modules, '@deepseek-ai/dsh-agent/lib/types/runtime-types.d.ts');
    writeFileSync(declaration, readFileSync(declaration, 'utf8').replace('messages: UserMessage[];', 'messages: UserMessage[]; futureContext?: string;'));
    const adapter = new HostAdapter(f.options); await adapter.dispose();
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

test('compatible host update reconnects from stale config and legacy descriptor and reports actual version', async () => {
  const f = installedFutureFixture();
  try {
    const nextVersion = '99.2.0-next-fixture';
    for (const name of Object.keys(profile.packages)) {
      const manifest = join(f.modules, name, 'package.json');
      writeFileSync(manifest, readFileSync(manifest, 'utf8').replaceAll(f.version, nextVersion));
    }
    for (const contract_id of [profile.contract_id, legacy.contract_id]) {
      const adapter = new HostAdapter({ ...f.options, host_contract: { ...f.options.host_contract, contract_id } });
      assert.equal(adapter.config.host_version, nextVersion); await adapter.dispose();
    }
  } finally { rmSync(f.directory, { recursive: true, force: true }); }
});

for (const fault of ['mixed-version', 'wrong-name', 'wrong-entry', 'cordis-major']) {
  test(`SDK identity and runtime capability boundaries reject ${fault}`, () => {
    const f = installedFutureFixture();
    try {
      const name = fault === 'cordis-major' ? '@deepseek-ai/cordis' : '@deepseek-ai/dsh-session';
      const file = join(f.modules, name, 'package.json'), metadata = JSON.parse(readFileSync(file, 'utf8'));
      if (fault === 'mixed-version') metadata.version = '99.8.0-incompatible-mix';
      if (fault === 'wrong-name') metadata.name = '@another/sdk';
      if (fault === 'wrong-entry') metadata.main = '../outside.js';
      if (fault === 'cordis-major') metadata.version = '5.0.0';
      writeFileSync(file, JSON.stringify(metadata));
      assert.throws(() => new HostAdapter(f.options), /contract could not be verified/);
    } finally { rmSync(f.directory, { recursive: true, force: true }); }
  });
}
