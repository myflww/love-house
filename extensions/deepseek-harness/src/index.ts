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
  const adapter = new HostAdapter(config, message => ctx.logger.warn(message));
  ctx.on('session/event', (session, event) => adapter.capture(session, event));
  ctx.on('agent/pre-step', (payload, next) => adapter.beforeStep(payload, next));
  ctx.effect(() => () => adapter.dispose());
}
