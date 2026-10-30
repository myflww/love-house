import http from 'node:http';
import https from 'node:https';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HostAdapter, sanitize, expandHome } from './runtime.ts';

export interface ProxyConfig { connection_file: string; session_id: string; state_dir?: string; listen_port?: number; upstream?: string; allow_upstream_http?: boolean }

/** Explicit, limited fallback: archives routed provider traffic, not native host events. */
export function createProxy(config: ProxyConfig) {
  if (!config.session_id?.trim()) throw new Error('Proxy requires an explicit session namespace');
  const upstream = new URL(config.upstream ?? 'https://api.deepseek.com');
  if (upstream.username || upstream.password || upstream.search || upstream.hash ||
      (upstream.protocol !== 'https:' && !(config.allow_upstream_http && upstream.hostname === '127.0.0.1'))) throw new Error('Invalid upstream');
  const delivery = new HostAdapter({ connection_file: config.connection_file, host_version: 'api-proxy', state_dir: config.state_dir }, message => process.stderr.write(message + '\n'), { apiProxy: true });
  const server = http.createServer((request, response) => {
    if (request.method !== 'POST' || !['/v1/chat/completions', '/chat/completions'].includes(request.url ?? '')) {
      response.writeHead(404, { 'content-type': 'application/json' }); response.end(JSON.stringify({ error: 'Only chat completions routed through this proxy are captured' })); return;
    }
    const chunks: Buffer[] = []; let size = 0;
    request.on('data', chunk => { size += chunk.length; if (size > 32 * 1024 * 1024) request.destroy(); else chunks.push(chunk); });
    request.on('end', async () => {
      let body: any;
      try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); if (!Array.isArray(body.messages)) throw new Error('messages'); }
      catch { response.writeHead(400); response.end('{"error":"Expected a chat messages request"}'); return; }
      const original = sanitize(body); const sid = typeof request.headers['x-neural-session-id'] === 'string' ? request.headers['x-neural-session-id'] : config.session_id;
      const requestId = typeof request.headers['x-neural-request-id'] === 'string' ? request.headers['x-neural-request-id'] : createHash('sha256').update(JSON.stringify(original)).digest('hex');
      const userMessage = [...body.messages].reverse().find((m: any) => m.role === 'user');
      const user = typeof userMessage?.content === 'string' ? userMessage.content : (userMessage?.content ?? []).filter((b: any) => b.type === 'text').map((b: any) => b.text).join('\n');
      try {
        if (delivery.enabled) {
          const context = await delivery.controller.send('context', { session_id: sid, query: user || '[Provider request with attachment references]' });
          if (delivery.enabled && typeof context.packet === 'string' && context.packet.trim()) body.messages = [{ role: 'user', content: context.packet }, ...body.messages];
        }
      } catch { /* Fail open; outbox recording remains independent of context availability. */ }
      const sent = Buffer.from(JSON.stringify(body)); const target = new URL('/chat/completions', upstream);
      const forwarded = (target.protocol === 'https:' ? https : http).request(target, {
        method: 'POST', headers: { 'content-type': 'application/json', 'content-length': sent.length,
          ...(typeof request.headers.authorization === 'string' ? { authorization: request.headers.authorization } : {}) },
      }, result => {
        response.writeHead(result.statusCode ?? 502, { 'content-type': result.headers['content-type'] ?? 'application/json', 'cache-control': 'no-store' });
        const received: Buffer[] = []; let bytes = 0; const digest = createHash('sha256');
        result.on('data', chunk => { response.write(chunk); digest.update(chunk); bytes += chunk.length; if (bytes <= 32 * 1024 * 1024) received.push(chunk); });
        result.on('end', () => {
          response.end(); const rawResponse = Buffer.concat(received).toString('utf8'); let assistant = '';
          if (body.stream) {
            for (const line of rawResponse.split('\n')) if (line.startsWith('data:') && !line.includes('[DONE]')) {
              try { const frame = JSON.parse(line.slice(5).trim()); assistant += frame.choices?.[0]?.delta?.content ?? ''; } catch { /* Non-JSON SSE control line. */ }
            }
          } else { try { assistant = JSON.parse(rawResponse).choices?.[0]?.message?.content ?? ''; } catch { /* HTTP failures are still observations. */ } }
          const record = { schema: 'neural-api-proxy/v1', host_id: delivery.hostId, host_version: 'api-proxy',
            raw_event: { request: original, response_body: rawResponse, response_status: result.statusCode,
              response_sha256: digest.digest('hex'), response_body_truncated: bytes > 32 * 1024 * 1024 },
            normalized: { type: 'turn', turn_id: requestId, status: (result.statusCode ?? 500) >= 400 ? 'failed' : 'partial',
              reason: 'proxy-wire-only-not-a-native-host-turn-boundary', user, assistant, messages: [] },
            limitations: ['Provider HTTP traffic only', 'No native session identity unless explicitly supplied', 'No tool results not sent back to provider', 'No attachment file bytes collected'] };
          delivery.enqueue({ session_id: sid, event_id: createHash('sha256').update(`${delivery.hostId}:${sid}:${requestId}`).digest('hex'),
            event_type: 'proxy/completion', seq: 0, time: 0, record });
        });
        result.on('error', () => response.destroy());
      });
      forwarded.setTimeout(120000, () => forwarded.destroy(new Error('Upstream timeout')));
      forwarded.on('error', () => { if (!response.headersSent) response.writeHead(502); response.end('{"error":"Provider upstream unavailable"}'); });
      forwarded.end(sent);
    });
  });
  server.on('close', () => { void delivery.dispose(); });
  return { server, delivery, listen: () => new Promise<number>(resolveListen => server.listen(config.listen_port ?? 0, '127.0.0.1', () => resolveListen((server.address() as any).port))) };
}

async function main() {
  const index = process.argv.indexOf('--config'); if (index < 0 || !process.argv[index + 1]) throw new Error('Use --config private-proxy.json');
  const config: ProxyConfig = JSON.parse(readFileSync(expandHome(process.argv[index + 1]), 'utf8'));
  const proxy = createProxy(config); const port = await proxy.listen();
  process.stdout.write(JSON.stringify({ base_url: `http://127.0.0.1:${port}/v1`, mode: 'api-proxy', full_host_capture: false }) + '\n');
  for (const signal of ['SIGTERM', 'SIGINT'] as const) process.on(signal, () => proxy.server.close());
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(() => { process.stderr.write('API proxy failed to start; inspect its private configuration\n'); process.exitCode = 1; });
