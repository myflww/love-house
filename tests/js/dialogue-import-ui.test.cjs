/* Exercise the shipped actions with inert DOM and local API boundaries. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/dialogue-import-ui.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
function action(name,ctx){
 const line=source.match(new RegExp('^async function '+name+'\\([^\\n]*','m'));
 assert(line,`Actual shipped action ${name} is missing`);
 return vm.runInNewContext(line[0]+';'+name,ctx);
}
function context(){
 const S={libraryId:'one-agent-only',libraryEpoch:4,selected:'existing-selection'};
 const payload={content:'用户：一起看海\n助手：好呀',name:'explicit.txt',format:'text'};
 const state={owner:{id:S.libraryId,epoch:S.libraryEpoch},version:7,busy:false,reading:false,draft:null};
 const messages=[],rendered=[],calls=[],toasts=[];
 const ctx={S,state,writeBusy:false,payload:async()=>({...payload}),current:o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch,
  dialog:{open:true,close(){this.open=false;}},consent:{checked:true},check:{textContent:''},apply:{textContent:''},
  file:{value:'picked.json'},source:{value:'selected source'},preview:{replaceChildren(...v){messages.push(...v);},append(v){messages.push(v);}},
  make:(tag,cls,text)=>({tag,cls,text}),render:data=>rendered.push(plain(data)),sync(){},invalidateRecall(){},updateWriteState(){},
  by:()=>({classList:{remove(){}}}),setPanelOpen(){},resetBrowseAfterWrite(){},reload:async()=>{},fit(){},toast:(text,error)=>toasts.push({text,error}),
  api:async(route,data,options)=>{calls.push({route,data:plain(data),options:plain(options)});return {read_only:true,added:1,fingerprint:'preview-hash'};},
  calls,messages,rendered,toasts};
 ctx.canWrite=()=>!ctx.writeBusy;return ctx;
}
function ready(ctx){const payload={content:'用户：一起看海\n助手：好呀',name:'explicit.txt',format:'text'};ctx.state.draft={payload,key:JSON.stringify(payload),result:{added:1,fingerprint:'preview-hash'},version:ctx.state.version};}
test('preview alone is read-only, uses the original library header, and binds the content fingerprint',async()=>{
 const ctx=context();await action('previewFile',ctx)();
 assert.equal(ctx.calls.length,1);assert.equal(ctx.calls[0].route,'dialogue-import/preview');
 assert.deepEqual(ctx.calls[0].options,{libraryId:'one-agent-only'});assert.equal(ctx.calls[0].data.confirm,undefined);
 assert.equal(ctx.state.draft.result.fingerprint,'preview-hash');assert.equal(ctx.rendered.length,1);
 assert.equal(ctx.consent.checked,false);assert.equal(ctx.state.reading,false);assert.equal(ctx.writeBusy,false);
});
test('missing consent prevents apply; confirmed apply sends only the previewed content and fingerprint',async()=>{
 const ctx=context();ready(ctx);const run=action('applyFile',ctx);
 ctx.consent.checked=false;await run();assert.equal(ctx.calls.length,0);
 ctx.consent.checked=true;ctx.api=async(route,data,options)=>{ctx.calls.push({route,data:plain(data),options:plain(options)});return {added:1,skipped:0};};
 await run();assert.equal(ctx.calls.length,1);assert.equal(ctx.calls[0].route,'dialogue-import/apply');
 assert.equal(ctx.calls[0].data.confirm,true);assert.equal(ctx.calls[0].data.expected_fingerprint,'preview-hash');
 assert.deepEqual(ctx.calls[0].options,{libraryId:'one-agent-only'});assert.equal(ctx.dialog.open,false);
 assert.equal(ctx.state.busy,false);assert.equal(ctx.writeBusy,false);
});
test('stale library owners never send preview or apply requests',async()=>{
 const ctx=context();ready(ctx);ctx.S.libraryId='another-agent';ctx.S.libraryEpoch++;
 await action('previewFile',ctx)();await action('applyFile',ctx)();assert.equal(ctx.calls.length,0);
});
test('switch during file read is checked before any API request',async()=>{
 const ctx=context();ctx.payload=async()=>{ctx.S.libraryEpoch++;return {content:'old data',name:'old.txt',format:'text'};};
 await action('previewFile',ctx)();assert.equal(ctx.calls.length,0);assert.equal(ctx.rendered.length,0);
 const next=context();ready(next);next.payload=async()=>{next.S.libraryId='new-owner';return {content:'old data',name:'old.txt',format:'text'};};
 await action('applyFile',next)();assert.equal(next.calls.length,0);assert.equal(next.S.selected,'existing-selection');
});
test('switch during preview drops the response and does not attach old data to the new library',async()=>{
 const ctx=context();ctx.api=async()=>{ctx.S.libraryId='other';ctx.S.libraryEpoch++;return {read_only:true,added:1,fingerprint:'OLD'};};
 await action('previewFile',ctx)();assert.equal(ctx.rendered.length,0);assert.equal(ctx.state.draft,null);assert.equal(ctx.state.reading,false);
});
test('successful old-library apply arriving after switch never clears or reloads the new library UI',async()=>{
 const ctx=context();ready(ctx);let reloads=0;ctx.reload=async()=>{reloads++;};
 ctx.api=async(route,data,options)=>{ctx.calls.push({route,data:plain(data),options:plain(options)});ctx.S.libraryId='other';ctx.S.libraryEpoch++;return {added:1,skipped:0};};
 await action('applyFile',ctx)();assert.deepEqual(ctx.calls[0].options,{libraryId:'one-agent-only'});
 assert.equal(ctx.S.selected,'existing-selection');assert.equal(reloads,0);assert.equal(ctx.toasts.length,0);
 assert.equal(ctx.state.busy,false);assert.equal(ctx.writeBusy,false);
});
test('editing source or receiving non-read-only preview prevents confirmed apply',async()=>{
 const ctx=context();ready(ctx);ctx.payload=async()=>({content:'changed source',name:'explicit.txt',format:'text'});
 await action('applyFile',ctx)();assert.equal(ctx.calls.length,0);assert(ctx.toasts.some(item=>item.text.includes('重新预览')));
 const unsafe=context();unsafe.api=async()=>({read_only:false,added:1,fingerprint:'unsafe'});
 await action('previewFile',unsafe)();assert.equal(unsafe.state.draft,null);assert.equal(unsafe.rendered.length,0);
});
test('actual payload action refuses mixed sources and oversize requests, reads only user-selected file',async()=>{
 const ctx={file:{files:[{name:'selected.json',size:5,text:async()=>'[{"role":"user","content":"explicit"}]'}]},source:{value:''},name:{value:''},format:{value:'json'},TextEncoder};
 const run=action('payload',ctx);let value=await run();assert.equal(value.name,'selected.json');assert(value.content.includes('explicit'));
 ctx.source.value='also pasted';await assert.rejects(run(),/请选择一种/);
 ctx.source.value='';ctx.file.files[0].size=4194305;await assert.rejects(run(),/4 MiB/);
 ctx.file.files=[];ctx.source.value='';await assert.rejects(run(),/请选择/);
});
