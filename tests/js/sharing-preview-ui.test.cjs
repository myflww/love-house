/* The complete shipped dialog: failed/slow optional organizer cannot gate export. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-portability-ui.js'),'utf8');
const all=e=>[e,...e.children.flatMap(x=>x instanceof Element?all(x):[])];
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.disabled=false;this.hidden=false;this.open=false;this.checked=false;this.textContent='';this.events={};this.classList={add(){}};}
 append(...nodes){for(const n of nodes){this.children.push(n);if(n instanceof Element)n.parent=this;}}
 before(node){this.parent.children.splice(this.parent.children.indexOf(this),0,node);node.parent=this.parent;}
 after(node){this.parent.children.splice(this.parent.children.indexOf(this)+1,0,node);node.parent=this.parent;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 setAttribute(){}
 addEventListener(k,v){this.events[k]=v;}
 querySelector(){return this.children.find(e=>e.tagName==='STRONG');}
 querySelectorAll(tag){return all(this).filter(e=>e.tagName===tag.toUpperCase());}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const preview={content_revision:'a'.repeat(64),name:'肥鱼',node_count:2,edge_count:0,archive_count:1,privacy:{redactions:{}}};
function setup(api){
 const body=new Element('body'),head=new Element('head');
 for(const id of ['libraryPanel','newLibraryBtn','createBackup','backupBtn','backupPanel']){const e=new Element('div');e.id=id;body.append(e);if(id==='backupPanel')e.append(new Element('strong'));}
 const get=id=>[...all(body),...all(head)].find(e=>e.id===id),requests=[],timers=new Map();let timerId=0;
 const ctx={MEMORY:{busy:false},S:{mode:'serve',libraryId:'fish-a',libraryEpoch:1,isDemo:false,libraryChanging:false},writeBusy:false,
 document:{body,head,getElementById:get,createTextNode:text=>({textContent:text})},
 el:(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';e.textContent=text||'';return e;},navigator:{},
 api:(...args)=>{requests.push(args);return api(...args);},num:x=>Number(x)||0,libraryName:()=> '肥鱼',
 confirmationList:(box,rows)=>box.replaceChildren(...rows.map(([label,value])=>{const e=new Element('p');e.textContent=label+': '+value;return e;})),
 updateMemoryButtons(){},setTimeout:(callback,delay)=>{const id=++timerId;timers.set(id,{callback,delay});return id;},clearTimeout:id=>timers.delete(id),window:{addEventListener(){}}};
 vm.runInNewContext(source,ctx);
 return {ctx,get,requests,timers,words:()=>all(get('memoryShareDialog')).map(e=>e.textContent).join('\n'),
  open:()=>ctx.window.LoveHousePortability.openShare(),consent:()=>{get('sharePersonalConsent').checked=true;get('sharePersonalConsent').onchange();}};
}
test('opening sharing requests only its archive, never an optional provider; consent enables complete exports',async()=>{
 const c=setup(async route=>{assert.equal(route,'sharing/preview');return preview;});await c.open();c.consent();
 assert.equal(c.requests.length,1);assert.equal(c.get('downloadMemoryJSON').disabled,false);assert.equal(c.get('downloadMemoryMarkdown').disabled,false);
 assert(c.words().includes('2 条记忆'));assert(!c.words().includes('检查这个存档的范围'));
});
test('a failed preview replaces the top loading message and refresh retries the real request',async()=>{
 let fail=true;const c=setup(async()=>{if(fail)throw Error('合成读取失败');return preview;});await c.open();c.consent();
 assert.equal(c.get('downloadMemoryJSON').disabled,true);assert(c.words().includes('无法读取分享范围：合成读取失败'));assert(!c.words().includes('检查这个存档的范围'));
 fail=false;await c.get('refreshMemoryShare').onclick();c.consent();assert.equal(c.requests.length,2);assert.equal(c.get('downloadMemoryJSON').disabled,false);
});
test('an unanswered preview times out visibly, and a late result cannot revive the old state',async()=>{
 let release;const c=setup(()=>new Promise(resolve=>release=resolve));const loading=c.open();
 const timeout=[...c.timers.values()].find(t=>t.delay===30000);assert(timeout);timeout.callback();await loading;c.consent();
 assert(c.words().includes('读取超时'));assert.equal(c.get('downloadMemoryJSON').disabled,true);
 release(preview);await Promise.resolve();await Promise.resolve();assert.equal(c.get('downloadMemoryJSON').disabled,true);
});
test('optional provider failure or timeout cannot disable JSON and Markdown after consent',async()=>{
 let mode='error';const c=setup(async route=>{if(route==='sharing/preview')return preview;if(mode==='error')throw Error('模型配置不可读');return new Promise(()=>{});});await c.open();c.consent();
 const details=all(c.get('memoryShareDialog')).find(e=>e.tagName==='DETAILS');details.open=true;
 await details.ontoggle();for(let i=0;i<8;i++)await Promise.resolve();
 assert(c.words().includes('可选阅读索引暂不可用'));assert.equal(c.get('downloadMemoryJSON').disabled,false);assert.equal(c.get('downloadMemoryMarkdown').disabled,false);
 mode='hang';details.open=false;details.ontoggle();details.open=true;details.ontoggle();
 const timeout=[...c.timers.values()].find(t=>t.delay===30000);assert(timeout);timeout.callback();for(let i=0;i<8;i++)await Promise.resolve();
 assert.equal(c.get('downloadMemoryJSON').disabled,false);assert(c.words().includes('完整分享仍可直接保存'));
});
