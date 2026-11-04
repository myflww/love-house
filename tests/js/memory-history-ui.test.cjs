/* Run the shipped history dialog against an inert DOM and deferred requests. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-history-ui.js'),'utf8');
const copy=x=>JSON.parse(JSON.stringify(x));
const all=n=>[n,...(n.children||[]).flatMap(all)];
const words=n=>all(n).map(n=>n.textContent||'').join('\n');
class Element {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attrs={};this.events={};this.disabled=false;this.hidden=false;this.open=false;this.checked=false;this.className='';this._text='';this.id='';this.classList={add:(...names)=>{this.className=[...new Set([...this.className.split(' '),...names])].join(' ');}};}
 get textContent(){return this._text;}
 set textContent(value){this._text=String(value);this.replaceChildren();}
 get isConnected(){return ['BODY','HEAD'].includes(this.tagName)||!!this.parentElement?.isConnected;}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 append(...nodes){for(const n of nodes){n.remove?.();n.parentElement=this;this.children.push(n);}}
 prepend(...nodes){for(const n of [...nodes].reverse()){n.remove?.();n.parentElement=this;this.children.unshift(n);}}
 replaceChildren(...nodes){for(const n of this.children)n.parentElement=null;this.children=[];this.append(...nodes);}
 setAttribute(name,value){this.attrs[name]=String(value);}
 addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
 async emit(name,event={}){event.preventDefault??=()=>{};for(const fn of this.events[name]||[])await fn(event);}
 click(){if(!this.disabled)return this.onclick?.();}
 focus(){this.focused=true;if(this.ownerDocument)this.ownerDocument.activeElement=this;}
 showModal(){this.open=true;}
 close(){if(!this.open)return;this.open=false;queueMicrotask(()=>this.emit('close'));}
 set innerHTML(_value){throw Error('Untrusted history must use text nodes');}
}
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const historical=(extra={})=>({id:'old',label:'当时对朋友的理解',text:'我当时以为朋友生气了。',available:true,role:'user',recorded_at:1700000000,source_time:null,source_ids:['raw-user'],revision:{state:'historical'},...extra});
const packet=(extra={})=>({schema:'love-house-memory-versions/v1',library_id:'a',id:'old',read_only:true,will_call_model:false,world_truth_assessed:false,entries:[historical()],next_cursor:null,legacy_history_requires_confirmation:false,...extra});
const preview=(extra={})=>({library_id:'a',id:'old',read_only:true,expected_revision:'exact-reviewed-revision',entries:[{id:'legacy-source',label:'旧版停用的原话'}],node_count:1,source_count:1,...extra});
const restored=(extra={})=>({library_id:'a',id:'old',restored:true,current_memory_restored:false,world_truth_assessed:false,...extra});
function environment({transport,demo=false,reload}={}) {
 const body=new Element('body'),head=new Element('head'),detail=new Element('aside');detail.id='detail';body.append(detail);
 const S={mode:'serve',libraryId:'a',libraryEpoch:1,libraryChanging:false,isDemo:demo,selected:'old',byId:new Map([['old',{id:'old',meta:{memory_revision:{status:'historical'}}}]])};
 const get=id=>[...all(body),...all(head)].find(n=>n.id===id),calls=[],reloads=[];
 const document={body,head,getElementById:get,activeElement:null};
 const context={S,MEMORY:{busy:false},writeBusy:false,document,window:{},Date,
  el:(tag,cls,text)=>{const n=new Element(tag);n.ownerDocument=document;n.className=cls||'';if(text!==undefined)n.textContent=text;return n;},
  renderDetail(){detail.replaceChildren();},updateMemoryButtons(){},canWrite:()=>!demo,
  updateWriteState(){context.updateMemoryButtons();},
  reload:async(...args)=>{reloads.push(args);if(reload)return reload(...args);return true;},
  api:async(...args)=>{calls.push(copy(args));return transport?transport(...args):packet();}};
 vm.createContext(context);vm.runInContext(source,context);context.renderDetail();
 const open=async()=>{get('viewMemoryVersions').click();await flush();};
 return {context,S,body,head,get,calls,reloads,document,open,words:id=>words(get(id))};
}
async function inspectRestore(e){await e.open();await e.get('previewLegacyHistoryRestore').click();await flush();}
function checkRestore(e){const box=e.get('confirmLegacyHistoryRestore');box.checked=true;box.onchange();}

test('historical statements keep source time, markup stays text, and unavailable rows expose no body',async()=>{
 const quoted='<img onerror=STEAL()>这是当时的说法';
 const e=environment({transport:async()=>packet({entries:[historical({text:quoted}),historical({id:'paused',available:false,label:'PRIVATE TITLE',text:'PRIVATE BODY'})]})});
 assert(words(e.get('detail')).includes('这是一段历史说法'));
 await e.open();const text=e.words('memoryHistoryList');
 assert(text.includes(quoted));assert(text.includes('当时的说法'));assert(text.includes('原始时间：时间未提供'));
 assert(text.includes('当前不可读取'));assert(!text.includes('PRIVATE TITLE'));assert(!text.includes('PRIVATE BODY'));
 assert.equal(e.context.STEAL,undefined);assert.equal(e.calls.length,1);
});

test('library switches and closed dialogs discard late bodies while close returns focus only in its owner library',async()=>{
 const waiting=deferred(),e=environment({transport:()=>waiting.promise});
 await e.open();e.S.libraryId='b';e.S.libraryEpoch++;e.context.renderDetail();const nextButton=e.get('viewMemoryVersions');
 e.context.updateMemoryButtons();waiting.resolve(packet({entries:[historical({text:'DO NOT SHOW FROM OLD LIBRARY'})]}));await flush();
 assert.equal(e.get('memoryHistoryDialog').open,false);assert.equal(e.get('memoryHistoryList').children.length,0);
 assert(!words(e.body).includes('DO NOT SHOW'));assert.notEqual(e.document.activeElement,nextButton);
 const late=deferred(),closed=environment({transport:()=>late.promise});await closed.open();const origin=closed.get('viewMemoryVersions');
 closed.get('closeMemoryHistory').click();late.resolve(packet());await flush();
 assert.equal(closed.get('memoryHistoryDialog').open,false);assert.equal(closed.get('memoryHistoryList').children.length,0);
 assert.equal(closed.document.activeElement,origin);
});

test('failed first reads and failed next pages can be retried in place without losing earlier history',async()=>{
 let attempt=0;const e=environment({transport:async route=>{
  attempt++;if(attempt===1||attempt===3)throw Error('本地读取暂时失败');
  return packet({entries:[historical({id:attempt===2?'first':'second',text:attempt===2?'FIRST PAGE':'SECOND PAGE'})],next_cursor:attempt===2?'page-two':null});
 }});
 await e.open();assert.equal(e.get('memoryHistoryStatus').dataset.error,'true');assert.equal(e.get('retryMemoryHistory').hidden,false);
 await e.get('retryMemoryHistory').click();assert(e.words('memoryHistoryList').includes('FIRST PAGE'));
 await e.get('moreMemoryHistory').click();assert(e.words('memoryHistoryList').includes('FIRST PAGE'));
 assert.equal(e.get('retryMemoryHistory').hidden,false);await e.get('retryMemoryHistory').click();
 assert(e.words('memoryHistoryList').includes('FIRST PAGE'));assert(e.words('memoryHistoryList').includes('SECOND PAGE'));
 assert.equal(e.calls[2][0],e.calls[3][0]);assert(e.calls[3][0].endsWith('?cursor=page-two'));
 assert.equal(e.get('memoryHistoryStatus').dataset.error,'false');assert.equal(e.get('moreMemoryHistory').hidden,true);
});

test('legacy restore needs an inspected scope and checkbox and submits that exact revision once',async()=>{
 const pending=deferred();const e=environment({transport:async route=>route.endsWith('/history-restore-preview')?preview():route.endsWith('/history-restore')?pending.promise:packet({legacy_history_requires_confirmation:true})});
 await e.open();assert.equal(e.get('restoreLegacyHistory').disabled,true);await e.get('previewLegacyHistoryRestore').click();
 assert(e.words('legacyHistoryRestorePlan').includes('旧版停用的原话'));assert.equal(e.get('restoreLegacyHistory').disabled,true);
 checkRestore(e);assert.equal(e.get('restoreLegacyHistory').disabled,false);const write=e.get('restoreLegacyHistory').click();
 assert.equal(e.get('restoreLegacyHistory').disabled,true);e.get('restoreLegacyHistory').click();
 assert.deepEqual(e.calls.filter(c=>c[0].endsWith('/history-restore')),[['memories/old/history-restore',{confirm:true,expected_revision:'exact-reviewed-revision'},{libraryId:'a'}]]);
 let prevented=false;await e.get('memoryHistoryDialog').emit('cancel',{preventDefault(){prevented=true;}});assert(prevented);
 pending.resolve(restored());await write;
 assert(e.words('memoryHistoryStatus').includes('旧版历史已恢复可读'));assert.equal(e.get('memoryHistoryStatus').dataset.error,'false');
 assert.equal(e.get('confirmLegacyHistoryRestore').checked,false);assert.equal(e.get('restoreLegacyHistory').disabled,true);
 assert.equal(e.context.MEMORY.busy,false);assert.equal(e.context.writeBusy,false);
 const demo=environment({demo:true,transport:async route=>route.endsWith('-preview')?preview():packet({legacy_history_requires_confirmation:true})});
 await inspectRestore(demo);checkRestore(demo);assert.equal(demo.get('restoreLegacyHistory').disabled,true);demo.get('restoreLegacyHistory').click();assert.equal(demo.calls.length,2);
});

test('restore failures and ambiguous receipts stay visible, and saved refresh failures never turn into a generic read success',async()=>{
 for(const kind of ['rejected','wrong-library','refresh']) {
  const e=environment({reload:kind==='refresh'?async()=>{throw Error('图谱离线');}:undefined,transport:async route=>{
   if(route.endsWith('-preview'))return preview();
   if(route.endsWith('/history-restore')){if(kind==='rejected')throw Error('范围已变化');return restored(kind==='wrong-library'?{library_id:'b'}:{});}
   return packet({legacy_history_requires_confirmation:true});
  }});
  await inspectRestore(e);checkRestore(e);await e.get('restoreLegacyHistory').click();const text=e.words('memoryHistoryStatus');
  assert.equal(e.get('memoryHistoryStatus').dataset.error,'true',kind);
  assert(text.includes(kind==='rejected'?'恢复未完成':kind==='wrong-library'?'操作可能已保存':'历史恢复已保存，图谱刷新未完成'),text);
  assert(!text.includes('旧版历史已恢复可读'));assert.equal(e.get('confirmLegacyHistoryRestore').checked,false);
  assert.equal(e.get('restoreLegacyHistory').disabled,true);assert.equal(e.context.MEMORY.busy,false);
  assert.equal(e.calls.filter(c=>c[0].endsWith('/history-restore')).length,1);
 }
});

test('late preview or restore receipts cannot populate the next library or leave global write controls locked',async()=>{
 for(const phase of ['preview','restore']) {
  const pending=deferred();const e=environment({transport:async route=>route.endsWith('-preview')?(phase==='preview'?pending.promise:preview()):route.endsWith('/history-restore')?pending.promise:packet({legacy_history_requires_confirmation:true})});
  await e.open();const reading=e.get('previewLegacyHistoryRestore').click();if(phase==='restore'){await reading;checkRestore(e);e.get('restoreLegacyHistory').click();}
  e.S.libraryId='b';e.S.libraryEpoch++;e.context.renderDetail();e.context.updateMemoryButtons();
  pending.resolve(phase==='preview'?preview({entries:[{label:'OLD PRIVATE PREVIEW'}]}):restored());await flush();
  assert.equal(e.get('memoryHistoryDialog').open,false);assert.equal(e.get('legacyHistoryRestorePlan').children.length,0);
  assert(!words(e.body).includes('OLD PRIVATE PREVIEW'));assert.equal(e.context.MEMORY.busy,false);assert.equal(e.context.writeBusy,false);
  assert.notEqual(e.document.activeElement,e.get('viewMemoryVersions'));
 }
});
