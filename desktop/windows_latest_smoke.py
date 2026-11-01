"""Isolated frozen/native checks for the shared 0.10.1 feature update.

The native script runs only in the owned Windows smoke profile. The backend
proof uses synthetic originals and a fake in-process model transport.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading

PERSONA_CHECKS=('defaultPersonaOn','defaultTogglesOn','manualEmpty','manualFolded','formedLayerPrimary',
    'apiRecommendation','noKeyPreviewOpen','noKeyCannotStart','noKeyCanConfigure','noKeyPreviewHonest',
    'previewReadOnly','newLibraryDefaultsOn','optoutSaved','originalLibraryStillOn','optoutSurvivesSwitch')
GRAPH_CHECKS=('graph_renderer','graph_empty','graph_sparse','graph_default_edges','graph_painter','graph_fibers',
    'graph_controls','graph_appearance_target','graph_theme_ui','graph_theme_reverse','graph_flat','graph_nebula',
    'graph_canonical','graph_manual','graph_labels_default','graph_labels_on','graph_labels_off','graph_original',
    'graph_detail','graph_minimap_on','graph_minimap_off','graph_pause_on','graph_pause_off','graph_canvas',
    'graph_http_edges','graph_recall')
GRAPH_WAITS=('empty','sparse-1','sparse-2','sparse-3','automatic-viewport','flat','nebula','restore-auto')
SAFE_CODES=frozenset((*GRAPH_CHECKS,*(('graph_wait_'+stage) for stage in GRAPH_WAITS),
    *(('persona_'+check) for check in PERSONA_CHECKS),'persona_paid_requests','persona_library',
    'persona_evaluation','graph_evaluation','persona_response','graph_response',
    'persona_script_error','graph_script_error','graph_result'))


class NativeFeatureFailure(AssertionError):
    """Only a fixed smoke-control code may appear in the public report."""
    def __init__(self,code):
        self.code=code if isinstance(code,str) and code in SAFE_CODES else 'graph_response'
        super().__init__(self.code)

PERSONA_SCRIPT = r"""
const getPersonaControl=id=>document.getElementById(id);
const originalPersonaAPI=api;
const originalPersonaLibrary=S.libraryId;
let paidPersonaRequests=0;
let optoutLibrary=null;
const personaMetrics={};
try {
  api=async function(route,...args){
    if(['persona/organize','organizer/run','sharing/summary'].includes(route)){
      paidPersonaRequests++;
      throw new Error('A read-only native persona acceptance attempted a model action');
    }
    const result=await originalPersonaAPI(route,...args);
    if(route==='persona/organize-preview')personaMetrics.previewReadOnly=result.library_id===originalPersonaLibrary&&result.will_call_model===false&&result.read_only===true&&result.model_ready===false&&result.credential_ready===false;
    return result;
  };

  setPanelOpen('aiPanel',true,{focus:false});
  memoryTab('persona');
  await refreshPersona({force:true});
  const defaultPersona=await api('persona');
  personaMetrics.defaultPersonaOn=defaultPersona.enabled===true&&defaultPersona.learning_enabled===true;
  personaMetrics.defaultTogglesOn=getPersonaControl('personaEnabled').checked===true&&getPersonaControl('personaLearning').checked===true;
  personaMetrics.manualEmpty=getPersonaControl('personaText').value==='';
  personaMetrics.manualFolded=getPersonaControl('personaManualSettings').open===false;
  personaMetrics.formedLayerPrimary=!!(getPersonaControl('personaFormedTraits').compareDocumentPosition(getPersonaControl('personaManualSettings'))&Node.DOCUMENT_POSITION_FOLLOWING);
  personaMetrics.apiRecommendation=getPersonaControl('personaApiRecommendation').textContent.includes('强烈建议')&&getPersonaControl('organizerApiRecommendation').textContent.includes('强烈建议');

  await window.LoveHousePersonaGrowth.openQuick();
  personaMetrics.noKeyPreviewOpen=getPersonaControl('personaFormationDialog').open===true;
  personaMetrics.noKeyCannotStart=getPersonaControl('confirmPersonaFormation').disabled===true;
  personaMetrics.noKeyCanConfigure=getPersonaControl('configurePersonaFormationAPI').hidden===false;
  personaMetrics.noKeyPreviewHonest=!getPersonaControl('personaFormationStatus').textContent.includes('已完成人格');
  getPersonaControl('closePersonaFormation').click();

  const created=await api('libraries',{name:'原生人格开关隔离自检'},{scope:false});
  optoutLibrary=created.library?.id||created.library_id||created.selected_id;
  if(typeof optoutLibrary!=='string'||!optoutLibrary)throw new Error('Missing temporary opt-out library identity');
  await refreshLibraries();
  await selectMemoryLibrary(optoutLibrary,{alreadySelected:true});
  setPanelOpen('aiPanel',true,{focus:false});memoryTab('persona');await refreshPersona({force:true});
  personaMetrics.newLibraryDefaultsOn=getPersonaControl('personaEnabled').checked===true&&getPersonaControl('personaLearning').checked===true;
  getPersonaControl('personaEnabled').checked=false;await getPersonaControl('personaEnabled').onchange();
  getPersonaControl('personaLearning').checked=false;await getPersonaControl('personaLearning').onchange();
  const explicitlyOff=await api('persona');
  personaMetrics.optoutSaved=explicitlyOff.enabled===false&&explicitlyOff.learning_enabled===false;

  await selectMemoryLibrary(originalPersonaLibrary);
  setPanelOpen('aiPanel',true,{focus:false});memoryTab('persona');await refreshPersona({force:true});
  personaMetrics.originalLibraryStillOn=getPersonaControl('personaEnabled').checked===true&&getPersonaControl('personaLearning').checked===true;
  await selectMemoryLibrary(optoutLibrary);
  setPanelOpen('aiPanel',true,{focus:false});memoryTab('persona');await refreshPersona({force:true});
  personaMetrics.optoutSurvivesSwitch=getPersonaControl('personaEnabled').checked===false&&getPersonaControl('personaLearning').checked===false;
  personaMetrics.paidRequests=paidPersonaRequests;
  personaMetrics.optoutLibraryId=optoutLibrary;
  return personaMetrics;
} finally {
  api=originalPersonaAPI;
  if(getPersonaControl('personaFormationDialog').open)getPersonaControl('closePersonaFormation').click();
  if(S.libraryId!==originalPersonaLibrary){await selectMemoryLibrary(originalPersonaLibrary);}
  memoryTab('connect');
  setPanelOpen('aiPanel',false,{restore:false});
}
"""

GRAPH_SCRIPT = r"""
const check=(ok,message)=>{if(!ok)throw Error(message);};
let stage='empty';
const graphDeadline=performance.now()+75000;
const wait=async(predicate)=>{const end=Math.min(performance.now()+30000,graphDeadline);while(!predicate()){if(performance.now()>end)throw Error('graph_wait_'+stage);await new Promise(r=>setTimeout(r,30));}};
const paint=async()=>{schedule();await new Promise(r=>setTimeout(r,80));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));};
const original=S.libraryId;
const texts=['今天我读到火山喷发形成熔岩。','今天我研究邮票收藏使用镊子。','今天我学习钢琴调律校正音准。'];
try{
  await selectMemoryLibrary(TEST_LIBRARY);
  await wait(()=>!S.libraryChanging&&S.nodes.length===0);
  await paint();
  const c=document.getElementById('cv'),artist=document.getElementById('artCanvas');
  check(S.art&&!!artRenderer,'graph_renderer');
  check(Number(c.dataset.viewCount)===0,'graph_empty');
  const counts=[0];
  for(const text of texts){
    stage='sparse-'+counts.length;
    await api('add',{label:text,text,kind:'fact'});
    // A library switch intentionally resets its visible-kind filters. A plain
    // preserving refresh of a previously empty graph keeps the empty filter.
    await selectMemoryLibrary(original);await selectMemoryLibrary(TEST_LIBRARY);await paint();
    await wait(()=>S.nodes.length===counts.length&&Number(c.dataset.viewCount)===counts.length);
    counts.push(S.nodes.length);
    check(S.edges.length===0,'graph_default_edges');
  }
  stage='automatic-viewport';
  await wait(()=>S.sim===0&&S.view.mode==='auto'&&!!S.view.target&&Math.abs(Math.log(S.cam.k/S.view.target.k))<.01);
  await paint();
  check(counts.join(',')==='0,1,2,3','graph_sparse');
  check(artist.dataset.painter==='approved-canvas'&&Number(artist.dataset.particleCount)>0,'graph_painter');
  check(Number(artist.dataset.fiberEdges)===S.edges.length,'graph_fibers');
  check(!document.querySelector('#approvedAtlasModes,#nebula-mode,#flat-mode'),'graph_controls');
  const canonical=JSON.stringify(S.nodes.map(n=>[n.id,n.x,n.y,n.recalls]));
  const uiAppearance=()=>JSON.stringify({tokens:['--bg','--paper','--panel','--soft','--line','--ink','--muted','--accent','--accent-soft','--gold','--danger','--shadow'].map(k=>getComputedStyle(document.documentElement).getPropertyValue(k)),elements:['header','#settings','#addBtn','#themeBtn','#tooltip','#aiPanel','#q','#personaText','#personaEnabled','#newLibraryDialog'].map(selector=>{const e=document.querySelector(selector);check(!!e,'graph_appearance_target');return ['', '::before','::after',...(selector==='#newLibraryDialog'?['::backdrop']:[])].map(pseudo=>{const s=getComputedStyle(e,pseudo||null);return [s.backgroundColor,s.color,s.borderColor,s.backgroundImage,s.filter,s.fontFamily,s.boxShadow,s.accentColor,s.colorScheme];});})});
  const appearance=uiAppearance(),theme=document.documentElement.dataset.theme;
  document.getElementById('themeBtn').click();await paint();
  check(document.documentElement.dataset.theme!==theme&&uiAppearance()===appearance,'graph_theme_ui');
  document.getElementById('themeBtn').click();await paint();
  check(document.documentElement.dataset.theme===theme&&uiAppearance()===appearance,'graph_theme_reverse');
  document.getElementById('viewBtn').click();
  stage='flat';
  await wait(()=>S.graphMode==='flat'&&!artRenderer.isTransitioning());await paint();
  check(c.dataset.graphMode==='flat'&&Number(c.dataset.viewCount)===3,'graph_flat');
  document.getElementById('viewBtn').click();
  stage='nebula';
  await wait(()=>S.graphMode==='nebula'&&!artRenderer.isTransitioning()&&Math.abs(Math.log(S.cam.k/S.view.target.k))<.01);await paint();
  check(c.dataset.graphMode==='nebula'&&Number(c.dataset.viewCount)===3,'graph_nebula');
  check(canonical===JSON.stringify(S.nodes.map(n=>[n.id,n.x,n.y,n.recalls])),'graph_canonical');
  document.getElementById('zoomIn').click();await paint();
  const manual={x:S.cam.x,y:S.cam.y,k:S.cam.k};
  await reload();await paint();
  check(c.dataset.viewMode==='manual'&&Math.abs(S.cam.k-manual.k)<.000001&&Math.abs(S.cam.x-manual.x)<.000001&&Math.abs(S.cam.y-manual.y)<.000001,'graph_manual');
  check(c.dataset.labelMode==='focus','graph_labels_default');
  document.getElementById('labelToggle').click();await wait(()=>c.dataset.labelMode==='auto');await paint();
  check(c.dataset.labelMode==='auto','graph_labels_on');
  document.getElementById('labelToggle').click();await wait(()=>c.dataset.labelMode==='focus');await paint();
  check(c.dataset.labelMode==='focus','graph_labels_off');
  document.getElementById('fitBtn').click();await paint();
  stage='restore-auto';
  await wait(()=>S.view.mode==='auto'&&!!S.view.target);
  const first=S.nodes.find(n=>n.text===texts[0]);
  check(!!first,'graph_original');
  select(first.id);await paint();
  check(S.selected===first.id&&!document.getElementById('inspector').hidden&&document.getElementById('detail').textContent.includes('火山'),'graph_detail');
  document.getElementById('minimapBtn').click();await paint();
  check(!document.getElementById('miniPanel').hidden&&document.getElementById('minimap').width>0,'graph_minimap_on');
  document.getElementById('minimapBtn').click();await paint();
  check(document.getElementById('miniPanel').hidden,'graph_minimap_off');
  const paused=S.paused;
  document.getElementById('pauseBtn').click();await paint();
  check(S.paused!==paused&&document.getElementById('pauseBtn').getAttribute('aria-pressed')===String(S.paused),'graph_pause_on');
  document.getElementById('pauseBtn').click();await paint();check(S.paused===paused,'graph_pause_off');
  check(Number.isFinite(S.dpr)&&S.dpr>0&&c.width>0&&c.height>0,'graph_canvas');
  const graphBefore=await api('graph');
  check(graphBefore.nodes.length===3&&graphBefore.edges.length===0,'graph_http_edges');
  const recall=await api('recall',{query:texts.join(' '),k:3,learn:true});
  const graphAfter=await api('graph');
  check(recall.hits.length===3&&recall.reinforced.pairs===0&&graphAfter.edges.length===0,'graph_recall');
  return {counts,painter:artist.dataset.painter,edges:0,topics:3,devicePixelRatio:devicePixelRatio,canvasDpr:S.dpr};
}finally{
  if(S.libraryId!==original)await selectMemoryLibrary(original);
}
"""


def evaluate(window, script, *, name='graph', timeout=90):
    ready=threading.Event();box={}
    def received(value):
        box['value']=value;ready.set()
    # JS exception text can contain API responses. Keep only exact, reviewed
    # control names; no arbitrary error text crosses into a smoke report.
    allowed=json.dumps(sorted(SAFE_CODES))
    fallback=json.dumps(name+'_script_error')
    wrapped="(async()=>{try{return {ok:true,value:await(async()=>{"+script+"})()};}catch(e){const allowed="+allowed+";return {ok:false,code:allowed.includes(e.message)?e.message:"+fallback+"};}})()"
    try:window.evaluate_js(wrapped,received)
    except Exception:raise NativeFeatureFailure(name+'_evaluation') from None
    if not ready.wait(timeout):raise NativeFeatureFailure(name+'_evaluation')
    result=box['value']
    if not isinstance(result,dict):raise NativeFeatureFailure(name+'_response')
    if result.get('ok') is not True:
        code=result.get('code')
        raise NativeFeatureFailure(code if isinstance(code,str) and code in SAFE_CODES else name+'_response')
    return result['value']


def verify_latest_ui(window,runtime):
    persona=evaluate(window,PERSONA_SCRIPT,name='persona',timeout=45)
    for name in PERSONA_CHECKS:
        if persona.get(name) is not True:raise NativeFeatureFailure('persona_'+name)
    if persona['paidRequests']!=0:raise NativeFeatureFailure('persona_paid_requests')
    library=persona['optoutLibraryId']
    if not isinstance(library,str) or library=='default':raise NativeFeatureFailure('persona_library')
    graph=evaluate(window,GRAPH_SCRIPT.replace('TEST_LIBRARY',json.dumps(library)))
    if not (graph['counts']==[0,1,2,3] and graph['painter']=='approved-canvas' and graph['topics']==3):raise NativeFeatureFailure('graph_result')
    snapshot=runtime.host.snapshot(library)
    result={'status':'passed','persona_controls':'passed','read_only_model_calls':0,'independent_topics':3,
        'default_edges':0,'joint_recall_edges':0,'approved_painter':'approved-canvas','graph_modes':['nebula','flat'],
        'graph_only_theme':'passed','canonical_coordinates_and_recalls':'passed','viewport_and_labels':'passed',
        'details_minimap_pause':'passed','native_canvas_dpr':graph['canvasDpr']}
    return result,{'library':library,'snapshot':snapshot,'selected':runtime.host.manager.selected_id}


def verify_latest_restart(runtime,expected):
    from nkb.companion.persona import persona_state
    from nkb.core.brain import Brain
    assert runtime.host.manager.selected_id==expected['selected']
    graph=runtime.host.snapshot(expected['library'])
    assert graph==expected['snapshot'],'Synthetic native graph changed across Controller restart'
    persona=persona_state(Brain(graph))
    assert persona['enabled'] is False and persona['learning_enabled'] is False
    assert len(graph['nodes'])==3 and not graph['edges']
    return 'passed'


def latest_backend_smoke(directory):
    from nkb import Brain
    from nkb.companion import record_turn
    from nkb.companion.persona import persona_state,import_persona
    from nkb.organizer import Organizer,apply_plan,save_profile
    brain=Brain.new();state=persona_state(brain)
    assert state['enabled'] and state['learning_enabled'] and state['manual']=='' and state['formed_traits']==[]
    save_profile(brain,enabled=True,base_url='https://synthetic-persona.invalid/v1',model='FAKE-persona-model')
    originals=['我喜欢星空，也喜欢分享天文知识。','我喜欢星空，常常观察星星。']
    ids=[record_turn(brain,'我们聊聊星空。',text,'synthetic-persona-window',str(index))
         for index,text in enumerate(originals)]
    import_persona(brain,'合成固定设定：认真、安静。',{'origin':'synthetic_package_proof'})
    requests=[]
    def send(request,timeout):
        payload=json.loads(json.loads(request.data)['messages'][1]['content']);requests.append(payload)
        records=payload['raw']+payload.get('persona_context',[])
        refs=[{'id':r['id'],'role':'assistant','quote':r['roles']['assistant']}
              for r in records if r.get('persona_evidence_available')]
        assert len(refs)==2 and {r['quote'] for r in refs}==set(originals)
        output={'version':1,'operations':[],'persona_traits':[{'dimension':'interests','value':'喜欢星空','evidence':refs}]}
        return {'choices':[{'message':{'content':json.dumps(output,ensure_ascii=False)},'finish_reason':'stop'}]}
    with tempfile.TemporaryDirectory(prefix='latest-persona-',dir=Path(directory)) as temporary:
        organizer=Organizer(temporary,snapshot=lambda _:deepcopy(brain.to_dict()),
            apply=lambda library,plan:apply_plan(brain,plan,library),
            credential=lambda *_:'FAKE-persona-proof-key',transport=send)
        try:
            organizer.enqueue('synthetic',ids)
            with organizer.db() as db:
                before=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY raw_id')]
            nodes=deepcopy(brain.nodes)
            selection=organizer.persona_selection('synthetic')
            assert selection['selected_records']==2
            job=organizer.enqueue_persona('synthetic',selection['selected_ids'])
            assert requests==[],'Read-only persona preview called a model'
            quick=organizer.run_once('synthetic',job_id=job['job_id'])
            assert quick['status']=='done' and len(requests)==1 and requests[0]['purpose']=='persona',quick
            assert brain.nodes==nodes
            with organizer.db() as db:
                after=[tuple(row) for row in db.execute('SELECT * FROM items ORDER BY raw_id')]
            assert before==after
            assert len(persona_state(brain)['formed_traits'])==1
            ordinary=organizer.run_once('synthetic')
            assert ordinary['status']=='done' and len(requests)==2,ordinary
            assert requests[1]['memory_policy']['persona_learning'] is True
            assert persona_state(brain)['manual']=='合成固定设定：认真、安静。'
            assert len(persona_state(brain)['formed_traits'])==1
            assert organizer.status('synthetic')['usage_24h']['count']==2
        finally:
            organizer.stop()
    return {'status':'passed','persona_defaults':'passed','quick_purpose_and_ordinary_queue':'passed',
        'ordinary_batch_persona':'passed','assistant_evidence_count':2,'manual_core_preserved':'passed',
        'preview_model_calls':0,'fake_model_calls':2,'budget_count':2,'transport':'in-process-fake',
        'real_model_calls':0,'real_credentials_accessed':False,'cleanup':'removed'}
