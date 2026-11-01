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
 const state={owner:{id:S.libraryId,epoch:7},version:9,busy:false,preview:{content_revision:'a'.repeat(64)},summary:null,providerReady:false,native:new Map()};
 const ctx={S,state,consent:{checked:true},aiConsent:{checked:true},generateAI:{dataset:{ready:'false'}},share:{d:{open:true}},shareNotice:{textContent:''},aiText:{textContent:'',hidden:true},shareControls(){},current:o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch,idle:()=>!state.busy,
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
 ctx.aiConsent.checked=true;ctx.state.providerReady=true;ctx.generateAI.dataset.ready='true';await run();
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

function shareContext(){
 const c=context(),rows=[],calls=[],timers=new Map();let timerID=0;
 Object.assign(c,{owner:()=>({id:c.S.libraryId,epoch:c.S.libraryEpoch}),libraryName:id=>id,num:n=>Number(n||0),make:(tag,cls,text)=>({tag,textContent:text}),
  share:{d:{open:false,showModal(){this.open=true;}},h:{textContent:''},close:{disabled:false}},shareFacts:{children:[],replaceChildren(...items){this.children=items;}},
  ai:{open:false},aiNote:{textContent:''},configureAI:{hidden:false},generateAI:{dataset:{ready:'false'},disabled:true},saveJSON:{disabled:true},saveMD:{disabled:true},refreshShare:{disabled:false},
  confirmationList:(node,list)=>{rows.push(plain(list));node.children=list;},setTimeout:(fn,ms)=>{const id=++timerID;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)});
 c.rows=rows;c.calls=calls;c.timers=timers;
 const preview={name:'Single fish',node_count:8,edge_count:3,archive_count:5,content_revision:'b'.repeat(64),privacy:{redactions:{paths:2}}};
 c.api=async(route,data,options)=>{calls.push({route,data:plain(data??null),options:plain(options??{})});if(route==='sharing/preview')return preview;throw Error('Unexpected '+route);};
 const controls=source.match(/function shareControls\([^\n]+/)[0];c.shareControls=vm.runInNewContext(controls+';shareControls',c);
 c.loadSummaryProvider=action('loadSummaryProvider',c);c.openShare=action('openShare',c);c.download=action('download',c);c.generateSummary=action('generateSummary',c);
 return c;
}
const settle=async()=>{await Promise.resolve();await Promise.resolve();};

test('complete sharing preview never requests organizer metadata until AI options are opened',async()=>{
 const c=shareContext();await c.openShare();assert(c.share.d.open);assert.equal(c.state.preview.node_count,8);assert.equal(c.rows.length,1);assert.deepEqual(c.calls.map(x=>x.route),['sharing/preview']);
 assert.equal(c.calls[0].options.libraryId,'lib-only');assert.equal(c.state.providerReady,false);assert.equal(c.generateAI.dataset.ready,'false');assert(c.generateAI.disabled);assert(c.aiConsent.disabled);assert(c.aiNote.textContent.includes('完整导出不需要 API Key'));assert.equal(c.timers.size,0);
 c.consent.checked=true;c.shareControls();assert.equal(c.saveJSON.disabled,false);assert.equal(c.saveMD.disabled,false);
});

test('organizer status rejection stays within AI options while JSON and Markdown exports remain available',async()=>{
 const c=shareContext();await c.openShare();c.consent.checked=true;c.shareControls();const originalNotice=c.shareNotice.textContent,saves=[];
 c.api=async(route,data,options)=>{c.calls.push({route,data:plain(data??null),options:plain(options??{})});if(route==='organizer')throw Error('FAKE_PRIVATE_DIAGNOSTIC_DO_NOT_SHOW');if(route==='sharing/download')return {filename:'fish.'+(data.format==='json'?'json':'md'),content:'FULL_LIBRARY_ARCHIVE',mime:'text/plain'};throw Error('Unexpected '+route);};
 c.ai.open=true;await c.loadSummaryProvider();assert(c.aiNote.textContent.includes('状态暂时无法确认'));assert(!c.aiNote.textContent.includes('FAKE_PRIVATE'));assert.equal(c.shareNotice.textContent,originalNotice);assert.equal(c.state.providerReady,false);assert(c.generateAI.disabled);assert(c.aiConsent.disabled);assert.equal(c.saveJSON.disabled,false);assert.equal(c.saveMD.disabled,false);
 c.saveFile=async(file,o)=>{saves.push({file,o});return 'saved';};await c.download('json');await c.download('markdown');assert.equal(saves.length,2);
 assert.deepEqual(c.calls.filter(x=>x.route==='sharing/download').map(x=>x.data),[{format:'json',confirm:true,expected_revision:'b'.repeat(64)},{format:'markdown',confirm:true,expected_revision:'b'.repeat(64)}]);assert(!c.calls.some(x=>x.route==='sharing/summary'));
});

test('a never-settling optional status check times out without blocking export or later promoting AI readiness',async()=>{
 const c=shareContext();await c.openShare();c.consent.checked=true;c.shareControls();let resolve;c.api=(route)=>{c.calls.push({route});return new Promise(r=>resolve=r);};c.ai.open=true;
 const pending=c.loadSummaryProvider();await settle();assert.equal(c.state.providerLoading,true);assert.equal(c.state.busy,false);assert.equal(c.saveJSON.disabled,false);assert.equal(c.saveMD.disabled,false);assert.equal(c.timers.size,1);
 const timer=[...c.timers.values()][0];assert(timer.ms>0&&timer.ms<=5000);timer.fn();await pending;assert.equal(c.state.providerLoading,false);assert.equal(c.state.providerReady,false);assert(c.generateAI.disabled);assert(c.aiNote.textContent.includes('完整 JSON 和 Markdown 仍可直接保存'));assert.equal(c.timers.size,0);
 resolve({provider:{credential_ready:true,model_ready:true,model:'LATE MODEL'}});await settle();assert.equal(c.state.providerReady,false);assert.equal(c.generateAI.dataset.ready,'false');assert(!c.aiNote.textContent.includes('LATE MODEL'));
});

test('optional status finishing after an archive switch cannot enable generation for the new archive',async()=>{
 const c=shareContext();await c.openShare();let resolve;c.api=(route,data,options)=>{c.calls.push({route,options:plain(options)});return new Promise(r=>resolve=r);};c.ai.open=true;const pending=c.loadSummaryProvider();await settle();
 c.S.libraryId='other-fish';c.S.libraryEpoch++;c.state.version++;c.share.d.open=false;resolve({provider:{credential_ready:true,model_ready:true,model:'OLD ARCHIVE MODEL'}});await pending;
 assert.equal(c.generateAI.dataset.ready,'false');assert.equal(c.state.providerReady,false);assert(!c.aiNote.textContent.includes('OLD ARCHIVE MODEL'));assert.equal(c.calls.at(-1).options.libraryId,'lib-only');assert.equal(c.timers.size,0);
});

test('a refreshed preview cannot inherit readiness or consent from an earlier pending status response',async()=>{
 const c=shareContext();await c.openShare();let resolve;const original=c.api;
 c.api=(route,data,options)=>route==='organizer'?new Promise(r=>resolve=r):original(route,data,options);c.ai.open=true;const old=c.loadSummaryProvider();await settle();
 c.aiConsent.checked=true;await c.openShare(true);assert.equal(c.aiConsent.checked,false);assert.equal(c.generateAI.dataset.ready,'false');assert.equal(c.state.providerReady,false);assert.equal(c.state.preview.content_revision,'b'.repeat(64));assert.equal(c.ai.open,false);
 resolve({provider:{credential_ready:true,model_ready:true,model:'BEFORE REFRESH'}});await old;assert.equal(c.state.providerReady,false);assert(!c.aiNote.textContent.includes('BEFORE REFRESH'));assert.equal(c.timers.size,0);
});

test('AI generation requires explicit verified model readiness as well as separate consent',async()=>{
 const c=shareContext();await c.openShare();let summaries=0;
 c.api=async(route)=>{if(route==='organizer')return {provider:{credential_ready:true,model_ready:false,model:'Incomplete model'}};if(route==='sharing/summary'){summaries++;return {summary_id:'one',reading_summary:{text:'Reading aid',coverage:{included_nodes:2,total_nodes:8}}};}throw Error('Unexpected '+route);};
 c.ai.open=true;await c.loadSummaryProvider();c.aiConsent.checked=true;await c.generateSummary();assert.equal(summaries,0);assert.equal(c.state.providerReady,false);assert(c.aiConsent.disabled);
 c.state.providerLoaded=false;c.api=async(route)=>{if(route==='organizer')return {provider:{credential_ready:true,model_ready:true,model:'Ready organizer'}};if(route==='sharing/summary'){summaries++;return {summary_id:'one',reading_summary:{text:'Reading aid',coverage:{included_nodes:2,total_nodes:8}}};}throw Error('Unexpected '+route);};
 await c.loadSummaryProvider();assert.equal(c.state.providerReady,true);assert.equal(c.generateAI.dataset.ready,'true');assert.equal(c.aiConsent.disabled,false);assert.equal(c.aiConsent.checked,false);assert(c.generateAI.disabled);assert(c.aiNote.textContent.includes('Ready organizer'));
 c.aiConsent.checked=true;c.shareControls();assert.equal(c.generateAI.disabled,false);await c.generateSummary();assert.equal(summaries,1);assert.equal(c.state.summary.summary_id,'one');assert(c.shareNotice.textContent.includes('2/8'));
});

test('malformed or stale model-status values never count as readiness',async()=>{
 for(const provider of [undefined,{credential_ready:'true',model_ready:true},{credential_ready:true},{credential_ready:true,model_ready:'true'}]){
  const c=shareContext();await c.openShare();c.ai.open=true;c.api=async()=>({provider});await c.loadSummaryProvider();assert.equal(c.state.providerReady,false);assert.equal(c.generateAI.dataset.ready,'false');assert(c.generateAI.disabled);assert.equal(c.saveJSON.disabled,true);c.consent.checked=true;c.shareControls();assert.equal(c.saveJSON.disabled,false);
 }
});

test('failed or incomplete core preview does not leave a ready export or an endless checking message',async()=>{
 for(const data of [null,{content_revision:'not-a-revision'}]){
  const c=shareContext();c.api=async()=>data;await c.openShare();assert.equal(c.state.preview,null);assert(c.shareNotice.textContent.includes('无法预览'));assert(!c.shareFacts.children.some(x=>x.textContent==='检查这个存档的范围…'));c.consent.checked=true;c.shareControls();assert(c.saveJSON.disabled);assert(c.saveMD.disabled);assert(c.generateAI.disabled);
 }
});
