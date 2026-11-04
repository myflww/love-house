// Neural Knowledge host adapter; PolyForm Noncommercial 1.0.0. Host contract: DeepSeek Harness 0.2.1-rc.3.
import { createRequire as __nkCreateRequire } from "node:module"; const require = __nkCreateRequire(import.meta.url);

// src/runtime.ts
import { createHash as createHash2, randomUUID } from "node:crypto";
import { mkdirSync, readFileSync as readFileSync2, writeFileSync, renameSync, unlinkSync, readdirSync, statSync as statSync2, openSync as openSync2, closeSync as closeSync2, fsyncSync } from "node:fs";
import { homedir } from "node:os";
import { join as join2, resolve } from "node:path";
import http from "node:http";
import https from "node:https";

// src/host-contract.ts
import { createHash } from "node:crypto";
import { openSync, closeSync, readSync, readFileSync, statSync, existsSync, lstatSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, sep } from "node:path";

// host-contract-fingerprints.json
var host_contract_fingerprints_default = {
  schema: "love-house-harness-fingerprints/v1",
  reference_versions: [
    "0.2.1-rc.3",
    "0.2.1-rc.5"
  ],
  metadata_keys: [
    "name",
    "type",
    "main",
    "module",
    "exports",
    "imports",
    "dependencies",
    "peerDependencies",
    "peerDependenciesMeta",
    "engines"
  ],
  cordis_version: "4.0.5",
  packages: {
    "@deepseek-ai/dsh-agent": {
      metadata_sha256: "ce85d3e3fbd71e4466f065fb455c24cc9ee31a4273b828290e09ec3ea00c628e",
      files: {
        "lib/index.js": "7b59cf82c2784c25bdce4e3e24e5e5303b02b9f1003efacf50255492d17baf8b",
        "lib/types/archive-admission.js": "d42fbc10fbf357f1343d4c57eab55d3c7a6bd53fe20a29469cf0b1b67e55c4dd",
        "lib/types/consumed-work.js": "e20ac9e88d81db3f5e25908a50ad4532cd1d93f410ad5ec4933ef9aa24da5c2d",
        "lib/types/dispatch.js": "f29567a8eb2f04aaf34523e597d52e46f0fb5bed273db4bf7fa25bc38e2877da",
        "lib/types/index.js": "cc5de4b13b26bc1c5383c7c9300a074f267b69fe129a0bf74d1fd4ab695f1c52",
        "lib/types/model-selection.js": "47f758ea21ebf7544b4633d2ef8cbe5afafddf3b4aaf9892276cda9e98af11e7",
        "lib/types/projection.js": "43ab89acd14b20b3c2a85c8307f236b38dfa27671dd31b703554777270abc534",
        "lib/types/runtime-types.js": "72347f43fb79c35cff8565b6428c6d7b96a78267cf8994ea3ffd0830a83a21d2",
        "lib/types/types.js": "f4ef7228255d5f64ba546ed2a2b6be63601b77c7b58ac3a58a74f4e8f970cb30"
      }
    },
    "@deepseek-ai/dsh-session": {
      metadata_sha256: "2bf36cb064c7fc1cfda7b0c4a95ee597d76d90df11a551f99cf502e901576510",
      files: {
        "lib/index.js": "2f5dd07cb5c744a29abbb8003a8a4cefd9e582c6e2538074ca299a0ddd02a3bf",
        "lib/types/fork.js": "72ca7ae2cce506eb607e565f2e6b15fc6e3c2663de8403f79e37fc3a469e34cf",
        "lib/types/index.js": "59cced30c7ee65813c62f4858c2fc15c8c636df96507b60c15543468178b72f2",
        "lib/types/known-event-types.js": "f2adf39f26ecf7cc84bceaef1dcf8210395a13aa02e16828df1038a27a404edd",
        "lib/types/preparation.js": "78dea29f5e11a4d220945a572b3eb26cb66460e6a368a423bf597c3ef05a5faa",
        "lib/types/repair.js": "ee2e02d4e924bf01af621c38c27e030b89eaa8e0abfdf801a6220eca95aa2038",
        "lib/types/request-header.js": "3f73ee59af794df50df159a9c45c606f0fbce364c482b371831d1e8f26b87aea",
        "lib/types/seq-ranges.js": "68a127c76affa98edeeb50e302eb43f154f4d24f7d04cb95ba8b323e88f3d09e",
        "lib/types/surface.js": "ebe8920a22fca8d987cbacab94c9db92f71df44863f58370a1be559155be734e",
        "lib/types/tool-history.js": "2d2c4f4cbb6717aa2f487af52ce6a81e2002ce2c768cb5a4210c867ec49a0e95",
        "lib/types/types.js": "91723a2522999e2c8b6c455796ad699794a6f0abfcb44d9cb883edb13142ff9b"
      }
    },
    "@deepseek-ai/dsh-llm": {
      metadata_sha256: "8fff27b373cb28baeab6681a1c5aac6a0dd1056e1a46f5feb3cd0582dfc1f792",
      files: {
        "lib/index.js": "d18d8ae4c8d961e628708c1e4698e09716a0ebb80e55a672e0bde1029bec1155",
        "lib/typert.host.js": "22d86e67e013714b9b70eb119f85b825d73a52e30d6ebd5d7894dc4a2965076a",
        "lib/typert.remote-client.js": "fea6401fe00567f6f25bd58057e30167bb38a7c09f00dcd626116e1bc6c1fde6",
        "lib/types/adapter-failure.js": "f1213f11f11e0f20aae26c09a5e0cf3d72512c1f1519e1b3f107edf64af43c28",
        "lib/types/api-key.js": "254b774234c0bd38dd759765c0fd1e60788651a22106f5559ec2760a39935f2d",
        "lib/types/assembler.js": "35a4754ab854055942b9142934c595c3e6358a717947daa2d8d89847aef988f7",
        "lib/types/assistant-stream.js": "7e0cc96a4d60aed34381b552f9cb4549d70df36dbd28c0630da4cd93fa44b7a1",
        "lib/types/attribution.js": "62f546a0434b4ab70860db3d7c768f515b5f4895f41b3b1399afc9d0d02c7add",
        "lib/types/brand.js": "6b70219e0478d3307d865309523e7e7be3f169b06c04f4eef0d49b54aaef72a2",
        "lib/types/call-config.js": "170f3ce7c7136b93087e2f5d50faa8b69815894ec3ebdf26c36d57e4c7a17a03",
        "lib/types/content.js": "79802e2e6bece64114c8f6857943c2cd23742bd2c20b067cd06298d397f9b85e",
        "lib/types/error.js": "103b72873eafc3512d717593f802bbf09230c52b7fcd31aa6ec10b5fd147e1cb",
        "lib/types/index.js": "03b16dc51a3e6712823d57afaf74a7663d628aefd05ae7768d2cea89d05f7197",
        "lib/types/message.js": "c87812f77a2afd284f271af071575edcadfde3daa7b6554d77b96810ce4688e0",
        "lib/types/retry-policy.js": "f0a8fe075ac24c56ed2aa5d5e359a85539f5ffa237af54b68d3f4fc5124b5d83",
        "lib/types/types.js": "14106d660103de2db746964fbb5be90c5eb2a7ff736779e2501e9faff956cbf5"
      }
    },
    "@deepseek-ai/dsh-scope": {
      metadata_sha256: "6c325e4ef3a868e9008645d7fd1c9c7849334df2d938db92013ff6e07fd63998",
      files: {
        "lib/index.js": "2829df71d76e08941457d4dd173eac60783e55354921137c8b75e8b5c0d2ecca"
      }
    }
  },
  contract_id: "sha256:3ac4fe40018cc65182d062453f64f7b2b8b61a150fe7f1429e19cb9903203e66"
};

// src/host-contract.ts
var sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
function canonical(value) {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
function normalizedMetadata(metadata) {
  const normalize = (value) => typeof value === "string" ? value === metadata.version ? "$HOST_VERSION" : value : Array.isArray(value) ? value.map(normalize) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalize(item)])) : value;
  return normalize(Object.fromEntries(host_contract_fingerprints_default.metadata_keys.filter((key) => key in metadata).map((key) => [key, metadata[key]])));
}
function resourceRead(resources, name2) {
  const loose = join(resources, "app", name2);
  if (existsSync(loose)) {
    const root = realpathSync(resources), path = realpathSync(loose), child = relative(root, path);
    if (child === ".." || child.startsWith(".." + sep) || isAbsolute(child) || statSync(path).size > 4 * 1024 * 1024) throw new Error("Resource escapes installation or exceeds limit");
    return readFileSync(path);
  }
  const archive = join(resources, "app.asar");
  if (lstatSync(archive).isSymbolicLink()) throw new Error("Linked archive is not a contract source");
  const archivedEntry = join(archive, name2);
  if (existsSync(archivedEntry)) {
    if (statSync(archivedEntry).size > 4 * 1024 * 1024) throw new Error("Contract resource exceeds limit");
    return readFileSync(archivedEntry);
  }
  const fd = openSync(archive, "r");
  try {
    const prefix = Buffer.alloc(16);
    if (readSync(fd, prefix, 0, 16, 0) !== 16) throw new Error("Invalid ASAR header");
    const headerSize = prefix.readUInt32LE(4), payloadSize = prefix.readUInt32LE(8), jsonSize = prefix.readUInt32LE(12);
    if (prefix.readUInt32LE(0) !== 4 || headerSize < 8 || headerSize > 32 * 1024 * 1024 || payloadSize + 4 !== headerSize || jsonSize < 1 || jsonSize > headerSize - 8) throw new Error("Invalid ASAR bounds");
    const header = Buffer.alloc(jsonSize);
    if (readSync(fd, header, 0, jsonSize, 16) !== jsonSize) throw new Error("Truncated ASAR header");
    let entry = JSON.parse(header.toString("utf8"));
    for (const part of name2.split("/")) entry = entry?.files?.[part];
    const size = entry?.size, offset = Number(entry?.offset), position = 8 + headerSize + offset;
    if (!entry || entry.link || entry.unpacked || !Number.isSafeInteger(size) || size < 1 || size > 4 * 1024 * 1024 || !Number.isSafeInteger(offset) || offset < 0 || position + size > statSync(archive).size) throw new Error("Missing or invalid ASAR contract file");
    const body = Buffer.alloc(size);
    if (readSync(fd, body, 0, size, position) !== size) throw new Error("Truncated ASAR file");
    return body;
  } finally {
    closeSync(fd);
  }
}
function verifiedHostVersion(descriptor, version) {
  if (!descriptor || typeof descriptor !== "object" || Array.isArray(descriptor)) return null;
  const value = descriptor;
  if (value.schema !== "love-house-harness-contract/v1" || value.host_version !== version || value.contract_id !== host_contract_fingerprints_default.contract_id || typeof value.resources_path !== "string" || !isAbsolute(value.resources_path)) return null;
  try {
    let actualVersion;
    for (const [name2, expected] of Object.entries(host_contract_fingerprints_default.packages)) {
      const prefix = "dsh/node_modules/" + name2 + "/";
      const metadata = JSON.parse(resourceRead(value.resources_path, prefix + "package.json").toString("utf8"));
      if (metadata.name !== name2 || typeof metadata.version !== "string" || !metadata.version || sha256(canonical(normalizedMetadata(metadata))) !== expected.metadata_sha256) return null;
      actualVersion ??= metadata.version;
      if (metadata.version !== actualVersion) return null;
      for (const [file, hash2] of Object.entries(expected.files)) if (sha256(resourceRead(value.resources_path, prefix + file)) !== hash2) return null;
    }
    const cordis = JSON.parse(resourceRead(value.resources_path, "dsh/node_modules/@deepseek-ai/cordis/package.json").toString("utf8"));
    return cordis.name === "@deepseek-ai/cordis" && cordis.version === host_contract_fingerprints_default.cordis_version ? actualVersion ?? null : null;
  } catch {
    return null;
  }
}

// src/runtime.ts
var SOURCE_KIND = "neural-knowledge-context";
var SUPPORTED_HOSTS = ["0.2.1-rc.3", "0.2.1-rc.5"];
var expandHome = (path) => path.startsWith("~/") ? join2(homedir(), path.slice(2)) : resolve(path);
var hash = (value) => createHash2("sha256").update(value).digest("hex");
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
  const fd = openSync2(temporary, "wx", 384);
  try {
    writeFileSync(fd, JSON.stringify(value));
    fsyncSync(fd);
  } finally {
    closeSync2(fd);
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
      files = readdirSync(directory).filter((name2) => name2.endsWith(".json")).flatMap((name2) => {
        try {
          const path = join2(directory, name2);
          return [{ path, time: statSync2(path).mtimeMs }];
        } catch {
          return [];
        }
      }).sort((a, b) => b.time - a.time);
    } catch {
    }
    for (const { path } of files) {
      try {
        if (statSync2(path).size > 16384) continue;
        const ready = JSON.parse(readFileSync2(path, "utf8"));
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
    const actualVersion = config.host_contract ? verifiedHostVersion(config.host_contract, config.host_version) : null;
    const compatible = config.host_contract ? !!actualVersion : SUPPORTED_HOSTS.includes(config.host_version);
    if (!compatible && !(options?.apiProxy && config.host_version === "api-proxy")) throw new Error("Harness contract could not be verified; regenerate the connection from the installed SDK metadata or validate changed interfaces");
    if (actualVersion) this.config = { ...config, host_version: actualVersion };
    this.connection = validateConnection(JSON.parse(readFileSync2(expandHome(config.connection_file), "utf8")));
    this.stateDir = join2(expandHome(config.state_dir ?? "~/Library/Application Support/NeuralKnowledge/harness-outbox"), hash(this.connection.connection_id).slice(0, 24));
    mkdirSync(this.stateDir, { recursive: true, mode: 448 });
    const identity = join2(this.stateDir, "identity.json");
    try {
      const stored = JSON.parse(readFileSync2(identity, "utf8"));
      this.hostId = stored.host_id;
      this.boundSession = stored.bound_session;
    } catch {
      this.hostId = randomUUID();
      atomicJson(identity, { host_id: this.hostId });
    }
    this.controller = new Controller(this.connection, config.timeout_ms ?? 2500, this.abort.signal);
    if (this.boundSession) sessionClaims.set(this.boundSession, this.connection.connection_id);
    for (const file of readdirSync(this.stateDir).filter((name2) => name2.endsWith(".event.json"))) {
      try {
        const path = join2(this.stateDir, file);
        const event = JSON.parse(readFileSync2(path, "utf8"));
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
  closing = false;
  closePromise;
  failures = 0;
  lastError;
  boundSession;
  waitingStarts = /* @__PURE__ */ new Map();
  heartbeatTimer;
  async heartbeat() {
    if (!this.isEnabled()) return;
    try {
      await this.controller.send("heartbeat", { host_version: this.config.host_version, adapter_version: "0.4.1", ...this.boundSession ? { bound_session_id: this.boundSession } : {} });
    } catch {
    }
  }
  isEnabled() {
    try {
      const current = JSON.parse(readFileSync2(expandHome(this.config.connection_file), "utf8"));
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
    atomicJson(join2(this.stateDir, "identity.json"), { host_id: this.hostId, bound_session: sid });
    const start = this.waitingStarts.get(sid);
    this.waitingStarts.clear();
    if (start) this.capture(start.session, start.event);
    void this.heartbeat();
    return true;
  }
  waitingForAgentWindow(session) {
    return this.connection.connection_host === "agent" && this.connection.session_scope === "next_session" && !this.boundSession && session.header?.origin !== "subagent";
  }
  fixedRoot(session) {
    const sid = String(session.id);
    const scope = this.connection.session_scope ?? "connection";
    return session.header?.origin !== "subagent" && (scope === "next_session" ? this.boundSession === sid : scope !== "connection" && scope === sid);
  }
  publicTaskQuery(session) {
    if (typeof session.deriveMessages !== "function") return;
    const messages = session.deriveMessages();
    if (!Array.isArray(messages)) return;
    const baseline = "\u5F53\u524D\u5DF2\u7ED1\u5B9A\u5B58\u6863\u7684\u957F\u671F\u57FA\u7EBF\u548C\u7EA6\u5B9A";
    for (let index = messages.length - 1; index >= 0; index--) {
      const message = messages[index];
      if (message.role === "user" && message.source?.kind === "user") {
        const text = textOf(message);
        return text.trim() ? text.slice(-4e4) : baseline;
      }
    }
    return baseline;
  }
  status() {
    atomicJson(join2(this.stateDir, "status.json"), {
      library_id: this.connection.library_id,
      connection_id: this.connection.connection_id,
      queued: this.pending.size,
      last_error: this.lastError ?? null,
      delivery: "accepted means private journal persisted; graph projection may still be pending"
    });
  }
  enqueue(event) {
    if (this.disposed || this.closing || !this.isEnabled()) return;
    const name2 = `${hash(event.session_id).slice(0, 16)}-${String(event.seq).padStart(16, "0")}-${event.event_id}.event.json`;
    const file = join2(this.stateDir, name2);
    if (!this.pending.has(event.event_id)) {
      atomicJson(file, event);
      this.pending.set(event.event_id, file);
    }
    this.status();
    this.schedule(0);
  }
  schedule(delay) {
    if (this.disposed || this.closing || this.timer) return;
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
          const event = JSON.parse(readFileSync2(file, "utf8"));
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
    if (this.disposed || this.closing || !this.isEnabled()) return;
    if (session.header?.origin === "subagent") return;
    const input = event;
    const data = input.data ?? {};
    const message = input.type === "user/message" ? data : data.message;
    if (message?.source?.kind === SOURCE_KIND) return;
    const agentMode = this.connection.connection_host === "agent";
    const deferred = this.waitingForAgentWindow(session);
    if (agentMode && session.header?.origin === "subagent") return;
    const claim = !agentMode && input.type === "user/message" && message?.source?.kind === "user";
    if (!deferred && !this.accepts(session, claim)) {
      if (!agentMode && input.type === "turn/start" && !this.boundSession) {
        this.waitingStarts.set(String(session.id), { session: { id: session.id, header: session.header }, event });
        if (this.waitingStarts.size > 64) this.waitingStarts.delete(this.waitingStarts.keys().next().value);
      }
      return;
    }
    const kinds = ["turn/start", "turn/end", "step/start", "step/end", "user/message", "assistant/message", "assistant/attempt", "tool/call", "tool/result", "system/message", "developer/message"];
    if (!kinds.includes(input.type)) return;
    const sid = String(session.id);
    const turnNumber = Number.isInteger(data.turn) ? data.turn : this.turns.get(sid)?.number ?? -1;
    if (input.type === "turn/start") {
      this.turns.set(sid, { number: turnNumber, started: true, interrupted: false, messages: [], calls: /* @__PURE__ */ new Map(), ...deferred ? { rawEvents: [] } : {} });
      if (deferred && this.turns.size > 64) this.turns.delete(this.turns.keys().next().value);
    }
    let turn = this.turns.get(sid);
    if (!turn) {
      turn = { number: turnNumber, started: false, interrupted: false, messages: [], calls: /* @__PURE__ */ new Map() };
      this.turns.set(sid, turn);
    }
    const redacted = [];
    const raw = sanitize(input, redacted);
    if (deferred) (turn.rawEvents ??= []).push(raw);
    const record = {
      schema: "deepseek-harness-event/v1",
      host_id: this.hostId,
      host_version: this.config.host_version,
      raw_event: raw,
      session_origin: session.header?.origin ?? "root",
      ...redacted.length ? { redacted_fields: redacted } : {}
    };
    if (input.type === "tool/call") turn.calls.set(String(data.callId), String(data.name));
    if (["step/start", "assistant/attempt", "tool/call", "tool/result"].includes(input.type)) turn.lastWorkSeq = input.seq;
    if (message?.role && ["user", "assistant"].includes(message.role)) {
      const human = message.role === "user" && message.source?.kind === "user" && session.header?.origin !== "subagent";
      const visible = visibleMessage(sanitize(message), human);
      turn.messages.push(visible);
      if (input.type === "assistant/message" && message.role === "assistant") {
        turn.lastAssistant = { message: visible, turn: data.turn, seq: input.seq };
      }
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
      const human = turn.messages.filter((m) => m.is_human);
      const finalAssistant = turn.lastAssistant?.message;
      const fixedRoot = this.fixedRoot(session);
      const finalText = finalAssistant ? textOf(finalAssistant) : "";
      const finalTextOnly = Array.isArray(finalAssistant?.content) && finalAssistant.content.every((block) => block.type === "text");
      if (fixedRoot && status === "complete" && Number.isInteger(data.turn) && data.turn === turn.number && turn.lastAssistant?.turn === turn.number && turn.lastAssistant.seq > (turn.lastWorkSeq ?? -1) && !human.length && finalAssistant?.source?.kind === "model" && typeof finalAssistant.id === "string" && finalAssistant.id.trim() && finalText.trim() && finalTextOnly) {
        record.normalized = {
          type: "output",
          role: "assistant",
          text: finalText,
          turn_id: `${sid}:${data.turn}`,
          status: "complete",
          reason,
          evidence: { assistant_message_id: finalAssistant.id }
        };
      } else record.normalized = {
        type: "turn",
        turn_id: `${sid}:${data.turn}`,
        status,
        reason,
        user: human.map(textOf).join("\n\n"),
        assistant: turn.messages.filter((m) => m.role === "assistant").map(textOf).join("\n\n"),
        messages: turn.messages
      };
      this.turns.delete(sid);
    }
    if (deferred) {
      if (record.normalized?.type !== "turn" || record.normalized.status !== "complete" || !record.normalized.user?.trim() || !record.normalized.assistant?.trim()) return;
      if (!this.accepts(session, true)) return;
      record.raw_events = turn.rawEvents;
      this.turns.clear();
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
    if (decision.kind !== "enter" || this.disposed || this.closing || !this.isEnabled() || payload.signal.aborted || this.injected.get(String(payload.agent.session.id)) === payload.turn) return decision;
    if (payload.agent.session.header?.origin === "subagent") return decision;
    const human = decision.messages.filter((message) => message.source.kind === "user");
    if (decision.messages.some((message) => message.source.kind === SOURCE_KIND)) return decision;
    const sid = String(payload.agent.session.id);
    const withoutHuman = !human.length;
    if (withoutHuman) {
      const turn = this.turns.get(sid);
      if (!this.fixedRoot(payload.agent.session) || !this.accepts(payload.agent.session) || !turn?.started || turn.interrupted || turn.number !== payload.turn) return decision;
    } else if (!this.waitingForAgentWindow(payload.agent.session) && !this.accepts(payload.agent.session, true)) return decision;
    try {
      const query = withoutHuman ? this.publicTaskQuery(payload.agent.session) : human.map((message) => textOf(message)).join("\n").slice(-4e4) || "[\u7528\u6237\u8F93\u5165\u5305\u542B\u9644\u4EF6\u5F15\u7528\uFF1B\u6CA1\u6709\u53EF\u91C7\u96C6\u7684\u6587\u5B57]";
      if (!query) return decision;
      const context = await this.controller.send("context", { session_id: sid, query });
      if (payload.signal.aborted || this.closing || !this.isEnabled() || typeof context.packet !== "string" || !context.packet.trim()) return decision;
      if (withoutHuman) {
        const current = this.turns.get(sid);
        if (!this.fixedRoot(payload.agent.session) || !this.accepts(payload.agent.session) || !current?.started || current.interrupted || current.number !== payload.turn) return decision;
      }
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
    if (this.closePromise) return this.closePromise;
    this.closing = true;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = void 0;
    }
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.closePromise = (async () => {
      let deadline;
      const budget = Math.max(1, Math.min(5e3, this.config.timeout_ms ?? 2500));
      const drain = async () => {
        do {
          const before = this.pending.size;
          await this.flush();
          if (!this.pending.size || this.pending.size >= before) break;
        } while (true);
      };
      try {
        await Promise.race([drain(), new Promise((resolve2) => {
          deadline = setTimeout(resolve2, budget);
        })]);
      } finally {
        if (deadline) clearTimeout(deadline);
        this.disposed = true;
        this.abort.abort();
        if (this.pumping) await this.pumping;
      }
    })();
    return this.closePromise;
  }
};

// src/index.ts
var name = "neural-knowledge-host";
var reusable = true;
var inject = ["sessions", "agents"];
function apply(ctx, config) {
  const adapter = new HostAdapter(config, (message) => ctx.logger.warn(message));
  ctx.on("session/event", (session, event) => adapter.capture(session, event));
  ctx.on("agent/pre-step", (payload, next) => adapter.beforeStep(payload, next));
  ctx.effect(() => () => adapter.dispose());
}
export {
  HostAdapter,
  SOURCE_KIND,
  SUPPORTED_HOSTS,
  apply,
  inject,
  name,
  reusable,
  sanitize
};
//# sourceMappingURL=index.js.map
