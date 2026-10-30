import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
execFileSync(process.execPath, ['node_modules/typescript/bin/tsc', '--noEmit'], { stdio: 'inherit' });
mkdirSync('dist', { recursive: true });
mkdirSync('licenses', { recursive: true });
const yamlLicense = readFileSync('node_modules/yaml/LICENSE', 'utf8');
writeFileSync('licenses/yaml-ISC.txt', yamlLicense);
const options = { outdir: 'dist',
  platform: 'node', target: 'node24', format: 'esm', bundle: true, sourcemap: true,
  legalComments: 'eof',
  banner: { js: '// Neural Knowledge host adapter; PolyForm Noncommercial 1.0.0. Host contract: DeepSeek Harness 0.2.1-rc.3.\nimport { createRequire as __nkCreateRequire } from "node:module"; const require = __nkCreateRequire(import.meta.url);' },
};
await build({ ...options, entryPoints: ['src/index.ts', 'src/proxy.ts'] });
await build({ ...options, entryPoints: ['src/configure.ts'],
  banner: { js: '/*! Bundled yaml@2.8.1 — ISC license; complete upstream notice follows.\n' + yamlLicense + '\n*/\n' + options.banner.js },
});
writeFileSync('dist/THIRD_PARTY_LICENSES.txt', 'The configure CLI bundles yaml@2.8.1 (ISC):\n\n' + yamlLicense);
