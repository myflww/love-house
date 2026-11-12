/* Optional public-release checks; no memories/keys leave the local controller. */
(()=>{
'use strict';
const panel=document.getElementById('settings');
if(!panel||typeof api!=='function')return;
const make=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const style=make('style');style.textContent=`
.house-update-card{border-top:2px solid var(--line);margin-top:15px;padding-top:14px;font-size:12px}.house-update-head{display:flex;justify-content:space-between;align-items:center;gap:8px}.house-update-head strong{font-size:13px}.house-update-state{margin:9px 0 5px;line-height:1.65;overflow-wrap:anywhere}.house-update-actions{display:flex;gap:7px;flex-wrap:wrap;margin:9px 0}.house-update-actions .btn{font-size:12px}.house-update-card .update-auto{display:flex;align-items:center;gap:8px;margin:10px 0}.house-update-card input[type=checkbox]{width:auto}.house-update-card select{max-width:145px}.house-update-card .update-note{font-size:11px;color:var(--muted);line-height:1.7;margin:6px 0}.house-update-card details{margin-top:8px}.house-update-card summary{cursor:pointer;color:var(--accent)}.house-update-notes{font:inherit;font-size:12px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;padding:10px;border:1px solid var(--line);background:var(--soft)}#settingsBtn.update-ready::after{content:'';position:absolute;right:3px;top:3px;width:7px;height:7px;background:#c75d75;border:1px solid var(--paper);box-shadow:1px 1px 0 var(--ink);pointer-events:none}`;
document.head.append(style);
const card=make('section','house-update-card');card.id='updateChecker';card.setAttribute('aria-label','爱之屋版本更新');
const heading=make('div','house-update-head'),title=make('strong','','爱之屋版本'),version=make('span','mono','');heading.append(title,version);
const status=make('p','house-update-state','正在读取版本信息…');status.id='updateCheckStatus';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
const actions=make('div','house-update-actions'),check=make('button','btn','检查更新'),download=make('a','btn primary','下载新版'),releasePage=make('a','btn','发布页面');check.id='checkForUpdates';check.type='button';check.dataset.hintTitle='检查更新';check.dataset.hintDescription='查询爱之屋的公开版本，只提示，不下载或安装，也不会发送记忆。';
for(const link of [download,releasePage]){link.target='_blank';link.rel='noopener noreferrer';}download.hidden=true;releasePage.href='https://github.com/myflww/love-house/releases';actions.append(check,download,releasePage);
const autoLabel=make('label','update-auto'),auto=make('input');auto.id='automaticUpdateCheck';auto.type='checkbox';auto.checked=true;autoLabel.append(auto,document.createTextNode('自动检查新版本'));
const advanced=make('details'),advancedTitle=make('summary','','发布通道与说明'),channelLabel=make('label','setting-row'),channel=make('select');channel.id='updateReleaseChannel';channel.setAttribute('aria-label','更新发布通道');for(const [value,label]of [['stable','稳定版'],['preview','包含预览版']]){const o=make('option','',label);o.value=value;channel.append(o);}channelLabel.append(make('span','','更新通道'),channel);
const privacy=make('p','update-note','仅向 GitHub 查询公开版本，不发送记忆、对话或密钥。每天自动检查一次；下载后由你决定安装。'),last=make('p','update-note'),notesBox=make('details'),notesTitle=make('summary','','查看更新说明'),notes=make('pre','house-update-notes');notesBox.append(notesTitle,notes);notesBox.hidden=true;advanced.append(advancedTitle,channelLabel,privacy);card.append(heading,status,actions,autoLabel,last,notesBox,advanced);const settingsHeading=panel.querySelector?.('.setting-title');if(settingsHeading)settingsHeading.after(card);else panel.append(card);
let data=null,busy=false,notified='',pollTimer=null,bootAttempts=0,requestVersion=0;
function trustedLink(value,kind){try{const u=new URL(value),p=decodeURIComponent(u.pathname);return u.protocol==='https:'&&u.host==='github.com'&&!u.username&&!u.password&&!u.search&&!u.hash&&!/[\\\x00-\x1f]/.test(p)&&!p.split('/').some(x=>x==='.'||x==='..')&&u.pathname.startsWith('/myflww/love-house/releases/'+(kind==='asset'?'download/':'tag/'))?u.href:'';}catch{return '';}}
function render(value){
 data=value;version.textContent='v'+String(value.current_version||'');auto.checked=value.settings?.auto_check!==false;channel.value=value.settings?.channel==='preview'?'preview':'stable';check.disabled=busy||value.checking===true;auto.disabled=channel.disabled=busy;check.textContent=value.checking?'正在检查…':'检查更新';
 const item=value.release||{},newVersion=value.available===true,offline=['offline','rate_limited','invalid_response'].includes(value.status);let text;
 if(value.checking)text='正在检查当前平台的新版本…';
 else if(offline)text=value.status==='rate_limited'?'GitHub 暂时限制查询，请稍后再试。':value.status==='invalid_response'?'版本信息暂时无法读取，请稍后再试。':'暂时无法连接 GitHub，记忆保存与聊天接入照常可用。';
 else if(newVersion)text='发现新版本 v'+String(item.version||'')+(item.prerelease?' · 预览版':'');
 else if(value.status==='not_checked')text=value.settings?.auto_check===false?'自动检查已关闭，你仍可以手动检查。':'尚未检查新版本。';
 else if(!value.release)text='发布页面暂时没有适合此平台的安装包。';
 else text='已是此平台的最新版本。';
 if(!offline&&!newVersion&&value.other_platform_version)text+=' 其他平台或架构的新版仍在单独发布。';
 if(offline&&newVersion)text+=' 上次检查发现 v'+String(item.version||'')+'，可查看缓存信息。';
 status.textContent=text;const asset=trustedLink(item.asset_url,'asset'),page=trustedLink(item.url,'release');download.hidden=!(newVersion&&asset);if(asset)download.href=asset;else download.removeAttribute('href');download.dataset.hintDescription='打开 GitHub 上适合 '+String(value.platform||'当前平台')+' / '+String(value.architecture||'')+' 的安装包；不会自动安装。';releasePage.href=page||'https://github.com/myflww/love-house/releases';
 notes.textContent=String(item.notes||'此版本没有填写更新说明。');notesBox.hidden=!value.release;last.textContent=value.checked_at?'上次成功检查：'+new Date(value.checked_at*1000).toLocaleString()+(value.cached?' · 缓存结果':''):'';
 document.getElementById('settingsBtn')?.classList.toggle('update-ready',newVersion);
 if(newVersion&&!offline&&notified!==item.tag){notified=item.tag;if(typeof toast==='function')toast('爱之屋有新版本，可在设置中查看。');}
 if(value.checking)schedulePoll(1200);
}
function schedulePoll(delay){clearTimeout(pollTimer);pollTimer=setTimeout(refresh,delay);}
async function refresh(){if(typeof S!=='undefined'&&S.mode!=='serve')return;if(busy){schedulePoll(1500);return;}const current=++requestVersion;try{const result=await api('updates',undefined,{scope:false});if(current!==requestVersion)return;render(result);}catch{if(current!==requestVersion)return;status.textContent='版本检测暂时不可用，记忆功能照常可用。';check.disabled=false;}if(!data?.checking)schedulePoll(60000);}
async function checkNow(){if(busy||data?.checking)return;busy=true;++requestVersion;check.disabled=true;status.textContent='正在检查新版本…';let notice='';try{const result=await api('updates/check',{}, {scope:false});render(result);if(!result.checking&&result.retry_after>0)notice=' 请在 '+result.retry_after+' 秒后再次检查。';}catch{notice='暂时无法检查，请稍后重试。';}finally{busy=false;if(data)render(data);else check.disabled=false;if(notice)status.textContent+=notice;}}
async function saveSettings(){if(busy)return;busy=true;++requestVersion;auto.disabled=channel.disabled=true;let failed=false;try{render(await api('updates/settings',{auto_check:auto.checked,channel:channel.value},{scope:false}));}catch{failed=true;if(data){auto.checked=data.settings?.auto_check!==false;channel.value=data.settings?.channel||'stable';}}finally{busy=false;if(data)render(data);auto.disabled=channel.disabled=false;if(failed)status.textContent='更新设置未能保存，请稍后重试。';}}
check.onclick=checkNow;auto.onchange=channel.onchange=saveSettings;
function open(){if(typeof setPanelOpen==='function')setPanelOpen('settings',true,{focus:false});card.scrollIntoView({block:'nearest'});check.focus();refresh();}
window.LoveHouseUpdates={open,check:()=>{open();return checkNow();}};
function boot(){if(typeof S==='undefined'||S.mode==='loading'){if(++bootAttempts<120)setTimeout(boot,500);return;}if(S.mode==='serve')refresh();else{status.textContent='请在爱之屋桌面软件中检查更新。';check.disabled=auto.disabled=channel.disabled=true;}}
setTimeout(boot,1500);window.addEventListener('beforeunload',()=>clearTimeout(pollTimer));
})();
