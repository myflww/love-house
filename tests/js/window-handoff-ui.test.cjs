/* Actual handoff controls, inert DOM/clipboard/transport: never accesses a user archive. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/window-handoff-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));

class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.events={};this.disabled=false;this.hidden=false;this.open=false;this.checked=false;this.textContent='';this.value='';this.style={};const classes=new Set();this.classList={toggle:(n,on)=>on?classes.add(n):classes.delete(n),contains:n=>classes.has(n)};}
 append(...nodes){for(const node of nodes){this.children.push(node);if(node instanceof Element)node.parent=this;}}
 after(node){const list=this.parent.children;list.splice(list.indexOf(this)+1,0,node);node.parent=this.parent;}
 setAttribute(name,value){this.attributes[name]=String(value);}
 addEventListener(name,action){this.events[name]=action;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 click(){if(!this.disabled)return this.onclick?.();}
 focus(){this.focused=true;}
 select(){this.selected=true;}
}
function all(root){return [root,...root.children.flatMap(child=>child instanceof Element?all(child):[])];}
function packet(profile='M',text='ONLY_ARCHIVE_A_MEMORY'){return {profile,text,identity:{library_id:'archive-a',library_name:'鲸鱼娘'},included_memories:2,total_memories:10,chars:text.length,all_memory_loaded:false,redactions:{},automatic_recording:false};}
async function flush(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
function context({api,clipboard}={}){
 const body=new Element('body'),panel=new Element('div'),inherit=new Element('button');panel.id='libraryPanel';inherit.id='inheritLibraryBtn';panel.append(inherit);body.append(panel);
 const calls=[],copies=[],messages=[],events=[],S={mode:'serve',isDemo:false,libraryChanging:false,libraryId:'archive-a',libraryEpoch:4},MEMORY={busy:false};
 const get=id=>all(body).find(node=>node.id===id);
 const ctx={S,MEMORY,writeBusy:false,document:{body,getElementById:get,createTextNode:text=>({textContent:text}),execCommand:()=>{events.push('fallback-copy');return true;}},
  el:(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;},
  updateMemoryButtons(){events.push('update-controls');},
  api:async(...args)=>{calls.push(plain(args));return api?api(...args):packet(args[1]?.profile);},
  navigator:{clipboard:{writeText:async text=>{copies.push(text);if(clipboard)return clipboard(text);}}},
  toast:message=>messages.push(message),window:{LoveHousePortability:{openInheritance:()=>events.push('connection-wizard')}}};
 vm.runInNewContext(source,ctx);
 return {ctx,S,MEMORY,get,body,calls,copies,messages,events,sizes:()=>all(body).filter(x=>x.tagName==='BUTTON'&&/[小中大] · /.test(x.textContent))};
}

test('preview is scoped and copy requires explicit review consent; no configuration or capture starts',async()=>{
 const c=context();c.get('windowHandoffBtn').click();await flush();
 assert.deepEqual(c.calls,[['memory/handoff',{profile:'M'},{libraryId:'archive-a'}]]);
 assert.equal(c.get('windowHandoffDialog').open,true);assert.equal(c.get('copyWindowHandoff').disabled,true);
 await c.get('copyWindowHandoff').onclick();assert.deepEqual(c.copies,[]);
 c.get('windowHandoffConsent').checked=true;c.get('windowHandoffConsent').onchange();
 await c.get('copyWindowHandoff').click();assert.deepEqual(c.copies,['ONLY_ARCHIVE_A_MEMORY']);
 assert(c.messages[0].includes('持续存档请连接这个库'));assert(!c.events.includes('connection-wizard'));
 assert.equal(c.calls.length,1);assert(c.get('windowHandoffStatus').textContent.includes('摘录'));
});

test('S/M/L requests can overlap and only the most recent complete reply becomes copyable',async()=>{
 const pending=[];const c=context({api:(...args)=>new Promise(resolve=>pending.push({args,resolve}))});
 c.get('windowHandoffBtn').click();assert.equal(pending[0].args[1].profile,'M');
 c.sizes()[0].click();c.sizes()[2].click();assert.equal(pending.length,3);
 pending[1].resolve(packet('S','OLD_SMALL'));pending[0].resolve(packet('M','OLD_MEDIUM'));await flush();
 assert.equal(c.get('windowHandoffText').value,'');assert.equal(c.get('copyWindowHandoff').disabled,true);
 pending[2].resolve(packet('L','LATEST_LARGE'));await flush();assert.equal(c.get('windowHandoffText').value,'LATEST_LARGE');
 c.get('windowHandoffConsent').checked=true;c.get('windowHandoffConsent').onchange();await c.get('copyWindowHandoff').click();assert.deepEqual(c.copies,['LATEST_LARGE']);
 c.sizes()[0].click();assert.equal(c.get('windowHandoffConsent').checked,false);assert.equal(c.get('copyWindowHandoff').disabled,true);
});

test('switching a library clears the old preview and cannot copy it, even if old requests resolve late',async()=>{
 let resolve;const c=context({api:()=>new Promise(done=>resolve=done)});c.get('windowHandoffBtn').click();
 c.S.libraryId='archive-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();
 assert.equal(c.get('windowHandoffDialog').open,false);assert.equal(c.get('windowHandoffText').value,'');
 resolve(packet('M','OLD_ARCHIVE_A'));await flush();assert.equal(c.get('windowHandoffText').value,'');
 c.get('windowHandoffConsent').checked=true;c.get('windowHandoffConsent').onchange();await c.get('copyWindowHandoff').onclick();assert.deepEqual(c.copies,[]);
});

test('a selected preview is still scoped at click time if a library changes before controls repaint',async()=>{
 const c=context();c.get('windowHandoffBtn').click();await flush();c.get('windowHandoffConsent').checked=true;c.get('windowHandoffConsent').onchange();
 c.S.libraryId='archive-b';c.S.libraryEpoch++;await c.get('copyWindowHandoff').onclick();assert.deepEqual(c.copies,[]);
});

test('connecting a new window is a separate explicit action from preview or clipboard copy',async()=>{
 const c=context();c.get('windowHandoffBtn').click();await flush();
 const connect=all(c.body).find(e=>e.tagName==='BUTTON'&&e.textContent==='连接新窗口');connect.click();
 assert.equal(c.get('windowHandoffDialog').open,false);assert.deepEqual(c.copies,[]);assert(c.events.includes('connection-wizard'));
 assert.deepEqual(c.calls.map(x=>x[0]),['memory/handoff']);
 const notes=all(c.body).map(x=>x.textContent).join('\n');assert(notes.includes('新窗口持续自动存档仍需要连接本库'));
});

test('closing during a request prevents late data revival; failed clipboard uses explicit selection fallback',async()=>{
 let resolve;const c=context({api:()=>new Promise(done=>resolve=done)});c.get('windowHandoffBtn').click();
 all(c.get('windowHandoffDialog')).find(e=>e.attributes['aria-label']==='关闭记忆包').click();resolve(packet());await flush();
 assert.equal(c.get('windowHandoffDialog').open,false);assert.equal(c.get('windowHandoffText').value,'');
 const fallback=context({clipboard:()=>{throw Error('clipboard permission denied in fixture');}});fallback.get('windowHandoffBtn').click();await flush();fallback.get('windowHandoffConsent').checked=true;fallback.get('windowHandoffConsent').onchange();await fallback.get('copyWindowHandoff').click();
 assert.equal(fallback.get('windowHandoffText').selected,true);assert(fallback.events.includes('fallback-copy'));
});

test('demo, loading and busy library states never generate a personal memory package',async()=>{
 for(const mutate of [c=>c.S.isDemo=true,c=>c.S.mode='embedded',c=>c.S.libraryChanging=true,c=>c.MEMORY.busy=true,c=>c.ctx.writeBusy=true]){
  const c=context();mutate(c);c.ctx.updateMemoryButtons();assert.equal(c.get('windowHandoffBtn').disabled,true);c.get('windowHandoffBtn').onclick();await flush();assert.equal(c.calls.length,0);
 }
});

test('clipboard permission rejection never falls back to a newly generated packet without fresh consent',async()=>{
 let rejectClipboard;
 const c=context({api:async(route,body)=>packet(body.profile,'PREVIEW_'+body.profile),clipboard:()=>new Promise((resolve,reject)=>rejectClipboard=reject)});
 c.get('windowHandoffBtn').click();await flush();c.get('windowHandoffConsent').checked=true;c.get('windowHandoffConsent').onchange();
 const copying=c.get('copyWindowHandoff').click();assert.deepEqual(c.copies,['PREVIEW_M']);
 c.sizes()[0].click();await flush();assert.equal(c.get('windowHandoffText').value,'PREVIEW_S');assert.equal(c.get('windowHandoffConsent').checked,false);
 rejectClipboard(Error('permission denied after user changed preview'));await copying;
 assert.equal(c.events.includes('fallback-copy'),false);assert.notEqual(c.get('windowHandoffText').selected,true);
});
