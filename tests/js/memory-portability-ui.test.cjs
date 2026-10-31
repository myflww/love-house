/* Run the actual shipped async actions with inert UI/transport boundaries. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-portability-ui.js'),'utf8');
function action(name,ctx){
 const match=source.match(new RegExp('async function '+name+'\\([^]*?\\n\\}'));
 assert(match,`Actual UI action ${name} is missing`);
 return vm.runInNewContext(match[0]+';'+name,ctx);
}
const plain=value=>JSON.parse(JSON.stringify(value));
function context(){
 const S={libraryId:'lib-only',libraryEpoch:7};
 const state={owner:{id:S.libraryId,epoch:7},version:9,busy:false,preview:{content_revision:'a'.repeat(64)},summary:null,native:new Map()};
 const ctx={S,state,consent:{checked:true},aiConsent:{checked:true},share:{d:{open:true}},shareNotice:{textContent:''},aiText:{textContent:'',hidden:true},shareControls(){},current:o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch,idle:()=>!state.busy,
  api:async()=>{throw Error('No default network allowed');},saveFile:async()=>{throw Error('No default file write allowed');}};
 return ctx;
}
test('download requires personal-memory consent and sends only scoped format/revision/opaque summary ID',async()=>{
 const ctx=context(),calls=[],saves=[];
 ctx.api=async(route,data)=>{calls.push({route,data:plain(data)});return {filename:'chosen.json',content:'only-library-memory',mime:'application/json'};};
 ctx.saveFile=async(result,owner)=>{saves.push({result,owner});return 'dialog';};
 const run=action('download',ctx);
 ctx.consent.checked=false;await run('json');assert.equal(calls.length,0);
 ctx.consent.checked=true;ctx.state.summary={summary_id:'summary-local'};await run('json');
 assert.deepEqual(calls,[{route:'sharing/download',data:{format:'json',confirm:true,expected_revision:'a'.repeat(64),summary_id:'summary-local'}}]);
 assert.equal(saves.length,1);assert.equal(saves[0].owner.id,'lib-only');assert.equal(ctx.state.busy,false);
 assert(ctx.shareNotice.textContent.includes('保存位置'));
});
test('stale owner never requests another library and an in-flight library switch never saves the old reply',async()=>{
 const ctx=context();let requests=0,saves=0;
 ctx.api=async()=>{requests++;ctx.S.libraryId='other-library';ctx.S.libraryEpoch++;return {content:'OLD_LIBRARY_CONTENT'};};
 ctx.saveFile=async()=>{saves++;};const run=action('download',ctx);
 ctx.S.libraryEpoch=8;await run('json');assert.equal(requests,0);
 ctx.S.libraryEpoch=7;await run('markdown');assert.equal(requests,1);assert.equal(saves,0);assert.equal(ctx.state.busy,false);
});
test('optional AI index is explicitly consented, stays a sidecar and does not auto-save any file',async()=>{
 const ctx=context(),calls=[];
 ctx.api=async(route,data)=>{calls.push({route,data:plain(data)});return {summary_id:'one',reading_summary:{text:'辅助索引',coverage:{included_nodes:2,total_nodes:10}}};};
 const run=action('generateSummary',ctx);
 ctx.aiConsent.checked=false;await run();assert.equal(calls.length,0);
 ctx.aiConsent.checked=true;await run();
 assert.deepEqual(calls,[{route:'sharing/summary',data:{confirm:true,expected_revision:'a'.repeat(64)}}]);
 assert.equal(ctx.aiText.textContent,'辅助索引');assert.equal(ctx.aiText.hidden,false);assert.equal(ctx.state.summary.summary_id,'one');
 assert(ctx.shareNotice.textContent.includes('2/10'));assert.equal(ctx.state.busy,false);
});
test('native save receives only chosen filename/content and correlates request without model credentials',async()=>{
 const ctx=context(),posts=[];
 ctx.window={webkit:{messageHandlers:{saveMemoryFile:{postMessage:payload=>posts.push(plain(payload))}}}};
 // Read the real saveFile function, including only its own inert native branch.
 const run=action('saveFile',ctx),owner={id:'lib-only',epoch:7};
 const result=await run({filename:'单库.lovehouse.json',content:'EXPLICIT_USER_SELECTED_MEMORY',mime:'application/json',provider:{get api_key(){throw Error('A file action must not touch a model key');}}},owner);
 assert.equal(result,'dialog');assert.equal(posts.length,1);
 assert.deepEqual(Object.keys(posts[0]).sort(),['content','filename','request_id']);
 assert.equal(posts[0].filename,'单库.lovehouse.json');assert.equal(posts[0].content,'EXPLICIT_USER_SELECTED_MEMORY');
 assert.deepEqual(plain(ctx.state.native.get(posts[0].request_id)),owner);
});
test('Windows native bridge reports saved/cancelled truthfully and does not fall through to a browser download',async()=>{
 const ctx=context(),calls=[];let response={saved:true,cancelled:false};
 ctx.window={pywebview:{api:{save_memory_file:async(filename,content)=>{calls.push({filename,content});return response;}}}};
 const run=action('saveFile',ctx),result={filename:'单库.json',content:'WINDOWS_EXPLICIT_MEMORY'};
 assert.equal(await run(result,ctx.state.owner),'saved');
 response={saved:false,cancelled:true};assert.equal(await run(result,ctx.state.owner),'cancelled');
 response={saved:false,error:'选择的位置不可写'};await assert.rejects(run(result,ctx.state.owner),/选择的位置不可写/);
 assert.equal(calls.length,3);assert.equal(ctx.state.native.size,0);
 assert.deepEqual(calls[0],{filename:'单库.json',content:'WINDOWS_EXPLICIT_MEMORY'});
});

test('an unready Windows bridge waits for native save and never reports a blocked browser download',async()=>{
 const ctx=context();let attempts=0,saves=0;
 ctx.window={pywebview:{api:{}}};ctx.setTimeout=resolve=>{attempts++;if(attempts===2)ctx.window.pywebview.api.save_memory_file=async()=>{saves++;return {saved:true};};resolve();};
 const run=action('saveFile',ctx);
 assert.equal(await run({filename:'safe.json',content:'synthetic'},ctx.state.owner),'saved');
 assert.equal(attempts,2);assert.equal(saves,1);
 ctx.window.pywebview.api={};ctx.setTimeout=resolve=>resolve();
 await assert.rejects(run({filename:'safe.json',content:'synthetic'},ctx.state.owner),/尚未就绪/);
});

test('a library switch while waiting for native readiness does not open a stale save dialog',async()=>{
 const ctx=context();let saves=0;
 ctx.window={pywebview:{api:{}}};ctx.setTimeout=resolve=>{ctx.S.libraryEpoch++;ctx.window.pywebview.api.save_memory_file=async()=>{saves++;return {saved:true};};resolve();};
 assert.equal(await action('saveFile',ctx)({filename:'old.json',content:'OLD'},ctx.state.owner),'stale');
 assert.equal(saves,0);
});

test('a library switch while native saving cannot overwrite the next library status',async()=>{
 const ctx=context();ctx.api=async()=>({filename:'old.json',content:'OLD'});
 ctx.saveFile=async()=>{ctx.S.libraryEpoch++;ctx.shareNotice.textContent='NEXT_LIBRARY';return 'saved';};
 await action('download',ctx)('json');assert.equal(ctx.shareNotice.textContent,'NEXT_LIBRARY');
});
