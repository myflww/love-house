import type { Context } from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-agent';
import type {} from '@deepseek-ai/dsh-session';
import { HostAdapter } from './runtime.ts';
import type { AdapterConfig } from './runtime.ts';
export { HostAdapter, SOURCE_KIND, sanitize, SUPPORTED_HOSTS } from './runtime.ts';
export const name = 'neural-knowledge-host';
export const reusable = true;
export const inject = ['sessions', 'agents'];
export function apply(ctx: Context, config: AdapterConfig) {
  // Check live injected registries without looking up or creating any sessions.
  // Declaration compatibility alone cannot prove that this host loaded them.
  if (!ctx || typeof ctx.on !== 'function' || typeof ctx.effect !== 'function' || typeof ctx.logger?.warn !== 'function'
      || typeof ctx.sessions?.get !== 'function' || typeof ctx.agents?.get !== 'function') {
    throw new Error('Harness runtime services do not provide the required memory event capabilities');
  }
  const adapter = new HostAdapter(config, message => ctx.logger.warn(message));
  ctx.on('session/event', (session, event) => adapter.capture(session, event));
  ctx.on('agent/pre-step', (payload, next) => adapter.beforeStep(payload, next));
  ctx.effect(() => () => adapter.dispose());
}
