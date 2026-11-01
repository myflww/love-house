/* Evidence-backed persona growth. Reading this UI never starts a model call. */
(()=>{
'use strict';
if(typeof MEMORY==='undefined'||typeof ORGANIZER==='undefined'||!document.getElementById('personaPanel'))return;
const by=id=>document.getElementById(id),make=(tag,cls,text)=>el(tag,cls,text);
const state={owner:null,personaOwner:null,resultOwner:null,manualLibrary:null,manualHasText:false,serial:0,preview:null,reading:false,running:false,traitBusy:false,lastRun:null,importOwner:null};
const owner=()=>({id:S.libraryId,epoch:S.libraryEpoch});
const current=o=>!!o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const writable=()=>S.mode==='serve'&&!S.isDemo&&!S.libraryChanging&&canManageMemory()&&!MEMORY.busy&&!writeBusy;
const number=value=>Number.isFinite(value)&&value>=0?Math.floor(value):0;
const button=(id,text,hint,fn)=>{const b=make('button','btn',text);b.type='button';b.id=id;b.dataset.hintDescription=hint;b.onclick=fn;return b;};
const style=make('style');style.textContent=`
.persona-api-recommend{padding:12px;border:1px solid var(--line);background:var(--soft);margin:12px 0}.persona-api-recommend strong{display:block;font-size:13px}.persona-api-recommend p{font-size:12px;line-height:1.8;margin:6px 0}.persona-growth-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.persona-growth-status{font-size:12px;line-height:1.8;color:var(--muted);white-space:pre-wrap}.persona-trait-card{padding:12px;border:1px solid var(--line);margin:10px 0;background:var(--soft)}.persona-trait-card p{font-size:12px;line-height:1.8;overflow-wrap:anywhere;margin:7px 0;white-space:pre-wrap}.persona-trait-card summary{font-size:11px;cursor:pointer}.persona-trait-card .btn{font-size:11px}.persona-growth-dialog{width:min(580px,calc(100vw - 28px));max-height:calc(100vh - 36px);overflow:auto}.persona-growth-dialog p{font-size:13px;line-height:1.9}.persona-growth-dialog .dialog-title h2{font-size:19px}.persona-import-prompt{position:fixed;bottom:22px;left:22px;z-index:28;width:min(380px,calc(100vw - 44px));padding:14px;border:2px solid var(--line);background:var(--panel);color:var(--ink);box-shadow:5px 5px 0 var(--line)}.persona-import-prompt p{font-size:12px;line-height:1.8;margin:7px 0}.persona-import-prompt[hidden]{display:none}.persona-import-prompt .dialog-title{margin-bottom:4px}.persona-import-prompt .dialog-title strong{font-size:14px}
`;
document.head.append(style);

function apiRecommendation(id){
 const box=make('section','persona-api-recommend');box.id=id;const title=make('strong','','强烈建议：配置整理 API'),text=make('p','', '让整理 AI 归纳长期记忆，逐步形成她的表达、兴趣与相处风格。');
 const status=make('p','persona-growth-status');status.id=id+'Status';
 const action=button(id+'Configure','配置整理 API','打开当前记忆库的整理模型设置；不会在此调用模型。',openAPISettings);
 box.append(title,text,status,action);return {box,title,text,status,action};
}
const personaRecommend=apiRecommendation('personaApiRecommendation');
const organizerRecommend=apiRecommendation('organizerApiRecommendation');
by('personaRevision').after(personaRecommend.box);
by('organizerState').after(organizerRecommend.box);
const purpose=make('p','form-note','整理 API 用于 AI 归纳记忆和人格特征，强烈建议配置。未配置时，原文保存、检索、导出和手动人格仍可用。开启后按本库预算调用，费用由所选 API 服务计收；它不是聊天窗口的记忆连接密钥。');
purpose.id='organizerApiPurpose';by('organizerSettings').querySelector('summary').after(purpose);
by('organizerProviderKey').setAttribute('aria-describedby',purpose.id);
by('organizerProviderKey').placeholder='粘贴整理模型 API Key；留空保留已有密钥';
const enable=button('saveAndEnableOrganizer','保存并开启自动整理','明确保存当前模型设置并开启自动整理；保留本库预算，人格学习仍遵循人格开关。',()=>saveOrganizerSettings({enable:true}));enable.classList.add('primary');
by('saveOrganizerSettings').after(enable);by('saveOrganizerSettings').textContent='保存设置';

const growthActions=make('div','persona-growth-actions');
const quick=button('quickOrganizePersona','快速整理人格','从当前库有角色依据的历史记忆提炼初步人格；先预览范围，再确认一次有预算的模型请求。',()=>openQuick());quick.classList.add('primary');
const inspectModel=button('personaOrganizerSettings','整理 API 设置','查看当前库的整理模型、累计阈值与每日预算。',openAPISettings),progress=button('personaFormationProgress','整理进度','查看本库人格与记忆整理任务的实际进度和错误提示，不调用模型。',()=>{if(!MEMORY.busy&&!S.libraryChanging)setPanelOpen('organizerPanel',true);});growthActions.append(quick,inspectModel,progress);
const growthStatus=make('p','persona-growth-status');growthStatus.id='personaGrowthStatus';growthStatus.setAttribute('role','status');
const traits=make('section');traits.id='personaFormedTraits';traits.setAttribute('aria-label','从记忆形成的人格特征');
const outcome=make('p','persona-growth-status');outcome.id='personaFormationOutcome';outcome.hidden=true;outcome.setAttribute('role','status');
const organizerOutcome=make('p','persona-growth-status');organizerOutcome.id='organizerPersonaOutcome';organizerOutcome.hidden=true;organizerOutcome.setAttribute('role','status');by('organizerCounts').after(organizerOutcome);
by('personaText').placeholder='可选：粘贴你明确指定的人格。学习功能默认开启，具体人格从记忆逐步形成。';
by('personaEnabled').dataset.hintDescription='默认启用。手动关闭后保留资料，不再向 Agent 提供或自动补充人格。';
by('personaLearning').dataset.hintDescription='默认启用。整理 API 和自动整理就绪后，从本库记忆逐步形成有依据的特征；关闭后不再自动增加。';
const manualLabel=document.querySelector('label[for=personaText]');if(manualLabel)manualLabel.textContent='明确人格设定（优先保留）';
const manualDetails=make('details','persona-manual-settings');manualDetails.id='personaManualSettings';manualDetails.append(make('summary','','固定设定（可选，优先保留）'));
const saveRow=by('savePersonaImport')?.parentElement,manualNote=saveRow?.nextElementSibling;
if(manualLabel){manualLabel.before(growthActions,growthStatus,outcome,traits,manualDetails);manualDetails.append(manualLabel,by('personaText'));if(saveRow)manualDetails.append(saveRow);if(manualNote?.tagName==='P'&&manualNote.classList.contains('form-note'))manualDetails.append(manualNote);}
else by('personaLearned').before(growthActions,growthStatus,outcome,traits,manualDetails);
manualDetails.setAttribute('aria-label','可选的固定人格设定');
const dimensions={communication:'表达习惯',temperament:'性格气质',interaction:'相处方式',speaking_style:'表达风格',interaction_style:'相处风格',interests:'兴趣',values:'重视的事',self_identity:'角色身份',tone:'语气',interest:'兴趣',style:'表达风格',identity:'角色身份'};
const rejectionLabels={schema:'返回格式不符合要求',dimension:'特征类别不受支持',value:'特征值格式不符合要求',value_policy:'包含不应自动生效的内容',evidence_schema:'依据格式不符合要求',evidence_count:'独立依据不足',evidence_role:'说话角色不匹配',evidence_id:'依据不在本次范围',evidence_quote:'缺少可核验原话',evidence_duplicate:'依据重复',trait_collection:'特征列表格式不符合要求',learning_disabled:'人格学习已关闭',evidence_source:'来源不适合归纳人格',evidence_quote_mismatch:'引用原话不匹配',evidence_unavailable:'依据已不可用',evidence_truncated:'原话被截断',evidence_current_batch:'依据不属于本批资料',evidence_revalidation:'依据复核未通过'};
const skipLabels={persona_disabled:'人格已关闭',learning_disabled:'人格学习已关闭',persona_revision_changed:'人格版本已变化',persona_evidence_changed:'依据已变化',unchanged_or_suppressed:'已有同类特征或已被手动移除',evidence_revalidation:'依据复核未通过'};
function personaOutcomeText(result){
 if(!result||!['formed','partial','unchanged','empty','rejected','skipped','invalid'].includes(result.status))return '';
 const count=key=>Number.isInteger(result[key])&&result[key]>=0&&result[key]<=100000?result[key]:0;
 const applied=count('applied_count'),rejected=count('rejected_count');let text;
 if(result.status==='partial')text=`本批采纳 ${applied} 条人格特征，${rejected} 条未采纳；不是所有特征都已生效。`;
 else if(result.status==='formed')text=applied?`本批采纳 ${applied} 条有依据的人格特征，后续继续补充。`:'本批没有新增的人格特征。';
 else if(result.status==='unchanged')text='本批没有新增或变化的人格特征，已有资料保持。';
 else if(result.status==='empty')text='本批未得到可靠的新特征，没有补写人格。';
 else if(result.status==='skipped')text='本批未修改人格'+(skipLabels[result.reason]?'：'+skipLabels[result.reason]:'')+'。';
 else text=`本批人格特征未通过校验，未采纳 ${rejected} 条；未形成人格结果，原文保留。`;
 const reasons=Object.entries(result.reasons||{}).filter(([key,value])=>Object.hasOwn(rejectionLabels,key)&&Number.isInteger(value)&&value>0&&value<=100000).map(([key,value])=>rejectionLabels[key]+' '+value+' 条');
 return text+(reasons.length?' 原因：'+reasons.join('；')+'。':'');
}
function renderOutcome(data){
 const status=data?.status||{};if(status.library_id&&status.library_id!==S.libraryId)return;
 const jobs=Array.isArray(status.jobs)?status.jobs:Array.isArray(data?.batches)?data.batches:[];
 const requested=current(state.lastRun?.owner)&&state.lastRun?.job_id?jobs.find(j=>j.id===state.lastRun.job_id):null;
 const job=requested||jobs.find(j=>j?.persona_result),text=personaOutcomeText(job?.persona_result);
 state.resultOwner=owner();for(const box of [outcome,organizerOutcome]){box.hidden=!text;box.textContent=text?'最近一次整理反馈：'+text:'';}
}
function showPersona(data){
 const displayedOwner=owner();state.personaOwner=displayedOwner;
 const hasManual=!!String(data?.manual??data?.profile?.persona??'').trim()||MEMORY.personaDirty===true||!!by('personaText').value.trim();
 if(state.manualLibrary!==S.libraryId){manualDetails.open=hasManual;state.manualLibrary=S.libraryId;}else if(hasManual&&!state.manualHasText)manualDetails.open=true;
 state.manualHasText=hasManual;
 const parts=Array.isArray(data?.formed_traits)?data.formed_traits.filter(x=>x&&typeof x.id==='string'&&typeof x.value==='string'):[];
 traits.replaceChildren(make('h3','section-label','从记忆形成'));
 if(!parts.length)traits.append(make('p','form-note','还没有足够的人格依据。可导入带 AI 说话角色的历史记录，再快速整理；不会预设或编造人格。'));
 for(const trait of parts){
  const card=make('article','persona-trait-card');card.append(make('strong','',dimensions[trait.dimension]||'形成中的特征'),make('p','',trait.value),make('small','', '学习归纳 · 明确设定优先'));
  const evidence=make('details');evidence.append(make('summary','',`查看依据 · ${Array.isArray(trait.evidence)?trait.evidence.length:0} 条`));
  for(const ref of Array.isArray(trait.evidence)?trait.evidence.slice(0,6):[]){const entry=make('div','persona-evidence');entry.append(make('small','','AI 原话依据'),make('p','',typeof ref.quote==='string'?ref.quote:''));if(S.byId.has(String(ref.id))){const view=button('', '查看来源记忆','打开这条特征的本库原始记忆，不调用模型。',()=>{if(current(displayedOwner))select(String(ref.id),true);});entry.append(view);}evidence.append(entry);}
  const remove=button('removePersonaTrait-'+trait.id,'移除特征','停用这条自动归纳特征，保留原始记录；不会自动加回相同特征。',()=>{if(current(displayedOwner))removeTrait(trait.id,displayedOwner);});remove.dataset.personaTraitRemove='true';card.append(evidence,remove);traits.append(card);
 }
 const active=data?.enabled===true,learning=data?.learning_enabled===true;
 const modelReady=ORGANIZER.data?.provider?.model_ready===true&&ORGANIZER.data?.provider?.credential_ready===true;
 growthStatus.textContent=!active?'人格已关闭。现有资料保留，不向 Agent 提供或自动补充人格。':!learning?'人格已启用，学习已暂停。保留明确设定和已有特征，不自动增加新特征。':parts.length?`已形成 ${parts.length} 条有依据的特征；继续对话和整理后会逐步补充。`:modelReady?'人格与学习已开启。可从历史记忆快速整理；自动整理开启后继续逐步补充。空白人格是正常的起点。':'人格与学习已开启。可先导入历史记录，再配置整理 API 归纳特征。空白人格是正常的起点。';
 if(current(state.lastRun?.owner))growthStatus.textContent+=' '+state.lastRun.message;
 if(parts.length)traits.append(make('p','form-note','这些是从当前库原文归纳的特征，不是权限或行动指令；你可以移除，明确设定不会被自动覆盖。'));
 controls();
}
function updateRecommendation(){
 const data=ORGANIZER.data,p=data?.provider||{},ready=p.credential_ready===true&&p.model_ready===true,on=data?.settings?.enabled===true;
 for(const item of [personaRecommend,organizerRecommend]){
  item.title.textContent=ready?'整理 API 已配置':p.key_saved===true&&!p.credential_ready?'整理 API 凭据暂未就绪':p.credential_ready===true?'请完善整理 API 设置':'强烈建议：配置整理 API';
  item.status.textContent=ready?(on?'自动整理已开启；人格学习开启时会随有依据的记忆逐步形成。':'API 已就绪，自动整理尚未开启。可在设置中明确保存并开启。'):p.key_saved===true&&!p.credential_ready?'已有密钥保存记录，但当前不可用。请在整理设置查看诊断，无需反复覆盖密钥；原文仍可保存、回忆和导出。':p.credential_ready===true?'凭据可用，请核对模型名称和 API 地址。完整记忆仍可保存、回忆和导出。':'未配置时仍可保存、回忆、导出原文和手动设定人格；AI 归纳的人格特征需要整理 API。';
  item.action.textContent=ready?'查看整理 API':'配置整理 API';
 }
}
async function openAPISettings(){
 if(S.mode!=='serve'||S.libraryChanging||MEMORY.busy||writeBusy||state.running)return;
 const o=owner();setPanelOpen('organizerPanel',true);by('organizerSettings').open=true;
 await refreshOrganizer();if(!current(o))return;by('organizerSettings').open=true;
 if(!ORGANIZER.dirty&&!ORGANIZER.data?.settings?.connection_id&&!ORGANIZER.data?.settings?.provider_id){by('organizerMode').value='separate';organizerModeChanged();}
 (by('organizerMode').value==='separate'?by('organizerProviderKey'):by('organizerConnection')).focus();
}

const dialog=make('dialog','persona-growth-dialog');dialog.id='personaFormationDialog';dialog.setAttribute('aria-labelledby','personaFormationTitle');
const head=make('div','dialog-title'),heading=make('h2','','从记忆快速整理人格');heading.id='personaFormationTitle';
const close=button('closePersonaFormation','×','关闭预览，不调用模型。',closeQuick);close.className='icon-btn';close.setAttribute('aria-label','关闭人格整理');head.append(heading,close);
const destination=make('p','portability-identity'),coverage=make('p','persona-growth-status');coverage.id='personaFormationCoverage';
const note=make('p','','只使用可核验记忆节点中的 AI 原话，形成有依据的初步特征；仅归档或未标角色的资料不猜人格。明确设定优先保留，之后持续补充。');
const cost=make('p','form-note','点击开始后会使用当前库的整理 API，最多一次模型请求，并计入原调用与字符预算。原始记忆保留；本次抽取不代表已读完全部历史。');
const quickStatus=make('p','persona-growth-status');quickStatus.id='personaFormationStatus';quickStatus.setAttribute('role','status');
const actions=make('div','persona-growth-actions'),start=button('confirmPersonaFormation','开始整理人格','明确使用当前整理 API 和本库预算，只处理预览选中的当前库资料。',startQuick),configure=button('configurePersonaFormationAPI','配置整理 API','先设置当前库的整理模型；不会直接调用模型。',()=>{closeQuick();return openAPISettings();}),switches=button('openPersonaLearningSettings','查看人格开关','打开人格与学习开关；不会替你开启已关闭的选项。',()=>{closeQuick();openPersona();}),refresh=button('refreshPersonaFormation','重新预览','读取当前库的资料范围和模型准备状态，不调用模型。',previewQuick);
start.classList.add('primary');actions.append(start,configure,switches,refresh);dialog.append(head,destination,coverage,note,cost,quickStatus,actions);document.body.append(dialog);
function openPersona(){if(S.libraryChanging)return;setPanelOpen('aiPanel',true);memoryTab('persona');}
function closeQuick(){if(state.running)return;state.serial++;state.preview=null;state.reading=false;dialog.close();quickStatus.textContent='';controls();}
function quickAvailability(p){
 if(p?.persona_enabled===false)return {ready:false,kind:'switch',text:'人格已关闭。需要你手动启用后，才会形成或提供人格。'};
 if(p?.learning_enabled===false)return {ready:false,kind:'switch',text:'人格学习已关闭。请按自己的选择手动开启；现有人格与原文保留。'};
 if(p?.model_ready!==true||p?.credential_ready!==true)return {ready:false,kind:'config',text:'强烈建议先配置整理 API，才能让 AI 从历史记忆归纳人格。原文保存、回忆和导出仍可使用。'};
 if(p?.organizer_enabled!==true)return {ready:false,kind:'config',text:'整理 API 已就绪。请在设置中明确保存并开启自动整理，再开始人格整理。'};
 if(p?.status==='budget_limited')return {ready:false,kind:'wait',text:'当前整理预算不足。原预算不会被改大，恢复后可再试。'};
 if(number(p?.selected_records)<2)return {ready:false,kind:'wait',text:'可用的独立 AI 对话依据不足。请先导入带角色的历史记录，或继续积累对话；不会编造人格。'};
 return {ready:true,kind:'ready',text:'范围已核对。可使用原有预算整理一份初步人格。'};
}
async function openQuick(){
 if(!writable()||state.running||state.reading||dialog.open)return;state.owner=owner();state.serial++;state.preview=null;coverage.textContent='正在读取可用记忆…';quickStatus.textContent='';destination.textContent='当前存档：'+libraryName(state.owner.id);dialog.showModal();controls();await previewQuick();
}
async function previewQuick(){
 if(!current(state.owner)||state.running||state.reading||!dialog.open)return;
 const o=state.owner,v=++state.serial;state.preview=null;state.reading=true;coverage.textContent='正在核对本库资料与整理设置…';quickStatus.textContent='';controls();
 try{const p=await api('persona/organize-preview',{}, {libraryId:o.id});if(!current(o)||v!==state.serial||!dialog.open)return;if(p.library_id!==o.id||p.will_call_model!==false)throw new Error('无法确认只读预览归属，请重新读取。');state.preview=p;coverage.textContent=`本次选择 ${number(p.selected_records)} 条 · 可核验 AI 记录 ${number(p.eligible_records)} 条${p.coverage==='sampled'?' · 已按输入预算抽取，未覆盖全部历史':' · 覆盖可用节点，不等于全部历史'}${number(p.archive_only_records)?'；另有 '+number(p.archive_only_records)+' 条仅归档资料未纳入':''}`;quickStatus.textContent=quickAvailability(p).text;}
 catch(e){if(current(o)&&v===state.serial&&dialog.open){coverage.textContent='预览未完成';quickStatus.textContent='无法读取人格整理范围：'+e.message;}}
 finally{if(v===state.serial)state.reading=false;controls();}
}
async function startQuick(){
 if(!writable()||!current(state.owner)||!dialog.open||state.reading||state.running||!quickAvailability(state.preview).ready)return;
 const o=state.owner,v=state.serial;state.running=true;MEMORY.busy=true;writeBusy=true;updateWriteState();quickStatus.textContent='正在提交人格整理…';controls();
 try{const result=await api('persona/organize',{confirm:true,max_records:60},{libraryId:o.id});if(!current(o)||v!==state.serial||!dialog.open)return;if(result.library_id!==o.id)throw new Error('整理结果归属未通过核对');
  const accepted=['queued','running','completed','done','existing_job'].includes(result.status);
  if(accepted){state.lastRun={owner:o,job_id:typeof result.job_id==='string'?result.job_id:null,message:'已提交一次人格整理，可在“整理进度”查看结果。'};outcome.hidden=organizerOutcome.hidden=true;state.preview=null;dialog.close();state.serial++;openPersona();await refreshPersona();void refreshOrganizer();toast('人格整理已提交；按本库预算处理，完成后可在这里查看。');}
  else{state.preview=result;quickStatus.textContent=quickAvailability(result).text;}
 }catch(e){if(current(o)&&v===state.serial)quickStatus.textContent='人格整理未确认：'+e.message+'。原始记忆保留，请查看整理批次后再决定是否重试。';}
 finally{state.running=false;MEMORY.busy=false;writeBusy=false;updateWriteState();controls();}
}
async function removeTrait(id,o){
 if(!writable()||state.traitBusy||!current(o))return;state.traitBusy=true;MEMORY.busy=true;writeBusy=true;updateWriteState();controls();
 try{await api('persona/traits/'+encodeURIComponent(id)+'/remove',{expected_revision:MEMORY.persona?.revision},{libraryId:o.id});if(current(o)){await refreshPersona();toast('已移除这条学习特征，原始记忆保留。');}}
 catch(e){if(current(o))toast('特征移除未确认：'+e.message,true);}
 finally{state.traitBusy=false;MEMORY.busy=false;writeBusy=false;updateWriteState();controls();}
}

const importPrompt=make('aside','persona-import-prompt');importPrompt.id='personaImportPrompt';importPrompt.hidden=true;importPrompt.setAttribute('aria-label','导入后的人格整理');
const importHead=make('div','dialog-title'),importTitle=make('strong','','记忆已导入'),importClose=button('dismissPersonaImportPrompt','×','稍后再整理人格，不改变已导入记录。',()=>{importPrompt.hidden=true;state.importOwner=null;});importClose.className='icon-btn';importClose.setAttribute('aria-label','收起导入后提示');importHead.append(importTitle,importClose);
const importNote=make('p','','可让整理 AI 提炼她的表达、兴趣与相处风格。若已开启自动整理，将按原预算逐步处理；此提示不会额外调用模型。');
const importActions=make('div','persona-growth-actions'),importQuick=button('organizeImportedPersona','快速整理人格','先预览本库存档的有效资料，再确认是否调用整理模型。',()=>{if(current(state.importOwner)){importPrompt.hidden=true;openQuick();}}),importConfig=button('configureImportedPersonaAPI','配置整理 API','设置当前存档的整理模型与预算。',()=>{if(current(state.importOwner)){importPrompt.hidden=true;openAPISettings();}});importActions.append(importQuick,importConfig);importPrompt.append(importHead,importNote,importActions);document.body.append(importPrompt);
function afterImport(info={}){if(S.mode!=='serve'||S.isDemo||S.libraryChanging||info.library_id!==S.libraryId)return;state.importOwner=owner();importTitle.textContent='记忆已导入 · 下一步整理人格';importPrompt.hidden=false;controls();}

function controls(){
 const busy=MEMORY.busy||writeBusy||S.libraryChanging||state.running||state.traitBusy;
 quick.disabled=!writable()||state.reading;inspectModel.disabled=progress.disabled=busy||S.mode!=='serve';enable.disabled=busy||!canManageMemory()||S.isDemo;
 personaRecommend.action.disabled=organizerRecommend.action.disabled=busy||S.mode!=='serve'||S.isDemo;
 const availability=quickAvailability(state.preview);start.disabled=busy||state.reading||!current(state.owner)||!state.preview||!availability.ready;
 configure.hidden=!!state.preview&&availability.kind!=='config';switches.hidden=!!state.preview&&availability.kind!=='switch';refresh.disabled=busy||state.reading;close.disabled=state.running;
 for(const b of traits.querySelectorAll('[data-persona-trait-remove]'))b.disabled=busy||!canManageMemory()||S.isDemo;
 const personaLoaded=!!MEMORY.persona&&current(state.personaOwner);for(const id of ['personaEnabled','personaLearning'])by(id).disabled=busy||!canManageMemory()||S.isDemo||!personaLoaded;
 if(dialog.open&&state.owner&&!current(state.owner)&&!state.running)closeQuick();
 if(state.personaOwner&&!current(state.personaOwner)){traits.replaceChildren();growthStatus.textContent='';state.personaOwner=null;}
 if(state.resultOwner&&!current(state.resultOwner)){outcome.hidden=organizerOutcome.hidden=true;outcome.textContent=organizerOutcome.textContent='';state.resultOwner=null;}
 if(state.manualLibrary!==null&&state.manualLibrary!==S.libraryId){manualDetails.open=false;state.manualLibrary=null;state.manualHasText=false;}
 if(state.importOwner&&!current(state.importOwner)){importPrompt.hidden=true;state.importOwner=null;}
 importQuick.disabled=importConfig.disabled=busy||!current(state.importOwner);
}
dialog.addEventListener('cancel',event=>{event.preventDefault();closeQuick();});
document.addEventListener('keydown',event=>{if(dialog.open&&event.key==='Escape'){event.preventDefault();event.stopPropagation();closeQuick();}},true);
const oldPersona=renderPersona;renderPersona=function(data,options){oldPersona(data,options);const learnedTitle=by('personaLearned').querySelector('h3');if(learnedTitle)learnedTitle.textContent='多轮反馈形成的表达风格';showPersona(data);updateRecommendation();};
const oldOrganizer=renderOrganizer;renderOrganizer=function(data){oldOrganizer(data);renderOutcome(data);updateRecommendation();controls();};
const oldButtons=updateMemoryButtons;updateMemoryButtons=function(...args){oldButtons(...args);updateRecommendation();controls();};
const oldMaintenance=updateMaintenanceButtons;updateMaintenanceButtons=function(...args){oldMaintenance(...args);controls();};
window.LoveHousePersonaGrowth={openQuick,openAPISettings,afterImport};updateRecommendation();controls();
})();
