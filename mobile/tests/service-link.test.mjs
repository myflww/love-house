import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../web/service-link.js',import.meta.url),'utf8');
const {memoryServiceUrl}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('phone opens only the explicitly selected HTTPS memory service without credentials',()=>{
 assert.equal(memoryServiceUrl('https://memory.example:9443'),'https://memory.example:9443/mobile');
 assert.equal(memoryServiceUrl('https://memory.example/mobile/'),'https://memory.example/mobile');
 for(const value of ['http://memory.example','javascript:alert(1)','https://'+'user'+':'+'secret'+'@memory.example','https://memory.example/?token=SECRET','https://memory.example/#secret','https://memory.example/other','https://memory.example\\@evil.invalid','https://memory.example\n'])assert.throws(()=>memoryServiceUrl(value));
});
