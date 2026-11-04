/* Exercise the shipped component with local-only inert transport and DOM. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/update-checker-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));

class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.hidden=false;this.disabled=false;this.textContent='';this.value='';this.open=false;this.shown=0;this.listeners=new Map();const classes=new Set();this.classList={toggle:(name,on)=>on?classes.add(name):classes.delete(name),contains:name=>classes.has(name)};}
 append(...nodes){this.children.push(...nodes);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 removeAttribute(name){delete this.attributes[name];if(name==='href')delete this.href;}
 scrollIntoView(){this.scrolled=true;}
 focus(){this.focused=true;}
 addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(fn);}
 showModal(){this.open=true;this.shown++;}
 close(){this.open=false;for(const fn of this.listeners.get('close')||[])fn({target:this});}
}
function all(root){return [root,...root.children.flatMap(child=>child instanceof Element?all(child):[])];}
function state(extra={}){return {current_version:'0.6.0',platform:'macos',architecture:'arm64',settings:{auto_check:true,channel:'stable'},status:'up_to_date',checking:false,available:false,checked_at:1700000000,release:{version:'0.6.0',tag:'v0.6.0',notes:'release notes'},retry_after:0,...extra};}
function context({mode='serve',api}={}){
 const head=new Element('head'),body=new Element('body'),panel=new Element('div'),settingsBtn=new Element('button');panel.id='settings';panel.hidden=true;settingsBtn.id='settingsBtn';const roots=[head,body,panel,settingsBtn],timers=new Map(),documentListeners=new Map();let timerId=0;const calls=[],toasts=[];
 const get=id=>roots.flatMap(all).find(e=>e.id===id);
 const ctx={document:{head,body,hidden:false,createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),getElementById:get,
   querySelectorAll:selector=>selector==='dialog[open]'?roots.flatMap(all).filter(e=>e.tagName==='DIALOG'&&e.open):[],
   addEventListener(type,fn){if(!documentListeners.has(type))documentListeners.set(type,[]);documentListeners.get(type).push(fn);}},S:{mode},URL,Date,console,
   api:async(...args)=>{calls.push(plain(args));if(api)return api(...args);return state();},
   setTimeout:(callback,delay)=>{timers.set(++timerId,{callback,delay});return timerId;},clearTimeout:id=>timers.delete(id),
   toast:message=>toasts.push(message),setPanelOpen:(id,open)=>{get(id).hidden=!open;},window:{addEventListener(){}}};
 vm.runInNewContext(source,ctx);
 async function timer(delay){const entry=[...timers.entries()].find(([,t])=>t.delay===delay);assert(entry,`Expected a ${delay} ms timer`);timers.delete(entry[0]);await entry[1].callback();await Promise.resolve();await Promise.resolve();}
 return {ctx,get,calls,toasts,timer,timers,panel,body,settingsBtn};
}

test('startup requests a fresh check once even when settings are closed, while an up-to-date page stays quiet',async()=>{
 const c=context();assert.equal(c.calls.length,0);assert.equal(c.panel.hidden,true);assert(all(c.panel).some(e=>e.tagName==='SUMMARY'&&e.textContent==='发布通道与说明'));
 await c.timer(1500);
 assert.deepEqual(c.calls,[['updates',null,{scope:false}],['updates/check',{},{scope:false}]]);
 assert.equal(c.panel.hidden,true);assert.equal(c.get('automaticUpdateCheck').checked,true);
 assert(c.get('updateCheckStatus').textContent.includes('最新版本'));
 assert.equal(c.get('checkForUpdates').disabled,false);
 assert.equal(c.get('updateAvailableDialog').open,false);
 await c.timer(60000);assert.equal(c.calls.filter(call=>call[0]==='updates/check').length,1,'status polling must never force another check');
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
 const c=context({api:async(route)=>{if(route==='updates/check'){checked=true;return state({status:'checking',checking:true,settings:{auto_check:false,channel:'stable'}});}return checked?state({status:'available',available:true,release:compatible,settings:{auto_check:false,channel:'stable'}}):state({settings:{auto_check:false,channel:'stable'}});}});
 await c.timer(1500);await c.get('checkForUpdates').onclick();await c.get('checkForUpdates').onclick();
 assert.equal(c.calls.filter(x=>x[0]==='updates/check').length,1);assert.equal(c.get('checkForUpdates').disabled,true);
 await c.timer(1200);const links=all(c.panel).filter(e=>e.tagName==='A');
 assert.equal(links[0].hidden,false);assert.equal(links[0].href,compatible.asset_url);assert.equal(c.settingsBtn.classList.contains('update-ready'),true);
 assert(all(c.panel).some(e=>e.tagName==='PRE'&&e.textContent===compatible.notes));assert.equal(c.toasts.length,0);assert.equal(c.get('checkForUpdates').disabled,false);
 assert.equal(c.get('updateAvailableDialog').open,true);assert.equal(c.get('updateAvailableNotes').textContent,compatible.notes);
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
 const pending=c.timer(1500);await Promise.resolve();c.get('updateReleaseChannel').value='preview';await c.get('updateReleaseChannel').onchange();assert.equal(c.get('updateReleaseChannel').value,'preview');
 resolveOld(state({settings:{auto_check:true,channel:'stable'}}));await pending;assert.equal(c.get('updateReleaseChannel').value,'preview');
});

test('offline cached update is labeled and exported static HTML never contacts the local update endpoint',async()=>{
 const c=context({api:async()=>state({status:'offline',cached:true,available:true,release:{version:'0.6.1',tag:'v0.6.1',asset_url:'https://github.com/myflww/love-house/releases/download/v0.6.1/LoveHouse-macOS-arm64.zip'}})});
 await c.timer(1500);assert(c.get('updateCheckStatus').textContent.includes('缓存信息'));assert.equal(c.toasts.length,0);assert.equal(c.get('updateAvailableDialog').open,false);
 const standalone=context({mode:'embedded'});await standalone.timer(1500);assert.equal(standalone.calls.length,0);assert.equal(standalone.get('checkForUpdates').disabled,true);
});

function available(tag='v0.10.2rc3'){
 return state({current_version:'0.10.2rc2',platform:'windows',architecture:'x64',status:'available',available:true,
  settings:{auto_check:true,channel:'preview'},release:{tag,version:tag.slice(1),notes:'新版说明\n<script>只作为文字</script>',prerelease:true,
   url:'https://github.com/myflww/love-house/releases/tag/'+tag,
   asset_url:'https://github.com/myflww/love-house/releases/download/'+tag+'/LoveHouse-Windows-x64.zip'}});
}

test('a fresh startup update opens a native dialog with both versions, plain notes and trusted links',async()=>{
 const c=context({api:async()=>available()});await c.timer(1500);
 assert.equal(c.get('updateAvailableDialog').tagName,'DIALOG');assert.equal(c.get('updateAvailableDialog').open,true);
 assert.match(c.get('updateAvailableVersions').textContent,/0\.10\.2rc2.*0\.10\.2rc3/);
 assert.match(c.get('updateAvailableVersions').textContent,/预览版.*windows\/x64/);
 assert.equal(c.get('updateAvailableNotes').textContent,available().release.notes);
 assert.equal(c.get('updateAvailableDownload').href,available().release.asset_url);
 assert.equal(c.get('updateAvailableRelease').href,available().release.url);
 assert.equal(c.get('updateAvailableDownload').target,'_blank');assert.equal(c.get('updateAvailableDownload').rel,'noopener noreferrer');
 assert.equal(c.panel.hidden,true);assert.equal(c.toasts.length,0);
 c.get('deferUpdateAvailable').onclick();assert.equal(c.get('updateAvailableDialog').open,false);
 await c.timer(60000);assert.equal(c.get('updateAvailableDialog').shown,1,'same tag may not reopen in one session');
 assert.equal(c.calls.filter(call=>call[0]==='updates/check').length,1);
 // A new application window/session gets its own one-time reminder.
 const next=context({api:async()=>available()});await next.timer(1500);assert.equal(next.get('updateAvailableDialog').shown,1);
});

test('an existing modal keeps focus until it closes, then the update reminder can be deferred or closed',async()=>{
 let value=available();const c=context({api:async()=>value}),other=new Element('dialog');other.id='userDialog';c.body.append(other);other.showModal();
 await c.timer(1500);assert.equal(other.open,true);assert.equal(c.get('updateAvailableDialog').shown,0);
 await c.timer(1000);assert.equal(c.get('updateAvailableDialog').shown,0);
 other.close();await c.timer(1000);assert.equal(c.get('updateAvailableDialog').open,true);
 c.get('closeUpdateAvailable').onclick();assert.equal(c.get('updateAvailableDialog').open,false);
 await c.timer(60000);assert.equal(c.get('updateAvailableDialog').shown,1);
 value=available('v0.10.2rc4');await c.timer(60000);assert.equal(c.get('updateAvailableDialog').shown,2);
});

test('automatic opt-out preserves the chosen channel and suppresses startup checks and popups',async()=>{
 const value={...available(),settings:{auto_check:false,channel:'stable'}},c=context({api:async()=>value});await c.timer(1500);
 assert.deepEqual(c.calls.map(call=>call[0]),['updates']);assert.equal(c.get('updateReleaseChannel').value,'stable');assert.equal(c.get('updateAvailableDialog').shown,0);
 await c.get('checkForUpdates').onclick();assert.equal(c.get('updateAvailableDialog').shown,1,'explicit manual check may notify');
});

test('a failed fresh startup check must not popup a stale cached update',async()=>{
 const c=context({api:async route=>{if(route==='updates/check')throw Error('synthetic offline');return available();}});
 await c.timer(1500);assert.equal(c.get('updateAvailableDialog').shown,0);assert.equal(c.toasts.length,0);
 await c.timer(60000);assert.equal(c.get('updateAvailableDialog').shown,0);
});

test('hidden documents wait to show an update and unsafe dialog download links never become active',async()=>{
 const value=available();value.release.asset_url='https://evil.invalid/fake.exe';value.release.url='https://evil.invalid/notes';
 const c=context({api:async()=>value});c.ctx.document.hidden=true;await c.timer(1500);assert.equal(c.get('updateAvailableDialog').shown,0);
 c.ctx.document.hidden=false;await c.timer(1000);assert.equal(c.get('updateAvailableDialog').open,true);
 assert.equal(c.get('updateAvailableDownload').hidden,true);assert.equal(c.get('updateAvailableDownload').href,undefined);
 assert.equal(c.get('updateAvailableRelease').href,'https://github.com/myflww/love-house/releases');
});
