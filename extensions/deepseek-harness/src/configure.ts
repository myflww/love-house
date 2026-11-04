import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, copyFileSync, chmodSync, lstatSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { parseDocument, isMap, isSeq } from 'yaml';
import { SUPPORTED_HOSTS, expandHome, type ConnectionConfig } from './runtime.ts';

const OWNER = 'neural-knowledge-host';
export interface ConfigureInput {
  app_path?: string; profile_dir?: string; home_dir?: string; install_dir?: string;
  connection?: ConnectionConfig; mode?: 'host' | 'proxy'; proxy_session_id?: string;
}
export function detectHarness(input: ConfigureInput = {}) {
  const home = input.home_dir ? resolve(input.home_dir) : homedir();
  const app = input.app_path ? expandHome(input.app_path) : [`/Applications/DeepSeek Harness.app`, join(home, 'Applications/DeepSeek Harness.app')].find(existsSync);
  let version: string | null = null;
  if (app && existsSync(join(app, 'Contents/Info.plist'))) {
    const info = JSON.parse(execFileSync('/usr/bin/plutil', ['-convert', 'json', '-o', '-', join(app, 'Contents/Info.plist')], { encoding: 'utf8' }));
    version = info.CFBundleShortVersionString ?? info.CFBundleVersion ?? null;
  }
  const profile = input.profile_dir ? expandHome(input.profile_dir) : join(home, '.dsh/profiles/desktop');
  return { app_path: app ?? null, version, supported: !!version && SUPPORTED_HOSTS.includes(version),
    profile_dir: profile, profile_source: input.profile_dir ? 'explicit' : 'desktop-default',
    patch_file: join(profile, 'cordis.patch.yml'), profile_exists: existsSync(join(profile, 'cordis.yml')),
    supported_versions: SUPPORTED_HOSTS, node_command: app && existsSync(join(app, 'Contents/Resources/runtime/bin/node')) ? join(app, 'Contents/Resources/runtime/bin/node') : process.execPath };
}

function checkConnection(value?: ConnectionConfig): ConnectionConfig {
  if (!value || ['connection_id', 'connection_token', 'library_id'].some(key => typeof (value as any)[key] !== 'string' || !(value as any)[key].trim())) throw new Error('A backend-created connection_id/token/library_id is required');
  if (value.base_url) {
    const url = new URL(value.base_url); const local = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
    if (url.username || url.password || url.search || url.hash || (!local && (!value.allow_remote || url.protocol !== 'https:'))) throw new Error('Unsafe or unapproved controller URL');
  }
  return value;
}

export function plan(input: ConfigureInput) {
  const detected = detectHarness(input); const connection = checkConnection(input.connection);
  const mode = input.mode ?? 'host';
  if (mode === 'host' && !detected.supported) throw new Error('Harness version is not source-verified; choose the explicit wire-only API proxy fallback or validate host compatibility');
  if (mode === 'host' && !detected.profile_exists) throw new Error('Desktop profile is absent; start Harness once or explicitly select the intended profile');
  const installation = input.install_dir ? expandHome(input.install_dir) : join(detected.profile_dir, '.neural-knowledge');
  const idHash = createHash('sha256').update(connection.connection_id).digest('hex').slice(0, 16);
  const configFile = join(installation, `connection-${idHash}.json`);
  const entry = { id: `${OWNER}-${idHash}`, name: pathToFileURL(join(installation, 'index.js')).href,
    config: { managed_by: OWNER, connection_file: configFile, host_version: detected.version } };
  return { mode, detected, install_dir: installation, connection_file: configFile,
    overlay_file: join(installation, `neural-knowledge-host-${idHash}.overlay.yml`), patch_file: detected.patch_file,
    library_id: connection.library_id, connection_id: connection.connection_id, entry,
    capabilities: mode === 'host' ? { passive_committed_events: true, native_sessions: true, full_tool_results: true, context_injection: true }
      : { passive_committed_events: false, native_sessions: false, full_tool_results: false, context_injection: true, scope: 'Only provider HTTP traffic routed through the proxy; not a complete host archive' },
    changes: mode === 'host' ? ['Copy bundled plugin JS', 'Write a private connection file', 'Add/update only the owned Cordis patch entry; back up existing patch']
      : ['Copy wire-only proxy JS', 'Write private proxy configuration; host provider routing requires explicit setup'],
    credentials_read: false, auto_restart: false };
}

/** Modify only the reserved, explicitly owned entry; retain all other YAML AST nodes. */
export function patchOwnedEntry(source: string, entry: Record<string, any>) {
  const document = parseDocument(source || '[]\n', { strict: true, uniqueKeys: true });
  if (document.errors.length) throw new Error('Existing patch is invalid YAML; no changes made');
  if (!isSeq(document.contents)) throw new Error('Expected the official patch operation sequence; no changes made');
  let found = false;
  for (const operation of document.contents.items) {
    if (!isMap(operation)) continue;
    const inserted = operation.get('insert', true);
    if (!isSeq(inserted)) continue;
    for (let i = 0; i < inserted.items.length; i++) {
      const node = inserted.items[i];
      if (!isMap(node) || node.get('id') !== entry.id) continue;
      const config = node.get('config', true);
      if (!isMap(config) || config.get('managed_by') !== OWNER) throw new Error('Reserved plugin id belongs to an unrecognized entry; no changes made');
      if (found) throw new Error('Duplicate owned plugin entries; no changes made');
      inserted.items[i] = document.createNode(entry); found = true;
    }
  }
  if (!found) document.add({ insert: [entry] });
  return String(document);
}

function writePrivate(path: string, content: string) {
  if (existsSync(path) && lstatSync(path).isSymbolicLink()) throw new Error('Refusing to replace a symlink');
  const temporary = `${path}.${randomUUID()}.tmp`;
  writeFileSync(temporary, content, { mode: 0o600 }); renameSync(temporary, path); chmodSync(path, 0o600);
}

export function applyConfiguration(input: ConfigureInput) {
  const prepared = plan(input); const connection = checkConnection(input.connection);
  const sourceDir = dirname(fileURLToPath(import.meta.url));
  const needed = prepared.mode === 'host' ? 'index.js' : 'proxy.js';
  if (!existsSync(join(sourceDir, needed))) throw new Error('Build/distribute the extension first; source TypeScript is not a loader artifact');
  let existing = ''; let patched = ''; let backup: string | null = null;
  if (prepared.mode === 'host') {
    if (existsSync(prepared.patch_file) && lstatSync(prepared.patch_file).isSymbolicLink()) throw new Error('Refusing to edit a linked profile patch');
    existing = existsSync(prepared.patch_file) ? readFileSync(prepared.patch_file, 'utf8') : '[]\n';
    patched = patchOwnedEntry(existing, prepared.entry);
  }
  if (existsSync(prepared.install_dir) && (lstatSync(prepared.install_dir).isSymbolicLink() ||
      (readdirSync(prepared.install_dir).length > 0 && !existsSync(join(prepared.install_dir, 'managed.json'))))) throw new Error('Installation directory is linked or contains unrecognized files');
  mkdirSync(prepared.install_dir, { recursive: true, mode: 0o700 });
  writePrivate(join(prepared.install_dir, 'managed.json'), JSON.stringify({ managed_by: OWNER, version: '0.4.1' }));
  for (const file of ['index.js', 'configure.js', 'proxy.js', 'THIRD_PARTY_LICENSES.txt']) if (existsSync(join(sourceDir, file)) && resolve(sourceDir, file) !== resolve(prepared.install_dir, file)) copyFileSync(join(sourceDir, file), join(prepared.install_dir, file));
  writePrivate(prepared.connection_file, JSON.stringify(connection));
  writePrivate(join(prepared.install_dir, 'package.json'), JSON.stringify({ name: 'neural-knowledge-local-adapter', private: true, type: 'module' }));
  if (prepared.mode === 'host') {
    writePrivate(prepared.overlay_file, `# Owned Neural Knowledge entry; no token is embedded here.\n${JSON.stringify([{ insert: [prepared.entry] }], null, 2)}\n`);
    if (existsSync(prepared.patch_file)) {
      backup = `${prepared.patch_file}.neural-knowledge-${Date.now()}.backup`;
      copyFileSync(prepared.patch_file, backup); chmodSync(backup, 0o600);
    }
    writePrivate(prepared.patch_file, patched);
  } else {
    const proxyConfig = { connection_file: prepared.connection_file, session_id: input.proxy_session_id ?? `proxy-${connection.connection_id}`,
      host_version: 'api-proxy', listen_port: 0, upstream: 'https://api.deepseek.com' };
    writePrivate(join(prepared.install_dir, 'proxy.json'), JSON.stringify(proxyConfig));
  }
  return { ...prepared, applied: true, backup, requires_harness_reload: prepared.mode === 'host',
    proxy_command: prepared.mode === 'proxy' ? [prepared.detected.node_command, join(prepared.install_dir, 'proxy.js'), '--config', join(prepared.install_dir, 'proxy.json')] : undefined };
}

async function main() {
  const mode = process.argv[2] ?? 'detect';
  let input: ConfigureInput = {};
  if (!process.stdin.isTTY) { const chunks: Buffer[] = []; for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk)); const body = Buffer.concat(chunks).toString('utf8').trim(); if (body) input = JSON.parse(body); }
  // Connection tokens arrive on stdin and never appear in argv or returned plans.
  const result = mode === 'detect' ? detectHarness(input) : mode === 'plan' ? plan(input) : mode === 'apply' ? applyConfiguration(input) : (() => { throw new Error('Use detect, plan or apply'); })();
  process.stdout.write(JSON.stringify({ ok: true, result }) + '\n');
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stdout.write(JSON.stringify({ ok: false, error: (error as Error).message }) + '\n'); process.exitCode = 1; });
}
