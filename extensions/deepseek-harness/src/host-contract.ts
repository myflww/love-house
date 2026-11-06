import { createHash } from 'node:crypto';
import { openSync, closeSync, readSync, readFileSync, statSync, existsSync, lstatSync, realpathSync } from 'node:fs';
import { isAbsolute, join, relative, sep } from 'node:path';
import fingerprints from '../host-contract-fingerprints.json' with { type: 'json' };
import capabilities from '../host-capabilities.json' with { type: 'json' };

export interface HostContractDescriptor {
  schema: 'love-house-harness-contract/v1'; host_version: string;
  contract_id: string; resources_path: string;
  layout?: 'node_modules';
}
const sha256 = (bytes: Buffer | string) => createHash('sha256').update(bytes).digest('hex');
function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
function normalizedMetadata(metadata: Record<string, any>) {
  const normalize = (value: any): any => typeof value === 'string' ? (value === metadata.version ? '$HOST_VERSION' : value)
    : Array.isArray(value) ? value.map(normalize)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)])) : value;
  return normalize(Object.fromEntries(fingerprints.metadata_keys.filter(key => key in metadata).map(key => [key, metadata[key]])));
}

/** Bounded metadata/code reads only. Never import or execute files selected by a descriptor. */
function resourceRead(resources: string, name: string, layout?: 'node_modules'): Buffer {
  if (layout === 'node_modules') {
    if (!name.startsWith('dsh/node_modules/')) throw new Error('Invalid SDK resource');
    const root = realpathSync(resources), path = realpathSync(join(root, name.slice('dsh/node_modules/'.length))), child = relative(root, path);
    if (child === '..' || child.startsWith('..' + sep) || isAbsolute(child) || statSync(path).size > 4 * 1024 * 1024) throw new Error('Resource escapes installation or exceeds limit');
    return readFileSync(path);
  }
  const loose = join(resources, 'app', name);
  if (existsSync(loose)) {
    const root = realpathSync(resources), path = realpathSync(loose), child = relative(root, path);
    if (child === '..' || child.startsWith('..' + sep) || isAbsolute(child) || statSync(path).size > 4 * 1024 * 1024) throw new Error('Resource escapes installation or exceeds limit');
    return readFileSync(path);
  }
  const archive = join(resources, 'app.asar');
  if (lstatSync(archive).isSymbolicLink()) throw new Error('Linked archive is not a contract source');
  // Electron exposes archive entries through fs; ordinary Node needs the
  // bounded raw reader below. Both paths read the same fixed SDK filenames.
  const archivedEntry = join(archive, name);
  if (existsSync(archivedEntry)) {
    if (statSync(archivedEntry).size > 4 * 1024 * 1024) throw new Error('Contract resource exceeds limit');
    return readFileSync(archivedEntry);
  }
  const fd = openSync(archive, 'r');
  try {
    const prefix = Buffer.alloc(16);
    if (readSync(fd, prefix, 0, 16, 0) !== 16) throw new Error('Invalid ASAR header');
    const headerSize = prefix.readUInt32LE(4), payloadSize = prefix.readUInt32LE(8), jsonSize = prefix.readUInt32LE(12);
    if (prefix.readUInt32LE(0) !== 4 || headerSize < 8 || headerSize > 32 * 1024 * 1024 || payloadSize + 4 !== headerSize || jsonSize < 1 || jsonSize > headerSize - 8) throw new Error('Invalid ASAR bounds');
    const header = Buffer.alloc(jsonSize);
    if (readSync(fd, header, 0, jsonSize, 16) !== jsonSize) throw new Error('Truncated ASAR header');
    let entry = JSON.parse(header.toString('utf8'));
    for (const part of name.split('/')) entry = entry?.files?.[part];
    const size = entry?.size, offset = Number(entry?.offset), position = 8 + headerSize + offset;
    if (!entry || entry.link || entry.unpacked || !Number.isSafeInteger(size) || size < 1 || size > 4 * 1024 * 1024 || !Number.isSafeInteger(offset) || offset < 0 || position + size > statSync(archive).size) throw new Error('Missing or invalid ASAR contract file');
    const body = Buffer.alloc(size);
    if (readSync(fd, body, 0, size, position) !== size) throw new Error('Truncated ASAR file');
    return body;
  } finally { closeSync(fd); }
}

/** Public declarations are compared by required shape, not bundled implementation bytes. */
const declarationShape = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\r\n]*/g, '').replace(/\s+/g, '');

function capabilityVersion(resources: string, layout?: 'node_modules'): string | null {
  const read = (path: string) => resourceRead(resources, path, layout);
  let actualVersion: string | undefined;
  for (const [name, expected] of Object.entries(capabilities.packages)) {
    const prefix = 'dsh/node_modules/' + name + '/';
    const metadata = JSON.parse(read(prefix + 'package.json').toString('utf8'));
    if (metadata.name !== name || metadata.type !== 'module' || typeof metadata.version !== 'string' || !metadata.version.trim()) return null;
    actualVersion ??= metadata.version;
    if (metadata.version !== actualVersion) return null;
    // A public declaration copied next to a missing implementation does not
    // establish a usable host. Packaged Electron builds omit .d.ts files.
    const main = metadata.main;
    if (typeof main !== 'string' || !main.endsWith('.js') || /^[\\/]/.test(main) || main.replace(/\\/g, '/').split('/').includes('..')) return null;
    const runtimeFiles = (expected as { runtime_files?: Record<string, string[]> }).runtime_files;
    const normalizedMain = main.replace(/^\.\//, '');
    const entry = metadata.exports?.['.'];
    const exported = typeof entry === 'string' ? entry : entry?.import ?? entry?.default;
    if (!runtimeFiles || !(normalizedMain in runtimeFiles) || typeof exported !== 'string'
        || exported.replace(/^\.\//, '') !== normalizedMain) return null;
    read(prefix + normalizedMain);
    let missingDeclarations = false;
    for (const [file, fragments] of Object.entries(expected.files)) {
      let declaration: Buffer;
      try { declaration = read(prefix + file); } catch { missingDeclarations = true; continue; }
      const source = declarationShape(declaration.toString('utf8'));
      if (!fragments.every(fragment => source.includes(declarationShape(fragment)))) return null;
    }
    if (missingDeclarations && !runtimeFiles) return null;
    for (const [file, fragments] of Object.entries(runtimeFiles ?? {})) {
      const source = declarationShape(read(prefix + file).toString('utf8'));
      if (!fragments.every(fragment => source.includes(declarationShape(fragment)))) return null;
    }
  }
  const cordis = JSON.parse(read('dsh/node_modules/@deepseek-ai/cordis/package.json').toString('utf8'));
  return cordis.name === '@deepseek-ai/cordis' && typeof cordis.version === 'string'
    && new RegExp('^' + capabilities.cordis_major + '\\.\\d+\\.\\d+(?:[-+].*)?$').test(cordis.version) ? actualVersion ?? null : null;
}

function legacyVersion(resources: string, layout?: 'node_modules'): string | null {
  const read = (path: string) => resourceRead(resources, path, layout);
  let actualVersion: string | undefined;
  for (const [name, expected] of Object.entries(fingerprints.packages)) {
    const prefix = 'dsh/node_modules/' + name + '/';
    const metadata = JSON.parse(read(prefix + 'package.json').toString('utf8'));
    if (metadata.name !== name || typeof metadata.version !== 'string' || !metadata.version || sha256(canonical(normalizedMetadata(metadata))) !== expected.metadata_sha256) return null;
    actualVersion ??= metadata.version;
    if (metadata.version !== actualVersion) return null;
    for (const [file, hash] of Object.entries(expected.files)) if (sha256(read(prefix + file)) !== hash) return null;
  }
  const cordis = JSON.parse(read('dsh/node_modules/@deepseek-ai/cordis/package.json').toString('utf8'));
  return cordis.name === '@deepseek-ai/cordis' && cordis.version === fingerprints.cordis_version ? actualVersion ?? null : null;
}

/** Recheck the installed SDK each load, including after an automatic host update. */
export function verifiedHostVersion(descriptor: unknown, _version: string): string | null {
  if (!descriptor || typeof descriptor !== 'object' || Array.isArray(descriptor)) return null;
  const value = descriptor as HostContractDescriptor;
  if (value.schema !== 'love-house-harness-contract/v1' || typeof value.host_version !== 'string' || !value.host_version.trim()
      || ![fingerprints.contract_id, capabilities.contract_id].includes(value.contract_id)
      || (value.layout !== undefined && value.layout !== 'node_modules')
      || typeof value.resources_path !== 'string' || !isAbsolute(value.resources_path)) return null;
  try {
    const compatible = capabilityVersion(value.resources_path, value.layout);
    if (compatible) return compatible;
  } catch { /* Older reviewed packages may only have the legacy proof files. */ }
  // Saved legacy descriptors retain their original exact-code compatibility
  // route. They can also use the current capability check above after updates.
  if (value.contract_id === fingerprints.contract_id) {
    try { return legacyVersion(value.resources_path, value.layout); } catch { return null; }
  }
  return null;
}
