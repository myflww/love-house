"""Shared native DOM acceptance for the guided workspace, on synthetic data only."""

CONTROL_HELPER = r"""
const nativeVisible=e=>!!e&&!e.hidden&&!e.closest('[hidden]')&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&e.getClientRects().length>0;
const nativeClick=async id=>{
 const e=document.getElementById(id);if(!e)throw Error('workspace_control');
 if(!nativeVisible(e)){
  const menu=e.closest('#workspaceDisplayMenu,#workspaceAddMenu');
  if(menu){const trigger=document.getElementById(menu.id==='workspaceDisplayMenu'?'workspaceDisplayButton':'workspaceAddButton');if(!nativeVisible(trigger))throw Error('workspace_control');trigger.click();}
  else if(e.closest('#sidebar')){const trigger=document.getElementById('menuBtn');if(!nativeVisible(trigger))throw Error('workspace_control');trigger.click();}
 }
 e.scrollIntoView({block:'nearest'});
 const r=e.getBoundingClientRect();if(!nativeVisible(e)||e.disabled||r.right<=0||r.left>=innerWidth||r.bottom<=0||r.top>=innerHeight)throw Error('workspace_control');
 e.click();await new Promise(resolve=>setTimeout(resolve,0));
};
"""

SCRIPT = r"""
const by=id=>document.getElementById(id),check=(ok,code)=>{if(!ok)throw Error(code);};
const wait=async test=>{const end=performance.now()+10000;while(!test()){if(performance.now()>end)throw Error('workspace_wait');await new Promise(r=>setTimeout(r,30));}};
const shown=e=>!!e&&!e.hidden&&!e.closest('[hidden]')&&getComputedStyle(e).display!=='none'&&getComputedStyle(e).visibility!=='hidden'&&e.getClientRects().length>0;
const click=async id=>{const e=by(id);check(shown(e)&&!e.disabled,'workspace_control');e.scrollIntoView({block:'nearest'});const r=e.getBoundingClientRect();check(r.top<innerHeight&&r.bottom>0&&r.left<innerWidth&&r.right>0,'workspace_control');e.click();await new Promise(r=>setTimeout(r,0));};
const originalApi=api,originalLibrary=S.libraryId;let paid=0,writes=0,reviewPreviews=0;
const canonical=g=>JSON.stringify({nodes:g.nodes.map(n=>[n.id,n.label,n.text,n.kind,n.tags,n.recalls,n.created,n.updated,n.event_at,n.valid_from,n.valid_to,n.superseded_by,n.meta]).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))),edges:g.edges.map(e=>[e.source,e.target,e.stored_w,e.n,e.last,e.valid_from,e.valid_to]).sort((a,b)=>String(a[0]+a[1]).localeCompare(String(b[0]+b[1])))});
const before=canonical(await api('graph'));
api=async function(route,body,...args){const path=String(route).split('?')[0];if(['persona/organize','organizer/run','sharing/summary','idle-review/run'].includes(path)||path.startsWith('idle-review/proposals/')){paid++;throw Error('workspace_paid');}if(path==='idle-review/preview'){const value=await originalApi(route,body,...args);check(value.read_only===true&&value.model_called===false&&value.library_id===originalLibrary,'workspace_idle_review');reviewPreviews++;return value;}if(body!==undefined)writes++;return originalApi(route,body,...args);};
try{
 window.LoveHouseWorkspace.closeMenus(false);for(const id of Object.keys(PANELS))setPanelOpen(id,false,{restore:false});
 const header=document.querySelector('#app>header');
 for(const [id,label]of [['menuBtn','记忆'],['companionBtn','连接'],['organizeBtn','整理'],['workspaceDisplayButton','显示'],['settingsBtn','更多']]){
  check(document.querySelectorAll('#'+id).length===1&&shown(by(id))&&by(id).textContent.includes(label),'workspace_navigation');
 }
 const rect=header.getBoundingClientRect();
 check(rect.left>=-1&&rect.right<=innerWidth+1&&header.scrollWidth<=header.clientWidth+1&&document.documentElement.scrollWidth<=innerWidth+1,'workspace_overflow');
 await click('workspaceAddButton');await wait(()=>shown(by('workspaceAddMenu')));
 for(const id of ['addBtn','importBtn','dialogueImportBtn','importMemoryShareBtn'])check(shown(by(id)),'workspace_add');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 await wait(()=>by('workspaceAddMenu').hidden);check(document.activeElement===by('workspaceAddButton'),'workspace_focus');
 await click('workspaceAddButton');await click('addBtn');await wait(()=>by('addDialog').open);
 await click('cancelAdd');await wait(()=>!by('addDialog').open);check(document.activeElement===by('workspaceAddButton'),'workspace_focus');
 await click('workspaceDisplayButton');await wait(()=>shown(by('workspaceDisplayMenu')));
 for(const id of ['filterBtn','timeBtn','detailBtn','viewBtn','layoutBtn','pauseBtn','themeBtn','fullscreenBtn'])check(shown(by(id)),'workspace_navigation');
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 await wait(()=>by('workspaceDisplayMenu').hidden);check(document.activeElement===by('workspaceDisplayButton'),'workspace_focus');
 await click('companionBtn');await wait(()=>shown(by('aiPanel')));await click('connectTab');
 await wait(()=>shown(by('connectionMemoryWorkspaceBtn'))&&!by('connectionMemoryWorkspaceBtn').disabled);
 await click('connectionMemoryWorkspaceBtn');await wait(()=>by('experienceTimelineDialog').open);
 await click('memoryWorkspaceTab-connections');
 await wait(()=>by('memoryWorkspaceStatus').textContent.includes('已核对')&&by('memoryWorkspaceStatus').dataset.error!=='true');
 const status=await api('memory/experience');
 check(status.read_only===true&&status.model_calls===0&&status.scope_changed===false&&status.library.id===originalLibrary&&Array.isArray(status.connections),'workspace_connections');
 check(by('memoryWorkspaceList').querySelectorAll('.memory-workspace-card').length===status.connections.length,'workspace_connections');
 check(by('memoryWorkspacePanel').textContent.includes('不证明模型采用'),'workspace_connections');
 await click('memoryWorkspaceTab-commitments');
 await wait(()=>by('memoryWorkspaceStatus').textContent.includes('已显示')&&by('memoryWorkspaceStatus').dataset.error!=='true');
 const commitments=await api('memory/timeline?limit=20&view=open');
 check(commitments.read_only===true&&commitments.library_id===originalLibrary&&Array.isArray(commitments.entries),'workspace_commitments');
 check(by('memoryWorkspaceList').querySelectorAll('.memory-workspace-card').length===commitments.entries.length,'workspace_commitments');
 await click('memoryWorkspaceTab-experiences');await wait(()=>!by('refreshExperienceTimeline').disabled);await click('refreshExperienceTimeline');
 await wait(()=>!by('refreshExperienceTimeline').disabled&&by('experienceTimelineStatus').textContent&&!by('experienceTimelineStatus').textContent.includes('正在'));
 const experiences=await api('experiences?limit=30');
 check(experiences.read_only===true&&experiences.will_call_model===false&&experiences.agent_id===originalLibrary&&Array.isArray(experiences.entries),'workspace_experiences');
 check(by('experienceTimelineList').querySelectorAll('.experience-card').length===experiences.entries.length,'workspace_experiences');
 await click('closeExperienceTimeline');await wait(()=>!by('experienceTimelineDialog').open);
 await click('organizeBtn');await wait(()=>shown(by('organizerPanel')));
 const reviewSection=by('idleReviewSection'),reviewSummary=reviewSection?.querySelector('summary');
 check(shown(reviewSummary),'workspace_idle_review');reviewSummary.scrollIntoView({block:'nearest'});
 const summaryRect=reviewSummary.getBoundingClientRect();check(summaryRect.top<innerHeight&&summaryRect.bottom>0,'workspace_idle_review');
 if(!reviewSection.open)reviewSummary.click();
 await wait(()=>shown(by('previewIdleReview'))&&!by('previewIdleReview').disabled&&by('idleReviewCounts').textContent.includes('合格来源'));
 const review=await api('idle-review');
 check(review.schema==='love-house-idle-review/v1'&&review.library_id===originalLibrary&&review.profile.enabled===false&&!by('idleReviewEnabled').checked,'workspace_idle_review');
 await click('previewIdleReview');
 await wait(()=>reviewPreviews===1&&!by('previewIdleReview').disabled&&by('idleReviewStatus').textContent.includes('未调用模型'));
 check(by('idleReviewStatus').dataset.error!=='true'&&!by('idleReviewEnabled').checked,'workspace_idle_review');
 await click('closeOrganizer');await wait(()=>!shown(by('organizerPanel')));
 const after=canonical(await api('graph'));
 check(before===after&&paid===0&&writes===0&&reviewPreviews===1&&S.libraryId===originalLibrary,'workspace_read_only');
 return {navigation:true,no_overflow:true,add_and_import_menu:true,escape_focus_restored:true,
         add_cancel_read_only:true,display_menu:true,experience_scope:true,commitment_scope:true,
         connection_scope:true,model_adoption_not_claimed:true,idle_review_opt_in:true,
         idle_review_preview_read_only:true,read_only:true,model_calls:paid,
         connections_checked:status.connections.length,experience_entries:experiences.entries.length};
}finally{
 api=originalApi;if(by('experienceTimelineDialog')?.open)window.LoveHouseExperiences.close();
 if(by('addDialog')?.open)by('addDialog').close();window.LoveHouseWorkspace.closeMenus(false);
 for(const id of Object.keys(PANELS))setPanelOpen(id,false,{restore:false});
}
"""

CHECKS = ('navigation','no_overflow','add_and_import_menu','escape_focus_restored','add_cancel_read_only',
          'display_menu','experience_scope','commitment_scope','connection_scope','model_adoption_not_claimed',
          'idle_review_opt_in','idle_review_preview_read_only','read_only')
CODES = ('workspace_control','workspace_navigation','workspace_overflow','workspace_add','workspace_focus',
         'workspace_connections','workspace_commitments','workspace_experiences','workspace_idle_review',
         'workspace_read_only','workspace_paid','workspace_wait')
