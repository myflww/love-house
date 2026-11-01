"""Real WebView2 acceptance on disposable libraries; never calls a real model."""
import json
import threading

EXPECTED={'status':'passed','astrbot_setup':'passed','organizer_api_status':'passed',
          'library_isolation':'passed','nebula_left_rotation':'passed',
          'hover_pause_resume':'passed','real_model_calls':0}

CODES=('rotation_ready','rotation_idle','rotation_direction','rotation_hover','rotation_hover_stable',
       'rotation_resume','rotation_resumed','rotation_canonical','library_created','api_empty',
       'api_saved','api_model_visible','api_key_private','api_honest','setup_ready','setup_generated',
       'setup_routing','setup_identity','setup_private','api_other_library','setup_other_library','api_return_library','paid_request')

class Release0102Failure(AssertionError):
    def __init__(self,code):
        self.code=code if code in (*CODES,'release_0102_timeout','release_0102_script') else 'release_0102_response'
        super().__init__(self.code)

SCRIPT=r"""
const original=S.libraryId,by=id=>document.getElementById(id);
const check=(v,code)=>{if(!v)throw Error(code);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const wait=async(test,code)=>{for(let n=0;n<100;n++){if(test())return;await sleep(50);}throw Error(code);};
let paid=0;const originalApi=api;
api=async function(route,...args){if(['organizer/run','persona/organize','sharing/summary'].includes(route)){paid++;throw Error('paid_request');}return originalApi(route,...args);};
try{
 await selectMemoryLibrary(TEST_GRAPH_LIBRARY);
 if(S.graphMode!=='nebula'){by('viewBtn').click();await wait(()=>S.graphMode==='nebula'&&!artRenderer.isTransitioning(),'rotation_ready');}
 if(S.paused)by('pauseBtn').click();
 const cv=by('cv'),art=by('artCanvas');
 // A library reload seeds 110 existing host-physics steps. They legitimately
 // move UI x/y independently of the approved renderer; snapshot after settling.
 await wait(()=>S.sim===0&&S.graphMode==='nebula'&&!artRenderer.isTransitioning(),'rotation_ready');
 const canonicalNodes=nodes=>JSON.stringify(nodes.map(n=>[n.id,n.x,n.y,n.recalls]).sort((a,b)=>String(a[0]).localeCompare(String(b[0]))));
 const canonical=canonicalNodes(S.nodes),persistedCanonical=canonicalNodes((await api('graph')).nodes);
 cv.dispatchEvent(new PointerEvent('pointerleave',{pointerId:1,pointerType:'mouse'}));
 await wait(()=>art.dataset.autoRotate==='true','rotation_idle');
 const yaw=Number(art.dataset.autoRotateYaw);await sleep(500);
 check(Number(art.dataset.autoRotateYaw)>yaw+.005,'rotation_direction');
 cv.dispatchEvent(new PointerEvent('pointerenter',{pointerId:1,pointerType:'mouse'}));
 await wait(()=>art.dataset.autoRotateReason==='hover','rotation_hover');
 const stopped=Number(art.dataset.autoRotateYaw);await sleep(300);
 check(Number(art.dataset.autoRotateYaw)===stopped,'rotation_hover_stable');
 cv.dispatchEvent(new PointerEvent('pointerleave',{pointerId:1,pointerType:'mouse'}));
 await wait(()=>art.dataset.autoRotate==='true','rotation_resume');await sleep(300);
 check(Number(art.dataset.autoRotateYaw)>stopped,'rotation_resumed');
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
 check(paid===0,'paid_request');return {passed:true};
}finally{
 api=originalApi;if(by('agentSourcesDialog').open)by('closeAgentSources').click();
 if(S.libraryId!==original)await selectMemoryLibrary(original);
}
"""


def verify(window,graph_library):
    done=threading.Event();result={}
    def received(value):result['value']=value;done.set()
    script=SCRIPT.replace('TEST_GRAPH_LIBRARY',json.dumps(graph_library))
    # Failure text is restricted to fixed control codes, never API responses.
    window.evaluate_js('(async()=>{try{return {ok:true,value:await(async()=>{'+script+'})()};}'
        'catch(e){const allowed='+json.dumps(CODES)+';return {ok:false,code:allowed.includes(e.message)?e.message:"release_0102_script"};}})()',received)
    if not done.wait(80):raise Release0102Failure('release_0102_timeout')
    value=result.get('value')
    if not isinstance(value,dict) or value.get('ok') is not True:
        raise Release0102Failure(value.get('code','release_0102_response') if isinstance(value,dict) else 'release_0102_response')
    return EXPECTED.copy()
