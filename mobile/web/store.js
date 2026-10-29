/* Local-only mobile memory storage. No transport, models or executable imports. */
export const SHARE_FORMAT = 'love-house-memory-share/v1';
export const MAX_IMPORT_BYTES = 32 * 1024 * 1024;
export const MAX_NODES = 10000;
const MAX_ARCHIVES = 10000;
const MAX_EDGES = 100000;
const MAX_LIBRARIES = 50;
const MAX_TOTAL_BYTES = 64 * 1024 * 1024;
const SCHEMA = 'love-house-mobile-store/v1';
const RESERVED = new Set(['__proto__', 'constructor', 'prototype']);
const PRIVATE_KEYS = new Set(('apikey authorization proxyauthorization password passwd clientsecret accesstoken refreshtoken token secret secrets secretkey privatekey apitoken credentials credential credentialref keychain keychainref headers env environment provider providerid providerref baseurl runtime runtimedir outboxdir privatepath configpath hostoptions mcpservers connectionconfig clientkey sessionkey libraryid agentid path filepath localpath attachmentpath organizerprofile organizerlog companioningestion modelconfig modelsettings providerconfig agentconfig hookconfig hooks pluginconfig executableconfig commandconfig autostart').split(' '));
const META_KEYS = new Set(['created', 'updated', 'companion_profile', 'companion_persona', 'organizer_candidates', 'long_term_archive']);
const CONFIG_FIELDS = new Set(('half_life drop_below edge_max edge_half_life seed_floor steps damping retain k min_score hebbian_lr salience_bump auto_link_top recovery_days anchor_threshold important_threshold context_before context_after context_window_hours bridge_window_hours bridge_max_events max_nodes').split(' '));
const KEY_RE = /\b(?:sk-(?:proj-|ant-api\d+-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,}|AKIA[A-Z0-9]{16})\b/g;
const AUTH_RE = /\b(?:Bearer|Basic)\s+[A-Za-z0-9_+/.=-]{12,}/gi;
const ASSIGNMENT_RE = /(\b(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret|password)\s*[:=]\s*["']?)([A-Za-z0-9_./+=-]{12,})/gi;
const PATH_RE = /(^|[^\w:/])(?:file:\/\/)?\/(?:Users|home|private|var|Volumes|tmp|opt|Applications|etc|usr|sbin|bin|Library|System|dev|mnt|media|run|root|srv)\/[^\s<>"'，。；）)]+|\b[A-Za-z]:[\\/](?:Users|Documents and Settings|Program Files)[\\/][^\s<>"']+/g;
const URL_RE = /https?:\/\/[^\s<>"'，。；）)]+/g;
const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const scope = typeof window !== 'undefined' ? window : typeof global !== 'undefined' ? global : {};
const entriesObject = entries => entries.reduce((out, entry) => { Object.defineProperty(out, entry[0], { value: entry[1], enumerable: true, configurable: true, writable: true }); return out; }, {});
const otherwise = (value, fallback) => value === null || value === undefined ? fallback : value;
const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v) && [Object.prototype, null].includes(Object.getPrototypeOf(v));
const copy = v => v === undefined ? undefined : JSON.parse(JSON.stringify(v));
const now = () => Date.now() / 1000;
const compact = key => key.toLowerCase().replace(/[^a-z0-9]/g, '');

export class StoreError extends Error {
  constructor(code, message) { super(message); this.name = 'StoreError'; this.code = code; }
}
const invalid = message => { throw new StoreError('invalid_data', message); };

function validUnicode(text) {
  for (let i = 0; i < text.length; i++) {
    const n = text.charCodeAt(i);
    if (n >= 0xd800 && n <= 0xdbff) {
      const next = text.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
    } else if (n >= 0xdc00 && n <= 0xdfff) return false;
  }
  return true;
}
function text(value, name, limit, { empty = false, trim = false } = {}) {
  if (typeof value !== 'string' || !validUnicode(value) || value.length > limit || (!empty && !value.trim())) invalid(`${name}格式不正确或超过长度上限`);
  return trim ? value.trim() : value;
}
function jsonData(value, depth = 0, seen = new Set()) {
  if (depth > 40) invalid('JSON 嵌套过深');
  if (value === null || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) return;
  if (typeof value === 'string') { if (!validUnicode(value)) invalid('文件包含无法保存的字符'); return; }
  if ((!plain(value) && !Array.isArray(value)) || seen.has(value)) invalid('文件须为普通、有限数值的 JSON 数据');
  seen.add(value);
  for (const [key, item] of Object.entries(value)) { if (!validUnicode(key)) invalid('字段名包含无法保存的字符'); jsonData(item, depth + 1, seen); }
  seen.delete(value);
}
function bytes(value) { return new TextEncoder().encode(typeof value === 'string' ? value : JSON.stringify(value)).byteLength; }
function id(prefix) {
  if (!scope.crypto || !scope.crypto.getRandomValues) throw new StoreError('unsupported_browser', '当前浏览器缺少安全随机数功能，请使用较新的系统浏览器');
  const values = new Uint8Array(16); scope.crypto.getRandomValues(values);
  return prefix + Array.from(values, n => n.toString(16).padStart(2, '0')).join('');
}
async function sha256(value) {
  if (!scope.crypto || !scope.crypto.subtle) throw new StoreError('unsupported_browser', '导入导出需要安全浏览器环境（HTTPS 或应用内页面）');
  const digest = await scope.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
}
function stable(value) {
  if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
  if (plain(value)) return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + stable(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function emptyLibrary(name) {
  const ts = now();
  return { id: id('lib_'), name, created: ts, updated: ts,
    memory: { version: 1, name, config: {}, nodes: {}, edges: {}, meta: { created: ts, long_term_archive: true } }, archives: [] };
}
function initialState() { const library = emptyLibrary('默认记忆库'); return { schema: SCHEMA, revision: 0, selectedLibraryId: library.id, libraries: [library] }; }
function stateCheck(state) {
  if (!plain(state) || state.schema !== SCHEMA || !Array.isArray(state.libraries) || !state.libraries.length || state.libraries.length > MAX_LIBRARIES || !Number.isSafeInteger(state.revision)) throw new StoreError('storage_corrupt', '本地存档格式不完整，未重置或覆盖原数据');
  const ids = new Set();
  for (const lib of state.libraries) {
    if (!plain(lib) || !/^lib_[a-f0-9]{32}$/.test(lib.id) || ids.has(lib.id) || typeof lib.name !== 'string' || !plain(lib.memory) || !plain(lib.memory.nodes) || !plain(lib.memory.edges) || !Array.isArray(lib.archives)) throw new StoreError('storage_corrupt', '本地记忆库不完整，未重置或覆盖原数据');
    ids.add(lib.id);
  }
  if (!ids.has(state.selectedLibraryId)) throw new StoreError('storage_corrupt', '当前存档引用缺失，未创建空库替代');
  return state;
}
function library(state, libraryId) {
  const found = state.libraries.find(lib => lib.id === libraryId);
  if (!found) throw new StoreError('library_not_found', '记忆库不存在，请重新选择');
  return found;
}
function summary(lib, state) {
  return { id: lib.id, name: lib.name, created: lib.created, updated: lib.updated,
    createdAt: lib.created * 1000, updatedAt: lib.updated * 1000, nodeCount: Object.keys(lib.memory.nodes).length,
    memoryCount: Object.keys(lib.memory.nodes).length, selected: state.selectedLibraryId === lib.id };
}
function memoryView(node) {
  return { id: node.id, title: node.label, text: node.text, assistant: node.meta && typeof node.meta.assistant_reply === 'string' ? node.meta.assistant_reply : '', tags: copy(node.tags || []), kind: node.kind,
    meta: copy(node.meta || {}), created: node.created, updated: otherwise(node.updated, node.created),
    createdAt: node.created * 1000, updatedAt: otherwise(node.updated, node.created) * 1000,
    status: node.meta && node.meta.memory_disabled ? 'disabled' : node.valid_to || node.superseded_by ? 'historical' : 'active' };
}
function storageFailure(error) {
  if (error instanceof StoreError) return error;
  const quota = error && error.name === 'QuotaExceededError';
  return new StoreError(quota ? 'storage_full' : 'storage_unavailable', quota ? '本地空间不足，保存未完成；原有记忆未改动，请先导出备份' : '当前环境无法持久保存数据，请检查浏览器存储权限；未切换到临时存储');
}

/** Explicit test adapter. Production never falls back to this implementation. */
export function createMemoryAdapter(seed = null) {
  let state = copy(seed), queue = Promise.resolve();
  return {
    read() { return queue.then(() => copy(state)); },
    transact(mutator) {
      const operation = queue.then(() => {
        const result = mutator(copy(state));
        if (!result || !own(result, 'state') || result.then) throw new TypeError('A storage mutation must be synchronous');
        state = copy(result.state); return copy(result.value);
      });
      queue = operation.catch(() => {}); return operation;
    }
  };
}

export function createIndexedDBAdapter({ indexedDB = scope.indexedDB, name = 'love-house-mobile-v1' } = {}) {
  let opening;
  function open() {
    if (!indexedDB || !indexedDB.open) return Promise.reject(new StoreError('storage_unavailable', '此环境不支持 IndexedDB 持久存储，未启用临时或 localStorage 替代'));
    if (!opening) opening = new Promise((resolve, reject) => {
      let request;
      try { request = indexedDB.open(name, 1); } catch (error) { reject(storageFailure(error)); return; }
      let refused = false;
      request.onupgradeneeded = () => { if (!request.result.objectStoreNames.contains('documents')) request.result.createObjectStore('documents'); };
      request.onblocked = () => { refused = true; reject(new StoreError('storage_busy', '另一个窗口正在使用旧版存储，请关闭后重试')); };
      request.onerror = () => reject(storageFailure(request.error));
      request.onsuccess = () => {
        const db = request.result;
        if (refused) { db.close(); return; }
        db.onversionchange = () => { db.close(); opening = undefined; };
        resolve(db);
      };
    }).catch(error => { opening = undefined; throw error; });
    return opening;
  }
  async function transact(mutator, write) {
    const db = await open();
    return new Promise((resolve, reject) => {
      let tx, value, failure;
      try { tx = db.transaction('documents', write ? 'readwrite' : 'readonly'); } catch (error) { reject(storageFailure(error)); return; }
      const bucket = tx.objectStore('documents'), request = bucket.get('state');
      request.onsuccess = () => {
        try {
          const result = mutator(copy(otherwise(request.result, null)));
          if (result && result.then) throw new TypeError('IndexedDB mutation must be synchronous');
          value = copy(write ? result.value : result);
          if (write) bucket.put(result.state, 'state');
        } catch (error) { failure = error; tx.abort(); }
      };
      tx.oncomplete = () => resolve(value);
      tx.onabort = () => reject(failure instanceof StoreError ? failure : storageFailure(failure || tx.error));
      tx.onerror = () => {}; // onabort owns the rejected promise and original state remains atomic.
    });
  }
  return { read: () => transact(v => v, false), transact: mutator => transact(mutator, true), close: async () => { const db = await open(); db.close(); opening = undefined; } };
}

function references(node) {
  const meta = node.meta || {}, atom = plain(meta.memory_atom) ? meta.memory_atom : {}, refs = new Set();
  for (const key of ['members', 'source_ids']) if (Array.isArray(meta[key])) for (const value of meta[key]) if (typeof value === 'string') refs.add(value);
  for (const items of [meta.organizer_evidence, meta.organizer_sources, atom.evidence]) if (Array.isArray(items)) for (const e of items) if (plain(e) && typeof e.id === 'string') refs.add(e.id);
  if (typeof meta.corrects === 'string') refs.add(meta.corrects);
  return refs;
}
function dependentIds(nodes, start) {
  const blocked = new Set(start), dependents = new Map();
  for (const [nid, node] of Object.entries(nodes)) for (const ref of references(node)) { if (!dependents.has(ref)) dependents.set(ref, []); dependents.get(ref).push(nid); }
  const queue = [...blocked];
  for (let i = 0; i < queue.length; i++) for (const nid of dependents.get(queue[i]) || []) if (!blocked.has(nid)) { blocked.add(nid); queue.push(nid); }
  return blocked;
}
function receiptIds(value, out = new Set()) {
  if (Array.isArray(value)) for (const child of value) receiptIds(child, out);
  else if (plain(value)) for (const [key, child] of Object.entries(value)) {
    if (['archive_receipt_id', 'receipt_id'].includes(key) && typeof child === 'string') out.add(child);
    else receiptIds(child, out);
  }
  return out;
}
function removeTextCopies(lib, forgotten) {
  const values = [...forgotten].filter(Boolean).sort((a, b) => b.length - a.length);
  const identities = new Set(['id', 'kind', 'session_id', 'source', 'source_id', 'source_ids', 'members', 'connection_id', 'superseded_by', 'receipt_id', 'archive_receipt_id']);
  const redact = (value, key = '') => {
    if (identities.has(key)) return value;
    if (typeof value === 'string') {
      for (const original of values) value = original.length > 3 ? value.split(original).join('[用户已删除]') : value === original ? '[用户已删除]' : value;
      return value;
    }
    if (Array.isArray(value)) return value.map(child => redact(child));
    if (plain(value)) return entriesObject(Object.entries(value).map(([k, child]) => [k, redact(child, k)]));
    return value;
  };
  // Imported candidates and persona history can contain a second copy of evidence.
  delete lib.memory.meta.organizer_candidates;
  delete lib.memory.meta.companion_persona;
  lib.memory.meta = redact(lib.memory.meta);
  for (const node of Object.values(lib.memory.nodes)) for (const key of ['label', 'text', 'tags', 'meta', 'anchor_info']) if (own(node, key)) node[key] = redact(node[key]);
  for (const row of lib.archives) row.record = redact(row.record);
}
function validateGraph(memory) {
  if (!plain(memory) || memory.version !== 1 || !plain(memory.nodes) || !plain(memory.edges) || !plain(memory.meta || {})) invalid('分享文件的记忆图谱不完整');
  const nodes = Object.entries(memory.nodes), edges = Object.entries(memory.edges);
  if (nodes.length > MAX_NODES || edges.length > MAX_EDGES) invalid('手机版最多导入一万个节点和十万条关系，请先在桌面分库');
  for (const [nid, node] of nodes) {
    text(nid, '节点编号', 300);
    if (nid.includes('|') || RESERVED.has(nid) || /[\u0000-\u001f]/.test(nid) || nid.match(KEY_RE) || nid.match(PATH_RE)) invalid('记忆节点编号不正确');
    if (!plain(node) || node.id !== nid || !plain(node.meta) || typeof node.text !== 'string' || typeof node.label !== 'string' || !node.label.trim() || typeof node.kind !== 'string' || !node.kind.trim()) invalid('记忆节点资料不完整');
    for (const field of ['created', 'reinforced', 'salience']) if (typeof node[field] !== 'number' || !Number.isFinite(node[field])) invalid('记忆节点时间或强度不正确');
    if (node.salience < 0 || node.salience > 1 || (node.tags !== undefined && (!Array.isArray(node.tags) || node.tags.some(v => typeof v !== 'string')))) invalid('记忆节点标签或强度不正确');
    for (const field of ['updated', 'decay_at', 'valid_from', 'valid_to', 'event_at']) if (node[field] != null && (typeof node[field] !== 'number' || !Number.isFinite(node[field]))) invalid('记忆节点时间不正确');
    for (const field of ['impact', 'recalls']) if (node[field] !== undefined && (typeof node[field] !== 'number' || !Number.isFinite(node[field]))) invalid('记忆节点计数不正确');
    if (node.anchor_info != null && (!plain(node.anchor_info) || (node.anchor_info.context_snippets !== undefined && (!Array.isArray(node.anchor_info.context_snippets) || node.anchor_info.context_snippets.some(s => !plain(s) || typeof s.id !== 'string'))))) invalid('记忆锚点引用格式不正确');
  }
  for (const [key, edge] of edges) {
    const ends = key.split('|');
    if (ends.length !== 2 || !ends.every(n => own(memory.nodes, n)) || !plain(edge) || typeof edge.w !== 'number' || edge.w < 0 || edge.w >= 1 || !Number.isFinite(edge.w)) invalid('记忆关系不完整或包含悬空引用');
    for (const field of ['last', 'decay_at', 'valid_from', 'valid_to', 'n']) if (edge[field] != null && (typeof edge[field] !== 'number' || !Number.isFinite(edge[field]))) invalid('记忆关系时间或计数不正确');
  }
  const config = memory.config || {};
  if (!plain(config)) invalid('记忆配置格式不正确');
  for (const [key, value] of Object.entries(config)) {
    if (!CONFIG_FIELDS.has(key)) continue;
    if (key === 'half_life') {
      if (!plain(value) || Object.values(value).some(n => n !== null && (typeof n !== 'number' || !Number.isFinite(n) || n <= 0))) invalid('记忆半衰期配置不正确');
    } else if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) invalid('记忆配置包含无效数值');
    else if (['drop_below', 'edge_max', 'seed_floor', 'damping', 'retain', 'min_score', 'hebbian_lr', 'salience_bump', 'anchor_threshold', 'important_threshold'].includes(key) && (value > 1 || (['drop_below', 'edge_max', 'anchor_threshold', 'important_threshold'].includes(key) && value === 0) || (['drop_below', 'edge_max'].includes(key) && value === 1))) invalid('记忆配置数值超出范围');
    else if (['steps', 'k', 'auto_link_top', 'context_before', 'context_after', 'bridge_max_events', 'max_nodes'].includes(key) && (!Number.isInteger(value) || (['steps', 'k', 'max_nodes'].includes(key) && value < 1))) invalid('记忆计数配置不正确');
    else if (['edge_half_life', 'recovery_days', 'context_window_hours', 'bridge_window_hours'].includes(key) && value <= 0) invalid('记忆时间配置不正确');
  }
}

async function portable(memory, archives, name) {
  validateGraph(memory);
  const tomb = (memory.meta && memory.meta.memory_tombstones) || {}, start = Array.isArray(tomb.node_ids) ? tomb.node_ids : [];
  const blocked = dependentIds(memory.nodes, [...start, ...Object.entries(memory.nodes).filter(([, n]) => n.meta.forgotten || n.meta.memory_forgotten).map(([nid]) => nid)]);
  const rawBlocked = new Set(Array.isArray(tomb.raw_ids) ? tomb.raw_ids : []), forgottenHashes = new Set(Array.isArray(tomb.text_hashes) ? tomb.text_hashes : []);
  const aliases = new Map(), stringValues = new Set(), forgotten = new Set();
  function scan(v) {
    if (typeof v === 'string') stringValues.add(v);
    else if (Array.isArray(v)) v.forEach(scan);
    else if (plain(v)) for (const [key, value] of Object.entries(v)) { if (compact(key) === 'connectionid' && typeof value === 'string') aliases.set(value, null); scan(value); }
  }
  scan(memory); scan(archives);
  for (const key of aliases.keys()) aliases.set(key, 'shared_source_' + (await sha256(key)).slice(0, 20));
  if (forgottenHashes.size) for (const value of stringValues) if (forgottenHashes.has(await sha256(value))) forgotten.add(value);
  const counts = { credential_fields: 0, credential_texts: 0, local_paths: 0, url_parameters: 0, forgotten_texts: 0 };
  function redact(value) {
    if (forgotten.has(value)) { counts.forgotten_texts++; return '[用户已忘记]'; }
    value = value.replace(KEY_RE, () => { counts.credential_texts++; return '[密钥已隐藏]'; })
      .replace(AUTH_RE, () => { counts.credential_texts++; return '[认证信息已隐藏]'; })
      .replace(ASSIGNMENT_RE, (_, prefix) => { counts.credential_texts++; return prefix + '[密钥已隐藏]'; })
      .replace(PATH_RE, (_, prefix) => { counts.local_paths++; return (prefix || '') + '[本机路径已隐藏]'; });
    return value.replace(URL_RE, match => {
      try { const u = new URL(match); if (u.username || u.password) { counts.credential_texts++; return '[带认证信息的链接已隐藏]'; } if (u.search || u.hash) { counts.url_parameters++; u.search = ''; u.hash = ''; return u.href; } }
      catch { counts.credential_texts++; return '[链接已隐藏]'; }
      return match;
    });
  }
  function scrub(value) {
    if (typeof value === 'string') return redact(value);
    if (Array.isArray(value)) return value.map(scrub);
    if (plain(value)) {
      const out = {};
      for (const [key, child] of Object.entries(value)) {
        if (RESERVED.has(key) || PRIVATE_KEYS.has(compact(key))) { counts.credential_fields++; continue; }
        out[key] = compact(key) === 'connectionid' && typeof child === 'string' ? aliases.get(child) : scrub(child);
      }
      return out;
    }
    return value;
  }
  const nodes = {};
  for (const [nid, node] of Object.entries(memory.nodes)) if (!blocked.has(nid)) nodes[nid] = scrub(node);
  const edges = {};
  for (const [key, edge] of Object.entries(memory.edges)) if (key.split('|').every(n => own(nodes, n))) edges[key] = scrub(edge);
  const meta = scrub(entriesObject(Object.entries(memory.meta || {}).filter(([key]) => META_KEYS.has(key))));
  meta.long_term_archive = true;
  const graph = { version: 1, name: redact(name), config: scrub(entriesObject(Object.entries(memory.config || {}).filter(([key]) => CONFIG_FIELDS.has(key)))), nodes, edges, meta };
  const rows = [];
  for (const row of archives) {
    if (row.status === 'forgotten' || rawBlocked.has(row.id) || row.node_ids.some(n => blocked.has(n))) continue;
    rows.push({ id: row.id, session_id: redact(row.session_id || ''), kind: redact(row.kind || 'event'), status: row.status,
      received: otherwise(row.received, null), applied: otherwise(row.applied, null), node_ids: row.node_ids.filter(n => own(nodes, n)), record: scrub(row.record) });
  }
  validateGraph(graph);
  const packageCounts = { node_count: Object.keys(nodes).length, edge_count: Object.keys(edges).length, archive_count: rows.length,
    disabled_count: Object.values(nodes).filter(n => n.meta && n.meta.memory_disabled).length, superseded_count: Object.values(nodes).filter(n => n.valid_to || n.superseded_by).length };
  const result = { format: SHARE_FORMAT, name: graph.name, created: now(), scope: 'single_library', memory: graph, archives: rows, counts: packageCounts,
    privacy: { includes_keys: false, includes_connections: false, includes_local_paths: false, redactions: counts, requires_user_review: true,
      note: '自动隐藏可识别的凭据与本机路径；正文可能含个人经历，分享前请检查。' } };
  result.content_revision = await sha256(stable({ name: result.name, memory: graph, archives: rows, counts: packageCounts, privacy: result.privacy }));
  if (bytes(result) > MAX_IMPORT_BYTES) invalid('分享包超过手机版 32MiB 上限，请先分库整理');
  return result;
}

async function parseShare(raw) {
  let value;
  if (typeof raw === 'string') {
    if (!validUnicode(raw) || bytes(raw) > MAX_IMPORT_BYTES) invalid('导入文件须为不超过 32MiB 的完整 JSON');
    try { value = JSON.parse(raw); } catch { invalid('文件不是完整的 JSON，原有记忆未改动'); }
  } else value = raw;
  jsonData(value);
  if (bytes(value) > MAX_IMPORT_BYTES || !plain(value) || value.format !== SHARE_FORMAT || value.scope !== 'single_library') invalid('请选择爱之屋的单库 JSON 分享文件');
  text(value.name, '记忆库名称', 80);
  if (typeof otherwise(value.created, 0) !== 'number' || !Number.isFinite(otherwise(value.created, 0)) || !Array.isArray(value.archives) || value.archives.length > MAX_ARCHIVES) invalid('原始档案格式不正确');
  validateGraph(value.memory);
  const ids = new Set();
  for (const row of value.archives) {
    if (!plain(row) || typeof row.id !== 'string' || !row.id || row.id.length > 300 || ids.has(row.id) || !plain(row.record) || !Array.isArray(row.node_ids) || row.node_ids.some(n => typeof n !== 'string') || typeof otherwise(row.session_id, '') !== 'string' || !['saved', 'archived', 'pending', 'retry', 'forgotten'].includes(row.status)) invalid('原始事件档案不完整或编号重复');
    for (const field of ['received', 'applied']) if (row[field] != null && (typeof row[field] !== 'number' || !Number.isFinite(row[field]))) invalid('原始档案时间不正确');
    ids.add(row.id);
  }
  return portable(copy(value.memory), copy(value.archives), value.name);
}

export function createStore({ adapter = createIndexedDBAdapter() } = {}) {
  let initialization;
  function initialize() {
    if (!initialization) initialization = adapter.transact(state => {
      const next = state === null ? initialState() : stateCheck(state);
      return { state: next, value: { selectedLibraryId: next.selectedLibraryId, libraries: next.libraries.map(lib => summary(lib, next)) } };
    }).catch(error => { initialization = undefined; throw storageFailure(error); });
    return initialization;
  }
  async function read() { await initialize(); return stateCheck(await adapter.read()); }
  async function mutate(action) {
    await initialize();
    try { return await adapter.transact(state => { stateCheck(state); const value = action(state); state.revision++; if (bytes(state) > MAX_TOTAL_BYTES) throw new StoreError('storage_full', '手机端数据超过 64MiB 上限，保存未完成，请先导出备份并分库'); return { state, value }; }); }
    catch (error) { throw storageFailure(error); }
  }
  return {
    async init() { const state = await read(); return { selectedLibraryId: state.selectedLibraryId, libraries: state.libraries.map(lib => summary(lib, state)) }; },
    async listLibraries() { const state = await read(); return state.libraries.map(lib => summary(lib, state)); },
    async createLibrary(name) {
      name = text(name, '记忆库名称', 80, { trim: true });
      return mutate(state => { if (state.libraries.length >= MAX_LIBRARIES) invalid('手机版最多保留 50 个记忆库'); const lib = emptyLibrary(name); state.libraries.push(lib); state.selectedLibraryId = lib.id; return summary(lib, state); });
    },
    async selectLibrary(libraryId) { return mutate(state => { const lib = library(state, libraryId); state.selectedLibraryId = lib.id; return summary(lib, state); }); },
    async listMemories(libraryId, { query = '' } = {}) {
      text(query, '检索文字', 500, { empty: true });
      const lib = library(await read(), libraryId), terms = query.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
      return Object.values(lib.memory.nodes).map(memoryView).filter(n => { const haystack = [n.title, n.text, n.assistant, ...n.tags].join('\n').normalize('NFKC').toLocaleLowerCase(); return terms.every(term => haystack.includes(term)); }).sort((a, b) => b.updated - a.updated || b.created - a.created || a.id.localeCompare(b.id));
    },
    async saveMemory(libraryId, input) {
      if (!plain(input)) invalid('记忆资料不正确');
      const title = text(input.title, '标题', 100, { trim: true }), body = text(input.text, '记忆原文', 200000);
      if (input.assistant !== undefined) text(input.assistant, '助手原文', 200000, { empty: true });
      if (input.tags !== undefined && (!Array.isArray(input.tags) || input.tags.length > 20)) invalid('标签最多 20 项');
      const tags = input.tags === undefined ? undefined : input.tags.map(tag => text(tag, '标签', 40, { trim: true }));
      return mutate(state => {
        const lib = library(state, libraryId), ts = now(), exists = input.id !== undefined;
        if (exists && !own(lib.memory.nodes, input.id)) throw new StoreError('memory_not_found', '记忆不存在，未创建替代记录');
        if (!exists && Object.keys(lib.memory.nodes).length >= MAX_NODES) invalid('手机版每库最多一万个节点');
        const nid = exists ? input.id : id('n_');
        const node = exists ? lib.memory.nodes[nid] : { id: nid, kind: 'episode', label: '', text: '', tags: [], created: ts, reinforced: ts,
          decay_at: ts, salience: 0.6, impact: 0, recalls: 0, valid_from: ts, valid_to: null, superseded_by: null, event_at: ts,
          event_recorded: true, event_explicit: false, session_id: null, important: false, meta: { source: 'mobile_manual' } };
        node.label = title; node.text = body; node.updated = ts;
        if (tags !== undefined) node.tags = [...new Set(tags)];
        if (input.assistant !== undefined) node.meta.assistant_reply = input.assistant;
        if (exists) node.meta.mobile_edited_at = ts;
        lib.memory.nodes[nid] = node; lib.updated = ts; lib.memory.meta.updated = ts;
        return memoryView(node);
      });
    },
    async deleteMemory(libraryId, memoryId) {
      return mutate(state => {
        const lib = library(state, libraryId);
        if (!own(lib.memory.nodes, memoryId)) throw new StoreError('memory_not_found', '记忆不存在');
        const blocked = dependentIds(lib.memory.nodes, [memoryId]), receipts = new Set(), forgotten = new Set();
        for (const nid of blocked) if (own(lib.memory.nodes, nid)) {
          const node = lib.memory.nodes[nid]; receiptIds(node, receipts); forgotten.add(node.text);
          if (typeof node.meta.assistant_reply === 'string') forgotten.add(node.meta.assistant_reply);
          delete lib.memory.nodes[nid];
        }
        for (const [key] of Object.entries(lib.memory.edges)) if (key.split('|').some(n => blocked.has(n))) delete lib.memory.edges[key];
        for (const node of Object.values(lib.memory.nodes)) if (node.anchor_info && Array.isArray(node.anchor_info.context_snippets)) node.anchor_info.context_snippets = node.anchor_info.context_snippets.filter(s => !blocked.has(s.id));
        lib.archives = lib.archives.filter(row => !receipts.has(row.id) && !row.node_ids.some(n => blocked.has(n)));
        removeTextCopies(lib, forgotten);
        lib.updated = now(); lib.memory.meta.updated = lib.updated;
        return { deleted: true, affectedIds: [...blocked] };
      });
    },
    async exportLibrary(libraryId) {
      const lib = library(await read(), libraryId);
      return portable(copy(lib.memory), copy(lib.archives), lib.name);
    },
    async importLibrary(raw) {
      const prepared = await parseShare(raw);
      return mutate(state => {
        if (state.libraries.length >= MAX_LIBRARIES) invalid('手机版最多保留 50 个记忆库');
        const lib = emptyLibrary(prepared.name), remap = new Map(prepared.archives.map(row => [row.id, id('archive_')]));
        const rewrite = value => {
          if (Array.isArray(value)) return value.map(rewrite);
          if (plain(value)) return entriesObject(Object.entries(value).map(([key, child]) => [key, ['archive_receipt_id', 'receipt_id'].includes(key) && remap.has(child) ? remap.get(child) : rewrite(child)]));
          return value;
        };
        lib.memory = rewrite(prepared.memory); lib.memory.name = lib.name;
        lib.archives = prepared.archives.map(row => ({ ...rewrite(row), id: remap.get(row.id), status: row.node_ids.length ? 'saved' : 'archived' }));
        state.libraries.push(lib); state.selectedLibraryId = lib.id;
        const info = summary(lib, state), redactions = prepared.privacy.redactions;
        return { ...info, library: info, warnings: Object.values(redactions).some(Boolean) ? ['导入时已隐藏可识别凭据、连接配置或本机路径；原文中的个人经历仍需自行检查。'] : [], connectionsRebound: false, organizerEnabled: false };
      });
    },
    async close() { if (adapter.close) await adapter.close(); initialization = undefined; }
  };
}
