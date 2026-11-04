"""Real WebView2 acceptance on disposable libraries; never calls a real model."""
import json
import threading
from workspace_smoke import CONTROL_HELPER

EXPECTED={'status':'passed','astrbot_setup':'passed','organizer_api_status':'passed',
          'library_isolation':'passed','nebula_left_rotation':'passed',
          'hover_continues_rotation':'passed','node_selection_pause_resume':'passed','motion_preference':'synthetic-toggle',
          'reduced_motion_respected':'passed','real_model_calls':0}

CODES=('rotation_ready','rotation_idle','rotation_direction','rotation_hover','rotation_hover_continues',
       'rotation_selected','rotation_selected_stable','rotation_selected_leave',
       'rotation_resume','rotation_resumed','rotation_reduced','rotation_reduced_stable','rotation_canonical','library_created','api_empty',
       'api_saved','api_model_visible','api_key_private','api_honest','setup_ready','setup_generated',
       'setup_routing','setup_identity','setup_private','api_other_library','setup_other_library','api_return_library','paid_request')

MOTION_REASONS=('idle','rotating','disabled','hidden','paused','reduced-motion',
                'flat','transition','interaction','hover','selected','unknown')


def safe_motion_diagnostic(value):
    """Return fixed booleans/enums only; never persist arbitrary JS values."""
    if not isinstance(value,dict):return {}
    result={key:value[key] for key in ('system_reduced_motion','initial_document_hidden','document_hidden')
            if type(value.get(key)) is bool}
    for key in ('initial_auto_rotate_reason','auto_rotate_reason'):
        if isinstance(value.get(key),str) and value[key] in MOTION_REASONS:result[key]=value[key]
    if value.get('test_motion_preference') in ('system','reduce','no-preference'):
        result['test_motion_preference']=value['test_motion_preference']
    return result


class Release0102Failure(AssertionError):
    def __init__(self,code,motion_diag=None):
        self.code=code if code in (*CODES,'release_0102_timeout','release_0102_script') else 'release_0102_response'
        self.motion_diag=safe_motion_diagnostic(motion_diag)
        super().__init__(self.code)

SCRIPT=CONTROL_HELPER+r"""
const original=S.libraryId,by=id=>document.getElementById(id);
const originalMatchMedia=globalThis.matchMedia,motionQuery='(prefers-reduced-motion: reduce)';
const motionReasons=['idle','rotating','disabled','hidden','paused','reduced-motion','flat','transition','interaction','hover','selected'];
const motionReason=()=>motionReasons.includes(by('artCanvas')?.dataset.autoRotateReason)?by('artCanvas').dataset.autoRotateReason:'unknown';
const initialMotion={system_reduced_motion:!!originalMatchMedia.call(globalThis,motionQuery).matches,
 initial_document_hidden:!!document.hidden,initial_auto_rotate_reason:motionReason()};
let testMotionPreference='system';
const motionDiagnostic=()=>({...initialMotion,document_hidden:!!document.hidden,auto_rotate_reason:motionReason(),test_motion_preference:testMotionPreference});
const check=(v,code)=>{if(!v){const error=Error(code);error.motion_diag=motionDiagnostic();throw error;}};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async(test,code)=>{for(let n=0;n<100;n++){if(test())return;await sleep(50);}check(false,code);};
let paid=0;const originalApi=api;
api=async function(route,...args){if(['organizer/run','persona/organize','sharing/summary'].includes(route)){paid++;throw Error('paid_request');}return originalApi(route,...args);};
try{
 await selectMemoryLibrary(TEST_GRAPH_LIBRARY);
 if(S.graphMode!=='nebula'){await nativeClick('viewBtn');await wait(()=>S.graphMode==='nebula'&&!artRenderer.isTransitioning(),'rotation_ready');}
 if(S.paused)await nativeClick('pauseBtn');
 const cv=by('cv'),art=by('artCanvas');
 // A library reload seeds 110 existing host-physics steps. They legitimately
 // move UI x/y independently of the approved renderer; snapshot after settling.
 await wait(()=>S.sim===0&&S.graphMode==='nebula'&&!artRenderer.isTransitioning(),'rotation_ready');
 const canonicalNodes=nodes=>JSON.stringify(nodes.map(n=>[n.id,n.x,n.y,n.recalls]).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))));
 const canonical=canonicalNodes(S.nodes),persistedCanonical=canonicalNodes((await api('graph')).nodes);
 // Hosted Windows may intentionally reduce animation. In this disposable
 // native test, control only this query; preserve all other media behavior and
 // restore the original function even on failure. The product remains unchanged.
 let reduced=false;
 try{
  testMotionPreference='no-preference';
  globalThis.matchMedia=function(query){
   const result=originalMatchMedia.apply(globalThis,arguments);
   return query===motionQuery?new Proxy(result,{get(target,key){const value=key==='matches'?reduced:Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;}}):result;
  };
  cv.dispatchEvent(new PointerEvent('pointerleave',{pointerId:1,pointerType:'mouse'}));schedule();
  await wait(()=>art.dataset.autoRotate==='true','rotation_idle');
  const yaw=Number(art.dataset.autoRotateYaw);await sleep(500);
  check(Number(art.dataset.autoRotateYaw)>yaw+.005,'rotation_direction');
  cv.dispatchEvent(new PointerEvent('pointerenter',{pointerId:1,pointerType:'mouse'}));
  await wait(()=>art.dataset.autoRotate==='true'&&art.dataset.autoRotateReason==='rotating','rotation_hover');
  const hovered=Number(art.dataset.autoRotateYaw);await sleep(300);
  check(Number(art.dataset.autoRotateYaw)>hovered,'rotation_hover_continues');
  const selectedRow=by('nodeList').querySelector('.node-row');
  check(!!selectedRow,'rotation_selected');if(!nativeVisible(selectedRow))await nativeClick('menuBtn');selectedRow.scrollIntoView({block:'nearest'});check(nativeVisible(selectedRow),'rotation_selected');selectedRow.click();
  await wait(()=>art.dataset.autoRotateReason==='selected','rotation_selected');
  const stopped=Number(art.dataset.autoRotateYaw);await sleep(300);
  check(Number(art.dataset.autoRotateYaw)===stopped,'rotation_selected_stable');
  cv.dispatchEvent(new PointerEvent('pointerleave',{pointerId:1,pointerType:'mouse'}));
  await sleep(100);check(art.dataset.autoRotateReason==='selected','rotation_selected_leave');
  select(null);schedule();
  await wait(()=>art.dataset.autoRotate==='true','rotation_resume');await sleep(300);
  check(Number(art.dataset.autoRotateYaw)>stopped,'rotation_resumed');
  reduced=true;testMotionPreference='reduce';schedule();
  await wait(()=>art.dataset.autoRotate==='false'&&art.dataset.autoRotateReason==='reduced-motion','rotation_reduced');
  const reducedYaw=Number(art.dataset.autoRotateYaw);await sleep(300);
  check(Number(art.dataset.autoRotateYaw)===reducedYaw,'rotation_reduced_stable');
 }finally{
  globalThis.matchMedia=originalMatchMedia;testMotionPreference='system';schedule();
 }
 check(canonical===canonicalNodes(S.nodes)&&persistedCanonical===canonicalNodes((await api('graph')).nodes),'rotation_canonical');
 const a=await api('libraries',{name:'Synthetic API and AstrBot acceptance'},{scope:false});
 const id=a.library?.id||a.library_id||a.selected_id;
 check(typeof id==='string','library_created');await refreshLibraries();await selectMemoryLibrary(id);
 await refreshOrganizer();check(by('organizerLibraryApiStatus').dataset.state==='not_configured','api_empty');
 setPanelOpen('organizerPanel',true,{focus:false});
 by('organizerMode').value='separate';by('organizerProviderBaseUrl').value='https://example.invalid/v1';
 by('organizerProviderModel').value='synthetic-native-model';by('organizerProviderKey').value='FAKE-native-session-only';
 by('organizerProviderSaveKey').checked=false;by('organizerEnabled').checked=false;by('organizerTriggerCount').value='20';
 await saveOrganizerSettings();await refreshOrganizer();
 check(by('organizerLibraryApiStatus').dataset.state==='session_only','api_saved');
 check(by('organizerApiStatusModel').textContent.includes('synthetic-native-model'),'api_model_visible');
 check(by('organizerProviderKey').value===''&&!document.body.textContent.includes('FAKE-native-session-only'),'api_key_private');
 check(by('organizerApiStatusVerification').textContent.includes('尚未确认'),'api_honest');
 setPanelOpen('organizerPanel',false);
 await window.LoveHouseSources.open();
 by('agentSourceAdapter').value='astrbot';by('agentSourceAdapter').dispatchEvent(new Event('change'));
 by('astrbotSetupLocation').value='same';by('astrbotSetupLocation').dispatchEvent(new Event('change'));
 by('astrbotSetupPlatform').value='qq';by('astrbotSetupPlatform').dispatchEvent(new Event('input'));
 by('astrbotSetupUmos').value='synthetic-native:FriendMessage:TEST';by('astrbotSetupUmos').dispatchEvent(new Event('input'));
 by('agentSourceConsent').checked=true;by('agentSourceConsent').dispatchEvent(new Event('change'));
 check(!by('createAgentSource').disabled,'setup_ready');await by('createAgentSource').onclick();
 check(!!by('astrbotSetupJson').value,'setup_generated');const config=JSON.parse(by('astrbotSetupJson').value),binding=config.bindings?.[0];
 check(config.enabled===true&&config.bindings.length===1&&binding.allowed_umos[0]==='synthetic-native:FriendMessage:TEST','setup_routing');
 check(binding.runtime_agent_id===by('agentSourceBoundIdentity').value&&binding.source_config_path===by('agentSourceConfigPath').value,'setup_identity');
 check(!Object.prototype.hasOwnProperty.call(config,'token')&&!Object.prototype.hasOwnProperty.call(binding,'token'),'setup_private');
 by('closeAgentSources').click();
 const b=await api('libraries',{name:'Synthetic unconfigured library'},{scope:false});const other=b.library?.id||b.library_id||b.selected_id;
 await refreshLibraries();await selectMemoryLibrary(other);await refreshOrganizer();
 check(by('organizerLibraryApiStatus').dataset.state==='not_configured','api_other_library');
 check(by('astrbotSetupJson').value==='','setup_other_library');
 await selectMemoryLibrary(id);await refreshOrganizer();
 check(by('organizerLibraryApiStatus').dataset.state==='session_only','api_return_library');
 check(paid===0,'paid_request');return {passed:true,motion_diag:motionDiagnostic()};
}catch(error){
 if(!error.motion_diag)error.motion_diag=motionDiagnostic();throw error;
}finally{
 api=originalApi;if(by('agentSourcesDialog').open)by('closeAgentSources').click();
 if(S.libraryId!==original)await selectMemoryLibrary(original);
}
"""


def verify(window,graph_library,*,environment=None):
    done=threading.Event();result={}
    def received(value):result['value']=value;done.set()
    script=SCRIPT.replace('TEST_GRAPH_LIBRARY',json.dumps(graph_library))
    # Failure text is restricted to fixed control codes, never API responses.
    window.evaluate_js('(async()=>{try{return {ok:true,value:await(async()=>{'+script+'})()};}'
        'catch(e){const allowed='+json.dumps(CODES)+';return {ok:false,code:allowed.includes(e.message)?e.message:"release_0102_script",motion_diag:e.motion_diag};}})()',received)
    if not done.wait(80):raise Release0102Failure('release_0102_timeout')
    value=result.get('value')
    if not isinstance(value,dict) or value.get('ok') is not True:
        raise Release0102Failure(value.get('code','release_0102_response') if isinstance(value,dict) else 'release_0102_response',
                                value.get('motion_diag') if isinstance(value,dict) else None)
    if isinstance(environment,dict):
        inner=value.get('value')
        environment.update(safe_motion_diagnostic(inner.get('motion_diag') if isinstance(inner,dict) else None))
    return EXPECTED.copy()
