import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, renameSync, unlinkSync, readdirSync, statSync, openSync, closeSync, fsyncSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import http from 'node:http';
import https from 'node:https';
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session';
import type { Agent, PreStepDecision } from '@deepseek-ai/dsh-agent';
import type { UserMessage, MessageId } from '@deepseek-ai/dsh-llm';

export const SOURCE_KIND = 'neural-knowledge-context';
export const SUPPORTED_HOSTS = ['0.2.1-rc.3', '0.2.1-rc.5'];
type JsonObject = Record<string, any>;
export interface ConnectionConfig {
  connection_id: string; connection_token: string; library_id: string;
  runtime_dir?: string; base_url?: string; allow_remote?: boolean;
  session_scope?: string;
  enabled?: boolean;
  connection_host?: 'harness' | 'agent';
}
export interface AdapterConfig {
  connection_file: string; host_version: string; state_dir?: string;
  retry_ms?: number; timeout_ms?: number;
}
export interface Envelope {
  session_id: string; event_id: string; event_type: string; seq: number; time: number;
  record: JsonObject;
}
export const expandHome = (path: string) => path.startsWith('~/') ? join(homedir(), path.slice(2)) : resolve(path);
const hash = (value: string) => createHash('sha256').update(value).digest('hex');
const object = (value: any): value is JsonObject => !!value && typeof value === 'object' && !Array.isArray(value);
const credential = (key: string) => /^(authorization|apikey|password|cookie|setcookie|accesstoken|refreshtoken|clientsecret|connectiontoken|deepseekapikey)$/i.test(key.replace(/[_\- ]/g, ''));

/** Remove explicit credential fields without rewriting a user's actual text. */
export function sanitize(value: any, paths: string[] = [], path = '$'): any {
  if (Array.isArray(value)) return value.map((item, i) => sanitize(item, paths, `${path}[${i}]`));
  if (!object(value)) return value;
  const result: JsonObject = {};
  for (const [key, item] of Object.entries(value)) {
    if (credential(key)) { paths.push(`${path}.${key}`); continue; }
    if (key === 'arguments' && typeof item === 'string') {
      try {
        const args = JSON.parse(item); const redactions: string[] = [];
        const cleaned = sanitize(args, redactions, `${path}.arguments`);
        result[key] = redactions.length ? JSON.stringify(cleaned) : item;
        paths.push(...redactions); continue;
      } catch { /* Unparseable provider arguments remain the actual source string. */ }
    }
    if (['image', 'file', 'audio'].includes(String(value.type)) && ['base64', 'bytes', 'data'].includes(key)) {
      paths.push(`${path}.${key}:attachment-bytes-not-captured`);
      result.omitted_bytes = true;
      if (typeof item === 'string') result.omitted_bytes_sha256 = hash(item);
      continue;
    }
    result[key] = sanitize(item, paths, `${path}.${key}`);
  }
  return result;
}

function atomicJson(path: string, value: unknown) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  const fd = openSync(temporary, 'wx', 0o600);
  try { writeFileSync(fd, JSON.stringify(value)); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(temporary, path);
}

function validateConnection(config: ConnectionConfig) {
  for (const key of ['connection_id', 'connection_token', 'library_id'] as const) {
    if (typeof config[key] !== 'string' || !config[key].trim() || /[\r\n]/.test(config[key])) throw new Error(`Missing/invalid ${key}`);
  }
  if (config.base_url) validateBase(config.base_url, config.allow_remote);
  return config;
}

function validateBase(base: string, allowRemote = false) {
  const url = new URL(base);
  const local = ['127.0.0.1', '[::1]', 'localhost'].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== '')) throw new Error('Unsafe controller base_url');
  if ((!local && (!allowRemote || url.protocol !== 'https:')) || !['http:', 'https:'].includes(url.protocol)) throw new Error('Remote controllers require explicit allow_remote and HTTPS');
  return url.origin;
}

/** Node's direct HTTP client intentionally does not use HTTP_PROXY/ALL_PROXY. */
export function requestJson(base: string, path: string, payload?: unknown, token?: string, timeout = 2500, signal?: AbortSignal): Promise<JsonObject> {
  const url = new URL(path, base); const data = payload === undefined ? undefined : Buffer.from(JSON.stringify(payload));
  return new Promise((resolveRequest, reject) => {
    const request = (url.protocol === 'https:' ? https : http).request(url, {
      method: data ? 'POST' : 'GET', signal,
      headers: { ...(data ? { 'content-type': 'application/json', 'content-length': data.length } : {}), ...(token ? { authorization: `Bearer ${token}` } : {}) },
    }, response => {
      const chunks: Buffer[] = []; let size = 0;
      response.on('data', chunk => { size += chunk.length; if (size > 8 * 1024 * 1024) request.destroy(new Error('Response too large')); else chunks.push(chunk); });
      response.on('end', () => {
        if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) { reject(new Error(`Controller HTTP ${response.statusCode}`)); return; }
        try { const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')); if (!object(parsed)) throw new Error('Not an object'); resolveRequest(parsed); }
        catch { reject(new Error('Invalid controller JSON')); }
      });
      response.on('error', () => reject(new Error('Controller response interrupted')));
    });
    request.setTimeout(timeout, () => request.destroy(new Error('Controller timeout')));
    request.on('error', error => reject(new Error(signal?.aborted ? 'Adapter disposed' : `Controller unavailable (${(error as NodeJS.ErrnoException).code ?? 'transport'})`)));
    request.end(data);
  });
}

export class Controller {
  readonly config: ConnectionConfig;
  constructor(config: ConnectionConfig, readonly timeout = 2500, readonly signal?: AbortSignal) { this.config = validateConnection(config); }
  async discover(): Promise<string> {
    if (this.config.base_url) {
      const base = validateBase(this.config.base_url, this.config.allow_remote);
      if ((await requestJson(base, '/api/health', undefined, undefined, this.timeout, this.signal)).ok !== true) throw new Error('Controller health failed');
      return base;
    }
    const directory = expandHome(this.config.runtime_dir ?? '~/Library/Application Support/NeuralKnowledge/.runtime');
    let files: { path: string; time: number }[] = [];
    try { files = readdirSync(directory).filter(name => name.endsWith('.json')).flatMap(name => { try { const path = join(directory, name); return [{ path, time: statSync(path).mtimeMs }]; } catch { return []; } }).sort((a, b) => b.time - a.time); } catch { /* Application is not running. */ }
    for (const { path } of files) {
      try {
        if (statSync(path).size > 16384) continue;
        const ready = JSON.parse(readFileSync(path, 'utf8'));
        if (!/^0\.4\./.test(ready.service_version ?? '') || !Number.isInteger(ready.controller_port) || ready.controller_port < 1 || ready.controller_port > 65535) continue;
        const base = `http://127.0.0.1:${ready.controller_port}`;
        if ((await requestJson(base, '/api/health', undefined, undefined, this.timeout, this.signal)).ok === true) return base;
      } catch { /* A stale ready entry is never a reason to choose a display port. */ }
    }
    throw new Error('Start Neural Knowledge 0.4.x with controller_port; older display/personal ports are not archive controllers');
  }
  async send(kind: 'events' | 'context' | 'heartbeat', payload: unknown) {
    const base = await this.discover();
    return requestJson(base, `/api/connections/${encodeURIComponent(this.config.connection_id)}/${kind}`, payload, this.config.connection_token, this.timeout, this.signal);
  }
}

type Turn = { number: number; started: boolean; interrupted: boolean; messages: JsonObject[]; calls: Map<string, string>; rawEvents?: JsonObject[] };
const claimsKey = Symbol.for('neural-knowledge.session-claims.v1');
const sessionClaims: Map<string, string> = ((globalThis as any)[claimsKey] ??= new Map());
const textOf = (message: JsonObject) => (Array.isArray(message.content) ? message.content : []).filter((block: JsonObject) => block.type === 'text' && typeof block.text === 'string').map((block: JsonObject) => block.text).join('\n');
function visibleMessage(message: JsonObject, human: boolean): JsonObject {
  return { id: message.id, role: message.role, source: sanitize(message.source), is_human: human,
    content: (message.content ?? []).filter((block: JsonObject) => block.type !== 'reasoning').map((block: JsonObject) => sanitize(block)) };
}

export class HostAdapter {
  readonly connection: ConnectionConfig; readonly stateDir: string; readonly hostId: string;
  readonly controller: Controller; readonly abort = new AbortController();
  private turns = new Map<string, Turn>(); private injected = new Map<string, number>();
  private pending = new Map<string, string>(); private pumping?: Promise<void>; private timer?: NodeJS.Timeout;
  private disposed = false; private failures = 0; private lastError?: string;
  private boundSession?: string; private waitingStarts = new Map<string, { session: Pick<Session, 'id' | 'header'>; event: SessionEvent }>();
  private heartbeatTimer?: NodeJS.Timeout;
  constructor(readonly config: AdapterConfig, readonly warn: (message: string) => void = () => {}, options?: { apiProxy: true }) {
    if (!SUPPORTED_HOSTS.includes(config.host_version) && !(options?.apiProxy && config.host_version === 'api-proxy')) throw new Error('Unsupported Harness version; use an explicitly configured API proxy or validate this host contract first');
    this.connection = validateConnection(JSON.parse(readFileSync(expandHome(config.connection_file), 'utf8')));
    this.stateDir = join(expandHome(config.state_dir ?? '~/Library/Application Support/NeuralKnowledge/harness-outbox'), hash(this.connection.connection_id).slice(0, 24));
    mkdirSync(this.stateDir, { recursive: true, mode: 0o700 });
    const identity = join(this.stateDir, 'identity.json');
    try { const stored = JSON.parse(readFileSync(identity, 'utf8')); this.hostId = stored.host_id; this.boundSession = stored.bound_session; }
    catch { this.hostId = randomUUID(); atomicJson(identity, { host_id: this.hostId }); }
    this.controller = new Controller(this.connection, config.timeout_ms ?? 2500, this.abort.signal);
    if (this.boundSession) sessionClaims.set(this.boundSession, this.connection.connection_id);
    for (const file of readdirSync(this.stateDir).filter(name => name.endsWith('.event.json'))) {
      try { const path = join(this.stateDir, file); const event: Envelope = JSON.parse(readFileSync(path, 'utf8')); this.pending.set(event.event_id, path); }
      catch { this.warn('Neural Knowledge outbox contains an unreadable record; retained for recovery'); }
    }
    this.schedule(0);
    this.heartbeatTimer = setInterval(() => { void this.heartbeat(); }, 15000); this.heartbeatTimer.unref();
    void this.heartbeat();
  }
  private async heartbeat() {
    if (!this.isEnabled()) return;
    try { await this.controller.send('heartbeat', { host_version: this.config.host_version, adapter_version: '0.4.0', ...(this.boundSession ? { bound_session_id: this.boundSession } : {}) }); }
    catch { /* Online status is separate from archived-turn acceptance; never fake a record. */ }
  }
  private isEnabled() {
    try {
      const current = JSON.parse(readFileSync(expandHome(this.config.connection_file), 'utf8'));
      const enabled = current.connection_id === this.connection.connection_id && current.library_id === this.connection.library_id && current.enabled !== false;
      if (!enabled) { this.turns.clear(); this.waitingStarts.clear(); }
      return enabled;
    } catch { this.turns.clear(); this.waitingStarts.clear(); return false; }
  }
  get enabled() { return this.isEnabled(); }
  private accepts(session: Pick<Session, 'id' | 'header'>, allowClaim = false) {
    const sid = String(session.id); const scope = this.connection.session_scope ?? 'connection';
    if (scope === 'connection') return true;
    if (scope !== 'next_session') return scope === sid;
    if (this.boundSession) return this.boundSession === sid;
    if (!allowClaim || session.header?.origin === 'subagent') return false;
    const claimed = sessionClaims.get(sid);
    if (claimed && claimed !== this.connection.connection_id) return false;
    this.boundSession = sid; sessionClaims.set(sid, this.connection.connection_id);
    atomicJson(join(this.stateDir, 'identity.json'), { host_id: this.hostId, bound_session: sid });
    const start = this.waitingStarts.get(sid); this.waitingStarts.clear();
    if (start) this.capture(start.session, start.event);
    void this.heartbeat();
    return true;
  }
  private waitingForAgentWindow(session: Pick<Session, 'id' | 'header'>) {
    return this.connection.connection_host === 'agent' && this.connection.session_scope === 'next_session'
      && !this.boundSession && session.header?.origin !== 'subagent';
  }
  private status() {
    atomicJson(join(this.stateDir, 'status.json'), { library_id: this.connection.library_id, connection_id: this.connection.connection_id,
      queued: this.pending.size, last_error: this.lastError ?? null, delivery: 'accepted means private journal persisted; graph projection may still be pending' });
  }
  enqueue(event: Envelope) {
    if (this.disposed || !this.isEnabled()) return;
    const name = `${hash(event.session_id).slice(0, 16)}-${String(event.seq).padStart(16, '0')}-${event.event_id}.event.json`;
    const file = join(this.stateDir, name);
    if (!this.pending.has(event.event_id)) { atomicJson(file, event); this.pending.set(event.event_id, file); }
    this.status(); this.schedule(0);
  }
  private schedule(delay: number) {
    if (this.disposed || this.timer) return;
    this.timer = setTimeout(() => { this.timer = undefined; void this.flush().catch(() => this.warn('Neural Knowledge durable outbox is unavailable; host records were not acknowledged')); }, delay); this.timer.unref();
  }
  async flush(): Promise<void> {
    if (this.pumping) return this.pumping;
    this.pumping = (async () => {
      for (const [id, file] of [...this.pending].sort((a, b) => a[1].localeCompare(b[1]))) {
        if (this.disposed || !this.isEnabled()) break;
        try {
          const event = JSON.parse(readFileSync(file, 'utf8'));
          const result = await this.controller.send('events', event);
          if (result.accepted !== true) throw new Error('Controller did not acknowledge journal persistence');
          unlinkSync(file); this.pending.delete(id); this.failures = 0; this.lastError = undefined;
        } catch (error) {
          this.lastError = (error as Error).message; this.failures++;
          if (this.failures === 1) this.warn(`Neural Knowledge archive queued: ${this.lastError}`);
          break;
        }
      }
      this.status();
    })().finally(() => { this.pumping = undefined; if (this.pending.size) this.schedule(Math.min(60000, (this.config.retry_ms ?? 1000) * 2 ** Math.min(this.failures, 6))); });
    return this.pumping;
  }
  capture(session: Pick<Session, 'id' | 'header'>, event: SessionEvent) {
    if (this.disposed || !this.isEnabled()) return;
    const input = event as unknown as JsonObject; const data = input.data ?? {};
    const message = input.type === 'user/message' ? data : data.message;
    if (message?.source?.kind === SOURCE_KIND) return;
    const agentMode = this.connection.connection_host === 'agent';
    const deferred = this.waitingForAgentWindow(session);
    if (agentMode && session.header?.origin === 'subagent') return;
    const claim = !agentMode && input.type === 'user/message' && message?.source?.kind === 'user';
    if (!deferred && !this.accepts(session, claim)) {
      if (!agentMode && input.type === 'turn/start' && !this.boundSession) {
        this.waitingStarts.set(String(session.id), { session: { id: session.id, header: session.header }, event });
        if (this.waitingStarts.size > 64) this.waitingStarts.delete(this.waitingStarts.keys().next().value!);
      }
      return;
    }
    const kinds = ['turn/start', 'turn/end', 'step/start', 'step/end', 'user/message', 'assistant/message', 'assistant/attempt', 'tool/call', 'tool/result', 'system/message', 'developer/message'];
    if (!kinds.includes(input.type)) return; // Never collect credential/config/request-header snapshots.
    const sid = String(session.id); const turnNumber = Number.isInteger(data.turn) ? data.turn : (this.turns.get(sid)?.number ?? -1);
    if (input.type === 'turn/start') {
      this.turns.set(sid, { number: turnNumber, started: true, interrupted: false, messages: [], calls: new Map(), ...(deferred ? { rawEvents: [] } : {}) });
      if (deferred && this.turns.size > 64) this.turns.delete(this.turns.keys().next().value!);
    }
    let turn = this.turns.get(sid);
    if (!turn) { turn = { number: turnNumber, started: false, interrupted: false, messages: [], calls: new Map() }; this.turns.set(sid, turn); }
    const redacted: string[] = []; const raw = sanitize(input, redacted);
    if (deferred) (turn.rawEvents ??= []).push(raw);
    const record: JsonObject = { schema: 'deepseek-harness-event/v1', host_id: this.hostId, host_version: this.config.host_version,
      raw_event: raw, session_origin: session.header?.origin ?? 'root', ...(redacted.length ? { redacted_fields: redacted } : {}) };
    if (input.type === 'tool/call') turn.calls.set(String(data.callId), String(data.name));
    if (message?.role && ['user', 'assistant'].includes(message.role)) {
      const human = message.role === 'user' && message.source?.kind === 'user' && session.header?.origin !== 'subagent';
      turn.messages.push(visibleMessage(sanitize(message), human));
      if (data.interrupted === true) turn.interrupted = true;
    }
    if (input.type === 'tool/result') {
      const callId = String(message?.toolCallId ?? message?.source?.callId ?? '');
      record.normalized = { type: 'tool', call_id: callId, tool_name: turn.calls.get(callId) ?? 'unknown', turn_id: `${sid}:${turn.number}`,
        outcome: message?.isError === true ? 'failed' : 'observed', content: sanitize(message?.content ?? []), is_error: message?.isError === true };
    }
    if (input.type === 'turn/end') {
      const reason = data.reason?.kind ?? 'unknown';
      const status = reason === 'completed' && turn.started && !turn.interrupted ? 'complete' : reason === 'error' ? 'failed' : reason === 'blocked' ? 'blocked' : 'partial';
      record.normalized = { type: 'turn', turn_id: `${sid}:${data.turn}`, status, reason,
        user: turn.messages.filter(m => m.is_human).map(textOf).join('\n\n'),
        assistant: turn.messages.filter(m => m.role === 'assistant').map(textOf).join('\n\n'), messages: turn.messages };
      this.turns.delete(sid);
    }
    if (deferred) {
      // A generic MCP connection is enrolled only by a complete real host turn.
      // Keep candidate windows in memory until then: no raw outbox files, no
      // premature identity claim and no rejected start event blocking the queue.
      if (record.normalized?.type !== 'turn' || record.normalized.status !== 'complete'
          || !record.normalized.user?.trim() || !record.normalized.assistant?.trim()) return;
      if (!this.accepts(session, true)) return;
      record.raw_events = turn.rawEvents;
      this.turns.clear();
    }
    this.enqueue({ session_id: sid, event_id: hash(`${this.hostId}\0${sid}\0${input.seq}\0${input.type}`),
      event_type: input.type, seq: input.seq, time: input.time, record });
  }
  async beforeStep(payload: { agent: Agent; messages: UserMessage[]; turn: number; step: number; signal: AbortSignal }, next: () => Promise<PreStepDecision>): Promise<PreStepDecision> {
    const decision = await next();
    if (decision.kind !== 'enter' || this.disposed || !this.isEnabled() || payload.signal.aborted || this.injected.get(String(payload.agent.session.id)) === payload.turn) return decision;
    const human = decision.messages.filter(message => message.source.kind === 'user');
    if (!human.length || decision.messages.some(message => message.source.kind === SOURCE_KIND)) return decision;
    if (this.connection.connection_host === 'agent' && payload.agent.session.header?.origin === 'subagent') return decision;
    if (!this.waitingForAgentWindow(payload.agent.session) && !this.accepts(payload.agent.session, true)) return decision;
    const query = human.map(message => textOf(message as unknown as JsonObject)).join('\n').slice(-40000) || '[用户输入包含附件引用；没有可采集的文字]';
    try {
      const context = await this.controller.send('context', { session_id: String(payload.agent.session.id), query });
      if (payload.signal.aborted || !this.isEnabled() || typeof context.packet !== 'string' || !context.packet.trim()) return decision;
      const text = `[宿主记忆连接绑定库 ${this.connection.library_id}。本会话使用宿主自动采集，仍以持久回执确认存档；无需再次调用旧手动record工具。若主动调用旧工具，先memory_status核实目标库，不得混入其他库。]\n${context.packet}`;
      const injected: UserMessage = Object.freeze({ id: `neural-context-${hash(`${this.connection.connection_id}:${payload.agent.session.id}:${payload.turn}:${payload.step}:${text}`)}` as MessageId,
        role: 'user', content: Object.freeze([{ type: 'text' as const, text }]),
        source: Object.freeze({ kind: SOURCE_KIND, form: 'recall' as const, connection_id: this.connection.connection_id }) });
      this.injected.set(String(payload.agent.session.id), payload.turn);
      return { ...decision, messages: [injected, ...decision.messages] };
    } catch { this.warn('Neural Knowledge context unavailable; the host turn continues without injected memory'); return decision; }
  }
  async dispose() {
    this.disposed = true; if (this.timer) clearTimeout(this.timer); if (this.heartbeatTimer) clearInterval(this.heartbeatTimer); this.abort.abort();
    if (this.pumping) await this.pumping;
  }
}

declare module '@deepseek-ai/dsh-llm' {
  interface MessageSourceMap { 'neural-knowledge-context': { kind: 'neural-knowledge-context'; form: 'recall'; connection_id: string } }
}
