// Neural Knowledge host adapter; PolyForm Noncommercial 1.0.0. Host contract: DeepSeek Harness 0.2.1-rc.3.
import { createRequire as __nkCreateRequire } from "node:module"; const require = __nkCreateRequire(import.meta.url);

// src/proxy.ts
import http2 from "node:http";
import https2 from "node:https";
import { createHash as createHash2 } from "node:crypto";
import { readFileSync as readFileSync2 } from "node:fs";
import { resolve as resolve2 } from "node:path";
import { fileURLToPath } from "node:url";

// src/runtime.ts
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, renameSync, unlinkSync, readdirSync, statSync, openSync, closeSync, fsyncSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import http from "node:http";
import https from "node:https";
var SOURCE_KIND = "neural-knowledge-context";
var SUPPORTED_HOSTS = ["0.2.1-rc.3"];
var expandHome = (path) => path.startsWith("~/") ? join(homedir(), path.slice(2)) : resolve(path);
var hash = (value) => createHash("sha256").update(value).digest("hex");
var object = (value) => !!value && typeof value === "object" && !Array.isArray(value);
var credential = (key) => /^(authorization|apikey|password|cookie|setcookie|accesstoken|refreshtoken|clientsecret|connectiontoken|deepseekapikey)$/i.test(key.replace(/[_\- ]/g, ""));
function sanitize(value, paths = [], path = "$") {
  if (Array.isArray(value)) return value.map((item, i) => sanitize(item, paths, `${path}[${i}]`));
  if (!object(value)) return value;
  const result = {};
  for (const [key, item] of Object.entries(value)) {
    if (credential(key)) {
      paths.push(`${path}.${key}`);
      continue;
    }
    if (key === "arguments" && typeof item === "string") {
      try {
        const args = JSON.parse(item);
        const redactions = [];
        const cleaned = sanitize(args, redactions, `${path}.arguments`);
        result[key] = redactions.length ? JSON.stringify(cleaned) : item;
        paths.push(...redactions);
        continue;
      } catch {
      }
    }
    if (["image", "file", "audio"].includes(String(value.type)) && ["base64", "bytes", "data"].includes(key)) {
      paths.push(`${path}.${key}:attachment-bytes-not-captured`);
      result.omitted_bytes = true;
      if (typeof item === "string") result.omitted_bytes_sha256 = hash(item);
      continue;
    }
    result[key] = sanitize(item, paths, `${path}.${key}`);
  }
  return result;
}
function atomicJson(path, value) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  const fd = openSync(temporary, "wx", 384);
  try {
    writeFileSync(fd, JSON.stringify(value));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
}
function validateConnection(config) {
  for (const key of ["connection_id", "connection_token", "library_id"]) {
    if (typeof config[key] !== "string" || !config[key].trim() || /[\r\n]/.test(config[key])) throw new Error(`Missing/invalid ${key}`);
  }
  if (config.base_url) validateBase(config.base_url, config.allow_remote);
  return config;
}
function validateBase(base, allowRemote = false) {
  const url = new URL(base);
  const local = ["127.0.0.1", "[::1]", "localhost"].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || url.pathname !== "/" && url.pathname !== "") throw new Error("Unsafe controller base_url");
  if (!local && (!allowRemote || url.protocol !== "https:") || !["http:", "https:"].includes(url.protocol)) throw new Error("Remote controllers require explicit allow_remote and HTTPS");
  return url.origin;
}
function requestJson(base, path, payload, token, timeout = 2500, signal) {
  const url = new URL(path, base);
  const data = payload === void 0 ? void 0 : Buffer.from(JSON.stringify(payload));
  return new Promise((resolveRequest, reject) => {
    const request = (url.protocol === "https:" ? https : http).request(url, {
      method: data ? "POST" : "GET",
      signal,
      headers: { ...data ? { "content-type": "application/json", "content-length": data.length } : {}, ...token ? { authorization: `Bearer ${token}` } : {} }
    }, (response) => {
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size > 8 * 1024 * 1024) request.destroy(new Error("Response too large"));
        else chunks.push(chunk);
      });
      response.on("end", () => {
        if ((response.statusCode ?? 500) < 200 || (response.statusCode ?? 500) >= 300) {
          reject(new Error(`Controller HTTP ${response.statusCode}`));
          return;
        }
        try {
          const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!object(parsed)) throw new Error("Not an object");
          resolveRequest(parsed);
        } catch {
          reject(new Error("Invalid controller JSON"));
        }
      });
      response.on("error", () => reject(new Error("Controller response interrupted")));
    });
    request.setTimeout(timeout, () => request.destroy(new Error("Controller timeout")));
    request.on("error", (error) => reject(new Error(signal?.aborted ? "Adapter disposed" : `Controller unavailable (${error.code ?? "transport"})`)));
    request.end(data);
  });
}
var Controller = class {
  constructor(config, timeout = 2500, signal) {
    this.timeout = timeout;
    this.signal = signal;
    this.config = validateConnection(config);
  }
  config;
  async discover() {
    if (this.config.base_url) {
      const base = validateBase(this.config.base_url, this.config.allow_remote);
      if ((await requestJson(base, "/api/health", void 0, void 0, this.timeout, this.signal)).ok !== true) throw new Error("Controller health failed");
      return base;
    }
    const directory = expandHome(this.config.runtime_dir ?? "~/Library/Application Support/NeuralKnowledge/.runtime");
    let files = [];
    try {
      files = readdirSync(directory).filter((name) => name.endsWith(".json")).flatMap((name) => {
        try {
          const path = join(directory, name);
          return [{ path, time: statSync(path).mtimeMs }];
        } catch {
          return [];
        }
      }).sort((a, b) => b.time - a.time);
    } catch {
    }
    for (const { path } of files) {
      try {
        if (statSync(path).size > 16384) continue;
        const ready = JSON.parse(readFileSync(path, "utf8"));
        if (!/^0\.4\./.test(ready.service_version ?? "") || !Number.isInteger(ready.controller_port) || ready.controller_port < 1 || ready.controller_port > 65535) continue;
        const base = `http://127.0.0.1:${ready.controller_port}`;
        if ((await requestJson(base, "/api/health", void 0, void 0, this.timeout, this.signal)).ok === true) return base;
      } catch {
      }
    }
    throw new Error("Start Neural Knowledge 0.4.x with controller_port; older display/personal ports are not archive controllers");
  }
  async send(kind, payload) {
    const base = await this.discover();
    return requestJson(base, `/api/connections/${encodeURIComponent(this.config.connection_id)}/${kind}`, payload, this.config.connection_token, this.timeout, this.signal);
  }
};
var claimsKey = Symbol.for("neural-knowledge.session-claims.v1");
var sessionClaims = globalThis[claimsKey] ??= /* @__PURE__ */ new Map();
var textOf = (message) => (Array.isArray(message.content) ? message.content : []).filter((block) => block.type === "text" && typeof block.text === "string").map((block) => block.text).join("\n");
function visibleMessage(message, human) {
  return {
    id: message.id,
    role: message.role,
    source: sanitize(message.source),
    is_human: human,
    content: (message.content ?? []).filter((block) => block.type !== "reasoning").map((block) => sanitize(block))
  };
}
var HostAdapter = class {
  constructor(config, warn = () => {
  }, options) {
    this.config = config;
    this.warn = warn;
    if (!SUPPORTED_HOSTS.includes(config.host_version) && !(options?.apiProxy && config.host_version === "api-proxy")) throw new Error("Unsupported Harness version; use an explicitly configured API proxy or validate this host contract first");
    this.connection = validateConnection(JSON.parse(readFileSync(expandHome(config.connection_file), "utf8")));
    this.stateDir = join(expandHome(config.state_dir ?? "~/Library/Application Support/NeuralKnowledge/harness-outbox"), hash(this.connection.connection_id).slice(0, 24));
    mkdirSync(this.stateDir, { recursive: true, mode: 448 });
    const identity = join(this.stateDir, "identity.json");
    try {
      const stored = JSON.parse(readFileSync(identity, "utf8"));
      this.hostId = stored.host_id;
      this.boundSession = stored.bound_session;
    } catch {
      this.hostId = randomUUID();
      atomicJson(identity, { host_id: this.hostId });
    }
    this.controller = new Controller(this.connection, config.timeout_ms ?? 2500, this.abort.signal);
    if (this.boundSession) sessionClaims.set(this.boundSession, this.connection.connection_id);
    for (const file of readdirSync(this.stateDir).filter((name) => name.endsWith(".event.json"))) {
      try {
        const path = join(this.stateDir, file);
        const event = JSON.parse(readFileSync(path, "utf8"));
        this.pending.set(event.event_id, path);
      } catch {
        this.warn("Neural Knowledge outbox contains an unreadable record; retained for recovery");
      }
    }
    this.schedule(0);
    this.heartbeatTimer = setInterval(() => {
      void this.heartbeat();
    }, 15e3);
    this.heartbeatTimer.unref();
    void this.heartbeat();
  }
  connection;
  stateDir;
  hostId;
  controller;
  abort = new AbortController();
  turns = /* @__PURE__ */ new Map();
  injected = /* @__PURE__ */ new Map();
  pending = /* @__PURE__ */ new Map();
  pumping;
  timer;
  disposed = false;
  failures = 0;
  lastError;
  boundSession;
  waitingStarts = /* @__PURE__ */ new Map();
  heartbeatTimer;
  async heartbeat() {
    if (!this.isEnabled()) return;
    try {
      await this.controller.send("heartbeat", { host_version: this.config.host_version, adapter_version: "0.4.0", ...this.boundSession ? { bound_session_id: this.boundSession } : {} });
    } catch {
    }
  }
  isEnabled() {
    try {
      const current = JSON.parse(readFileSync(expandHome(this.config.connection_file), "utf8"));
      const enabled = current.connection_id === this.connection.connection_id && current.library_id === this.connection.library_id && current.enabled !== false;
      if (!enabled) {
        this.turns.clear();
        this.waitingStarts.clear();
      }
      return enabled;
    } catch {
      this.turns.clear();
      this.waitingStarts.clear();
      return false;
    }
  }
  get enabled() {
    return this.isEnabled();
  }
  accepts(session, allowClaim = false) {
    const sid = String(session.id);
    const scope = this.connection.session_scope ?? "connection";
    if (scope === "connection") return true;
    if (scope !== "next_session") return scope === sid;
    if (this.boundSession) return this.boundSession === sid;
    if (!allowClaim || session.header?.origin === "subagent") return false;
    const claimed = sessionClaims.get(sid);
    if (claimed && claimed !== this.connection.connection_id) return false;
    this.boundSession = sid;
    sessionClaims.set(sid, this.connection.connection_id);
    atomicJson(join(this.stateDir, "identity.json"), { host_id: this.hostId, bound_session: sid });
    const start = this.waitingStarts.get(sid);
    this.waitingStarts.clear();
    if (start) this.capture(start.session, start.event);
    void this.heartbeat();
    return true;
  }
  status() {
    atomicJson(join(this.stateDir, "status.json"), {
      library_id: this.connection.library_id,
      connection_id: this.connection.connection_id,
      queued: this.pending.size,
      last_error: this.lastError ?? null,
      delivery: "accepted means private journal persisted; graph projection may still be pending"
    });
  }
  enqueue(event) {
    if (this.disposed || !this.isEnabled()) return;
    const name = `${hash(event.session_id).slice(0, 16)}-${String(event.seq).padStart(16, "0")}-${event.event_id}.event.json`;
    const file = join(this.stateDir, name);
    if (!this.pending.has(event.event_id)) {
      atomicJson(file, event);
      this.pending.set(event.event_id, file);
    }
    this.status();
    this.schedule(0);
  }
  schedule(delay) {
    if (this.disposed || this.timer) return;
    this.timer = setTimeout(() => {
      this.timer = void 0;
      void this.flush().catch(() => this.warn("Neural Knowledge durable outbox is unavailable; host records were not acknowledged"));
    }, delay);
    this.timer.unref();
  }
  async flush() {
    if (this.pumping) return this.pumping;
    this.pumping = (async () => {
      for (const [id, file] of [...this.pending].sort((a, b) => a[1].localeCompare(b[1]))) {
        if (this.disposed || !this.isEnabled()) break;
        try {
          const event = JSON.parse(readFileSync(file, "utf8"));
          const result = await this.controller.send("events", event);
          if (result.accepted !== true) throw new Error("Controller did not acknowledge journal persistence");
          unlinkSync(file);
          this.pending.delete(id);
          this.failures = 0;
          this.lastError = void 0;
        } catch (error) {
          this.lastError = error.message;
          this.failures++;
          if (this.failures === 1) this.warn(`Neural Knowledge archive queued: ${this.lastError}`);
          break;
        }
      }
      this.status();
    })().finally(() => {
      this.pumping = void 0;
      if (this.pending.size) this.schedule(Math.min(6e4, (this.config.retry_ms ?? 1e3) * 2 ** Math.min(this.failures, 6)));
    });
    return this.pumping;
  }
  capture(session, event) {
    if (this.disposed || !this.isEnabled()) return;
    const input = event;
    const data = input.data ?? {};
    const message = input.type === "user/message" ? data : data.message;
    if (message?.source?.kind === SOURCE_KIND) return;
    const claim = input.type === "user/message" && message?.source?.kind === "user";
    if (!this.accepts(session, claim)) {
      if (input.type === "turn/start" && !this.boundSession) {
        this.waitingStarts.set(String(session.id), { session: { id: session.id, header: session.header }, event });
        if (this.waitingStarts.size > 64) this.waitingStarts.delete(this.waitingStarts.keys().next().value);
      }
      return;
    }
    const kinds = ["turn/start", "turn/end", "step/start", "step/end", "user/message", "assistant/message", "assistant/attempt", "tool/call", "tool/result", "system/message", "developer/message"];
    if (!kinds.includes(input.type)) return;
    const sid = String(session.id);
    const turnNumber = Number.isInteger(data.turn) ? data.turn : this.turns.get(sid)?.number ?? -1;
    if (input.type === "turn/start") this.turns.set(sid, { number: turnNumber, started: true, interrupted: false, messages: [], calls: /* @__PURE__ */ new Map() });
    let turn = this.turns.get(sid);
    if (!turn) {
      turn = { number: turnNumber, started: false, interrupted: false, messages: [], calls: /* @__PURE__ */ new Map() };
      this.turns.set(sid, turn);
    }
    const redacted = [];
    const raw = sanitize(input, redacted);
    const record = {
      schema: "deepseek-harness-event/v1",
      host_id: this.hostId,
      host_version: this.config.host_version,
      raw_event: raw,
      session_origin: session.header?.origin ?? "root",
      ...redacted.length ? { redacted_fields: redacted } : {}
    };
    if (input.type === "tool/call") turn.calls.set(String(data.callId), String(data.name));
    if (message?.role && ["user", "assistant"].includes(message.role)) {
      const human = message.role === "user" && message.source?.kind === "user" && session.header?.origin !== "subagent";
      turn.messages.push(visibleMessage(sanitize(message), human));
      if (data.interrupted === true) turn.interrupted = true;
    }
    if (input.type === "tool/result") {
      const callId = String(message?.toolCallId ?? message?.source?.callId ?? "");
      record.normalized = {
        type: "tool",
        call_id: callId,
        tool_name: turn.calls.get(callId) ?? "unknown",
        turn_id: `${sid}:${turn.number}`,
        outcome: message?.isError === true ? "failed" : "observed",
        content: sanitize(message?.content ?? []),
        is_error: message?.isError === true
      };
    }
    if (input.type === "turn/end") {
      const reason = data.reason?.kind ?? "unknown";
      const status = reason === "completed" && turn.started && !turn.interrupted ? "complete" : reason === "error" ? "failed" : reason === "blocked" ? "blocked" : "partial";
      record.normalized = {
        type: "turn",
        turn_id: `${sid}:${data.turn}`,
        status,
        reason,
        user: turn.messages.filter((m) => m.is_human).map(textOf).join("\n\n"),
        assistant: turn.messages.filter((m) => m.role === "assistant").map(textOf).join("\n\n"),
        messages: turn.messages
      };
      this.turns.delete(sid);
    }
    this.enqueue({
      session_id: sid,
      event_id: hash(`${this.hostId}\0${sid}\0${input.seq}\0${input.type}`),
      event_type: input.type,
      seq: input.seq,
      time: input.time,
      record
    });
  }
  async beforeStep(payload, next) {
    const decision = await next();
    if (decision.kind !== "enter" || this.disposed || !this.isEnabled() || payload.signal.aborted || this.injected.get(String(payload.agent.session.id)) === payload.turn) return decision;
    const human = decision.messages.filter((message) => message.source.kind === "user");
    if (!human.length || decision.messages.some((message) => message.source.kind === SOURCE_KIND)) return decision;
    if (!this.accepts(payload.agent.session, true)) return decision;
    const query = human.map((message) => textOf(message)).join("\n").slice(-4e4) || "[\u7528\u6237\u8F93\u5165\u5305\u542B\u9644\u4EF6\u5F15\u7528\uFF1B\u6CA1\u6709\u53EF\u91C7\u96C6\u7684\u6587\u5B57]";
    try {
      const context = await this.controller.send("context", { session_id: String(payload.agent.session.id), query });
      if (payload.signal.aborted || !this.isEnabled() || typeof context.packet !== "string" || !context.packet.trim()) return decision;
      const text = `[\u5BBF\u4E3B\u8BB0\u5FC6\u8FDE\u63A5\u7ED1\u5B9A\u5E93 ${this.connection.library_id}\u3002\u672C\u4F1A\u8BDD\u4F7F\u7528\u5BBF\u4E3B\u81EA\u52A8\u91C7\u96C6\uFF0C\u4ECD\u4EE5\u6301\u4E45\u56DE\u6267\u786E\u8BA4\u5B58\u6863\uFF1B\u65E0\u9700\u518D\u6B21\u8C03\u7528\u65E7\u624B\u52A8record\u5DE5\u5177\u3002\u82E5\u4E3B\u52A8\u8C03\u7528\u65E7\u5DE5\u5177\uFF0C\u5148memory_status\u6838\u5B9E\u76EE\u6807\u5E93\uFF0C\u4E0D\u5F97\u6DF7\u5165\u5176\u4ED6\u5E93\u3002]
${context.packet}`;
      const injected = Object.freeze({
        id: `neural-context-${hash(`${this.connection.connection_id}:${payload.agent.session.id}:${payload.turn}:${payload.step}:${text}`)}`,
        role: "user",
        content: Object.freeze([{ type: "text", text }]),
        source: Object.freeze({ kind: SOURCE_KIND, form: "recall", connection_id: this.connection.connection_id })
      });
      this.injected.set(String(payload.agent.session.id), payload.turn);
      return { ...decision, messages: [injected, ...decision.messages] };
    } catch {
      this.warn("Neural Knowledge context unavailable; the host turn continues without injected memory");
      return decision;
    }
  }
  async dispose() {
    this.disposed = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.abort.abort();
    if (this.pumping) await this.pumping;
  }
};

// src/proxy.ts
function createProxy(config) {
  if (!config.session_id?.trim()) throw new Error("Proxy requires an explicit session namespace");
  const upstream = new URL(config.upstream ?? "https://api.deepseek.com");
  if (upstream.username || upstream.password || upstream.search || upstream.hash || upstream.protocol !== "https:" && !(config.allow_upstream_http && upstream.hostname === "127.0.0.1")) throw new Error("Invalid upstream");
  const delivery = new HostAdapter({ connection_file: config.connection_file, host_version: "api-proxy", state_dir: config.state_dir }, (message) => process.stderr.write(message + "\n"), { apiProxy: true });
  const server = http2.createServer((request, response) => {
    if (request.method !== "POST" || !["/v1/chat/completions", "/chat/completions"].includes(request.url ?? "")) {
      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "Only chat completions routed through this proxy are captured" }));
      return;
    }
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > 32 * 1024 * 1024) request.destroy();
      else chunks.push(chunk);
    });
    request.on("end", async () => {
      let body;
      try {
        body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
        if (!Array.isArray(body.messages)) throw new Error("messages");
      } catch {
        response.writeHead(400);
        response.end('{"error":"Expected a chat messages request"}');
        return;
      }
      const original = sanitize(body);
      const sid = typeof request.headers["x-neural-session-id"] === "string" ? request.headers["x-neural-session-id"] : config.session_id;
      const requestId = typeof request.headers["x-neural-request-id"] === "string" ? request.headers["x-neural-request-id"] : createHash2("sha256").update(JSON.stringify(original)).digest("hex");
      const userMessage = [...body.messages].reverse().find((m) => m.role === "user");
      const user = typeof userMessage?.content === "string" ? userMessage.content : (userMessage?.content ?? []).filter((b) => b.type === "text").map((b) => b.text).join("\n");
      try {
        if (delivery.enabled) {
          const context = await delivery.controller.send("context", { session_id: sid, query: user || "[Provider request with attachment references]" });
          if (delivery.enabled && typeof context.packet === "string" && context.packet.trim()) body.messages = [{ role: "user", content: context.packet }, ...body.messages];
        }
      } catch {
      }
      const sent = Buffer.from(JSON.stringify(body));
      const target = new URL("/chat/completions", upstream);
      const forwarded = (target.protocol === "https:" ? https2 : http2).request(target, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": sent.length,
          ...typeof request.headers.authorization === "string" ? { authorization: request.headers.authorization } : {}
        }
      }, (result) => {
        response.writeHead(result.statusCode ?? 502, { "content-type": result.headers["content-type"] ?? "application/json", "cache-control": "no-store" });
        const received = [];
        let bytes = 0;
        const digest = createHash2("sha256");
        result.on("data", (chunk) => {
          response.write(chunk);
          digest.update(chunk);
          bytes += chunk.length;
          if (bytes <= 32 * 1024 * 1024) received.push(chunk);
        });
        result.on("end", () => {
          response.end();
          const rawResponse = Buffer.concat(received).toString("utf8");
          let assistant = "";
          if (body.stream) {
            for (const line of rawResponse.split("\n")) if (line.startsWith("data:") && !line.includes("[DONE]")) {
              try {
                const frame = JSON.parse(line.slice(5).trim());
                assistant += frame.choices?.[0]?.delta?.content ?? "";
              } catch {
              }
            }
          } else {
            try {
              assistant = JSON.parse(rawResponse).choices?.[0]?.message?.content ?? "";
            } catch {
            }
          }
          const record = {
            schema: "neural-api-proxy/v1",
            host_id: delivery.hostId,
            host_version: "api-proxy",
            raw_event: {
              request: original,
              response_body: rawResponse,
              response_status: result.statusCode,
              response_sha256: digest.digest("hex"),
              response_body_truncated: bytes > 32 * 1024 * 1024
            },
            normalized: {
              type: "turn",
              turn_id: requestId,
              status: (result.statusCode ?? 500) >= 400 ? "failed" : "partial",
              reason: "proxy-wire-only-not-a-native-host-turn-boundary",
              user,
              assistant,
              messages: []
            },
            limitations: ["Provider HTTP traffic only", "No native session identity unless explicitly supplied", "No tool results not sent back to provider", "No attachment file bytes collected"]
          };
          delivery.enqueue({
            session_id: sid,
            event_id: createHash2("sha256").update(`${delivery.hostId}:${sid}:${requestId}`).digest("hex"),
            event_type: "proxy/completion",
            seq: 0,
            time: 0,
            record
          });
        });
        result.on("error", () => response.destroy());
      });
      forwarded.setTimeout(12e4, () => forwarded.destroy(new Error("Upstream timeout")));
      forwarded.on("error", () => {
        if (!response.headersSent) response.writeHead(502);
        response.end('{"error":"Provider upstream unavailable"}');
      });
      forwarded.end(sent);
    });
  });
  server.on("close", () => {
    void delivery.dispose();
  });
  return { server, delivery, listen: () => new Promise((resolveListen) => server.listen(config.listen_port ?? 0, "127.0.0.1", () => resolveListen(server.address().port))) };
}
async function main() {
  const index = process.argv.indexOf("--config");
  if (index < 0 || !process.argv[index + 1]) throw new Error("Use --config private-proxy.json");
  const config = JSON.parse(readFileSync2(expandHome(process.argv[index + 1]), "utf8"));
  const proxy = createProxy(config);
  const port = await proxy.listen();
  process.stdout.write(JSON.stringify({ base_url: `http://127.0.0.1:${port}/v1`, mode: "api-proxy", full_host_capture: false }) + "\n");
  for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => proxy.server.close());
}
if (process.argv[1] && resolve2(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(() => {
  process.stderr.write("API proxy failed to start; inspect its private configuration\n");
  process.exitCode = 1;
});
export {
  createProxy
};
//# sourceMappingURL=proxy.js.map
