/* Exercise the shipped component with local-only inert transport and DOM. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/update-checker-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));

class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.hidden=false;this.disabled=false;this.textContent='';this.value='';const classes=new Set();this.classList={toggle:(name,on)=>on?classes.add(name):classes.delete(name),contains:name=>classes.has(name)};}
 append(...nodes){this.children.push(...nodes);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 removeAttribute(name){delete this.attributes[name];if(name==='href')delete this.href;}
 scrollIntoView(){this.scrolled=true;}
 focus(){this.focused=true;}
}
function all(root){return [root,...root.children.flatMap(child=>child instanceof Element?all(child):[])];}
function state(extra={}){return {current_version:'0.6.0',platform:'macos',architecture:'arm64',settings:{auto_check:true,channel:'stable'},status:'up_to_date',checking:false,available:false,checked_at:1700000000,release:{version:'0.6.0',tag:'v0.6.0',notes:'release notes'},retry_after:0,...extra};}
function context({mode='serve',api}={}){
 const head=new Element('head'),panel=new Element('div'),settingsBtn=new Element('button');panel.id='settings';panel.hidden=true;settingsBtn.id='settingsBtn';const roots=[head,panel,settingsBtn],timers=new Map();let timerId=0;const calls=[],toasts=[];
 const get=id=>roots.flatMap(all).find(e=>e.id===id);
 const ctx={document:{head,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),getElementById:get},S:{mode},URL,Date,console,
   api:async(...args)=>{calls.push(plain(args));if(api)return api(...args);return state();},
   setTimeout:(callback,delay)=>{timers.set(++timerId,{callback,delay});return timerId;},clearTimeout:id=>timers.delete(id),
   toast:message=>toasts.push(message),setPanelOpen:(id,open)=>{get(id).hidden=!open;},window:{addEventListener(){}}};
 vm.runInNewContext(source,ctx);
 async function timer(delay){const entry=[...timers.entries()].find(([,t])=>t.delay===delay);assert(entry,`Expected a ${delay} ms timer`);timers.delete(entry[0]);await entry[1].callback();await Promise.resolve();await Promise.resolve();}
 return {ctx,get,calls,toasts,timer,timers,panel,settingsBtn};
}

test('startup checks automatically even when settings are closed, without opening or blocking the page',async()=>{
 const c=context();assert.equal(c.calls.length,0);assert.equal(c.panel.hidden,true);assert(all(c.panel).some(e=>e.tagName==='SUMMARY'&&e.textContent==='发布通道与说明'));
 await c.timer(1500);
 assert.deepEqual(c.calls,[['updates',null,{scope:false}]]);
 assert.equal(c.panel.hidden,true);assert.equal(c.get('automaticUpdateCheck').checked,true);
 assert(c.get('updateCheckStatus').textContent.includes('最新版本'));
 assert.equal(c.get('checkForUpdates').disabled,false);
});

test('offline first check has a clear status and manual retry works with null initial release',async()=>{
 let failing=true;
 const c=context({api:async()=>{if(failing)throw Error('network disabled in test');return state({status:'not_checked',checked_at:null,release:null});}});
 await c.timer(1500);assert(c.get('updateCheckStatus').textContent.includes('暂时不可用'));
 assert.equal(c.get('checkForUpdates').disabled,false);failing=false;await c.get('checkForUpdates').onclick();
 assert.equal(c.calls.at(-1)[0],'updates/check');assert.equal(c.calls.at(-1)[1] instanceof Object,true);
 assert(c.get('updateCheckStatus').textContent.includes('尚未检查'));assert.equal(c.get('checkForUpdates').disabled,false);
});

test('user can disable automatic checks and switch release channel, with no memory or model fields',async()=>{
 const c=context({api:async(route,body)=>route==='updates/settings'?state({settings:{...body},status:'not_checked',checked_at:null,release:null}):state()});
 await c.timer(1500);const automatic=c.get('automaticUpdateCheck'),channel=c.get('updateReleaseChannel');
 automatic.checked=false;await automatic.onchange();assert.deepEqual(c.calls.at(-1),['updates/settings',{auto_check:false,channel:'stable'},{scope:false}]);
 assert.equal(automatic.checked,false);assert(c.get('updateCheckStatus').textContent.includes('自动检查已关闭'));
 channel.value='preview';await channel.onchange();assert.deepEqual(c.calls.at(-1),['updates/settings',{auto_check:false,channel:'preview'},{scope:false}]);
 assert.equal(channel.value,'preview');assert.equal(automatic.disabled,false);assert.equal(c.get('checkForUpdates').disabled,false);
});

test('manual checking coalesces clicks and polls to show a platform package and plain-text release notes',async()=>{
 let checked=false;
 const compatible={version:'0.6.1',tag:'v0.6.1',notes:'<script>never execute</script>',prerelease:false,
   url:'https://github.com/myflww/love-house/releases/tag/v0.6.1',asset_url:'https://github.com/myflww/love-house/releases/download/v0.6.1/LoveHouse-macOS-arm64.zip'};
 const c=context({api:async(route)=>{if(route==='updates/check'){checked=true;return state({status:'checking',checking:true});}return checked?state({status:'available',available:true,release:compatible}):state();}});
 await c.timer(1500);await c.get('checkForUpdates').onclick();await c.get('checkForUpdates').onclick();
 assert.equal(c.calls.filter(x=>x[0]==='updates/check').length,1);assert.equal(c.get('checkForUpdates').disabled,true);
 await c.timer(1200);const links=all(c.panel).filter(e=>e.tagName==='A');
 assert.equal(links[0].hidden,false);assert.equal(links[0].href,compatible.asset_url);assert.equal(c.settingsBtn.classList.contains('update-ready'),true);
 assert(all(c.panel).some(e=>e.tagName==='PRE'&&e.textContent===compatible.notes));assert.equal(c.toasts.length,1);assert.equal(c.get('checkForUpdates').disabled,false);
});

test('unrelated platform release never exposes a download, and unsafe external/cross-repo links are refused',async()=>{
 const c=context({api:async()=>state({other_platform_version:'0.7.0rc1'})});await c.timer(1500);
 let links=all(c.panel).filter(e=>e.tagName==='A');assert.equal(links[0].hidden,true);assert(c.get('updateCheckStatus').textContent.includes('其他平台或架构'));
 for(const asset_url of ['https://evil.example/fake.exe','https://github.com/another/repo/releases/download/v1/a.zip','https://user@github.com/myflww/love-house/releases/download/v1/a.zip','https://github.com/myflww/love-house/releases/download/v1/%2e%2e/%2e%2e/outside']){
  c.ctx.api=async()=>state({available:true,status:'available',release:{version:'9.0.0',tag:'v9.0.0',asset_url,url:'https://evil.example/notes'}});
  await c.get('checkForUpdates').onclick();links=all(c.panel).filter(e=>e.tagName==='A');assert.equal(links[0].hidden,true);assert.equal(links[0].href,undefined);assert.equal(links[1].href,'https://github.com/myflww/love-house/releases');
 }
});

test('late startup status cannot overwrite a user channel change',async()=>{
 let resolveOld;
 const c=context({api:(route,body)=>route==='updates'?new Promise(resolve=>resolveOld=resolve):Promise.resolve(state({settings:body}))});
 await c.timer(1500);c.get('updateReleaseChannel').value='preview';await c.get('updateReleaseChannel').onchange();assert.equal(c.get('updateReleaseChannel').value,'preview');
 resolveOld(state({settings:{auto_check:true,channel:'stable'}}));await Promise.resolve();await Promise.resolve();assert.equal(c.get('updateReleaseChannel').value,'preview');
});

test('offline cached update is labeled and exported static HTML never contacts the local update endpoint',async()=>{
 const c=context({api:async()=>state({status:'offline',cached:true,available:true,release:{version:'0.6.1',tag:'v0.6.1',asset_url:'https://github.com/myflww/love-house/releases/download/v0.6.1/LoveHouse-macOS-arm64.zip'}})});
 await c.timer(1500);assert(c.get('updateCheckStatus').textContent.includes('缓存信息'));assert.equal(c.toasts.length,0);
 const standalone=context({mode:'embedded'});await standalone.timer(1500);assert.equal(standalone.calls.length,0);assert.equal(standalone.get('checkForUpdates').disabled,true);
});
