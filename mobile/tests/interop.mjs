// Bridge used only by the Python desktop/mobile interoperability tests. No networking.
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../web/store.js', import.meta.url), 'utf8');
const { createStore, createMemoryAdapter } = await import('data:text/javascript;base64,' + Buffer.from(source + '\n//# sourceURL=mobile-store.js').toString('base64'));
const store = createStore({ adapter: createMemoryAdapter() });
const initial = await store.init();
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
let result;
if (process.argv[2] === 'manual') {
  await store.saveMemory(initial.selectedLibraryId, input);
  result = { package: await store.exportLibrary(initial.selectedLibraryId) };
} else {
  const imported = await store.importLibrary(input.package || input);
  if (input.deleteId) await store.deleteMemory(imported.id, input.deleteId);
  result = { imported, package: await store.exportLibrary(imported.id) };
}
process.stdout.write(JSON.stringify(result));
