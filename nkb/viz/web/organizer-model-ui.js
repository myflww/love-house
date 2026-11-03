/* Per-library organizer model discovery and provider-declared limits. */
(()=>{
'use strict';
if(typeof ORGANIZER==='undefined'||!document.getElementById('organizerSettings'))return;
const by=id=>document.getElementById(id),make=(tag,cls,text)=>el(tag,cls,text);
const state={version:0,models:[],selectedModel:'',owner:null,busy:false,credentialVersion:0};
const settings=by('organizerSettings'),model=by('organizerProviderModel');
const list=make('datalist');list.id='organizerAvailableModels';model.setAttribute('list',list.id);model.after(list);
const refresh=make('button','btn','读取可用模型');refresh.type='button';refresh.id='organizerReadModels';
refresh.dataset.hintDescription='从当前API服务读取模型与支持的推理强度，不发送记忆，不调用聊天模型。';
const note=make('p','form-note');note.id='organizerModelCapabilities';note.setAttribute('aria-live','polite');
const effortLabel=make('label','','推理强度');effortLabel.htmlFor='organizerReasoningEffort';
const effort=make('select');effort.id='organizerReasoningEffort';
const advanced=make('details'),summary=make('summary','','上下文与输出 · 默认使用模型最高');advanced.append(summary);
function numberField(id,label){const l=make('label','',label),input=make('input');input.id=id;input.type='number';input.min='1';input.step='1';input.placeholder='留空：模型支持的最高';l.htmlFor=id;advanced.append(l,input);return input;}
const context=numberField('organizerContextWindow','上下文窗口（token）'),output=numberField('organizerMaxOutputTokens','单次输出（token）');context.min='512';
advanced.append(make('p','form-note','默认按模型公布的最高能力运行；服务未提供上限时由服务决定。自定较小上下文会为输出保留空间，并按UTF-8字节保守估算输入。只发送本批需要的材料，不会为了填满窗口额外发送全部记忆。'));
const cadence=by('organizerCadence'),anchor=cadence.previousElementSibling;
for(const control of [refresh,note,effortLabel,effort,advanced])settings.insertBefore(control,anchor);
function scope(){return JSON.stringify([S.libraryId,S.libraryEpoch,by('organizerMode').value,by('organizerConnection').value,by('organizerProviderBaseUrl').value,state.credentialVersion]);}
function owner(){return JSON.stringify([scope(),model.value]);}
function option(value,label){const o=make('option','',label);o.value=value;return o;}
function currentMetadata(){const selected=by('organizerMode').value==='connection'?state.selectedModel:model.value.trim();return state.models.find(m=>m.id===selected)||null;}
function renderEffort(meta,selected=effort.value||'auto'){
 const levels=Array.isArray(meta?.effort?.supported_levels)?meta.effort.supported_levels:[];
 const labels={none:'关闭思考',low:'低',medium:'中',high:'高',xhigh:'更高',max:'最高'};
 effort.replaceChildren(option('auto','自动 · 服务默认'));
 effort.append(option('none',levels.length?'关闭思考':'关闭思考 · 需服务支持'));
 if(levels.length){for(const level of levels)effort.append(option(level,labels[level]||level));}
 else for(const level of ['low','medium','high','xhigh','max'])effort.append(option(level,`${labels[level]} · 需服务支持`));
 // An explicitly saved custom-provider choice remains editable even before
 // discovery, without claiming that every compatible model supports it.
 if(selected!=='auto'&&!Array.from(effort.options).some(o=>o.value===selected)&&!levels.length)effort.append(option(selected,`${labels[selected]||selected} · 需服务支持`));
 effort.value=Array.from(effort.options).some(o=>o.value===selected)?selected:'auto';
}
function describe(meta){
 const contextText=meta?.context_window?`${Number(meta.context_window).toLocaleString()} token`:'由服务决定';
 const outputText=meta?.max_output_tokens?`${Number(meta.max_output_tokens).toLocaleString()} token`:'由服务决定';
 note.textContent=`模型上下文：${contextText}；最高输出：${outputText}。自动强度沿用服务默认。${meta?.effort?.supported_levels?.length?'':'服务未公布推理强度；通用选项需当前模型和服务支持。'}`;
}
function invalidate(){state.version++;state.models=[];state.selectedModel='';state.busy=false;list.replaceChildren();renderEffort(null);describe(null);refresh.disabled=false;}
for(const id of ['organizerMode','organizerConnection','organizerProviderBaseUrl'])for(const type of ['input','change'])by(id).addEventListener(type,()=>{invalidate();ORGANIZER.dirty=true;});
by('organizerProviderKey').addEventListener('input',()=>{state.credentialVersion++;invalidate();ORGANIZER.dirty=true;});
model.addEventListener('input',()=>{renderEffort(currentMetadata(),'auto');describe(currentMetadata());ORGANIZER.dirty=true;});
for(const control of [effort,context,output])control.addEventListener('input',()=>{ORGANIZER.dirty=true;});
function positiveOrAuto(input){const value=input.value.trim();if(!value)return 0;const n=Number(value);if(!Number.isSafeInteger(n)||n<1)throw new Error('上下文和输出请留空使用模型最高，或填写正整数 token。');return n;}
function settingsPayload(){const windowTokens=positiveOrAuto(context);if(windowTokens&&windowTokens<512)throw new Error('自定上下文至少512 token，留空使用模型最高。');return {reasoning_effort:effort.value||'auto',context_window:windowTokens,max_output_tokens:positiveOrAuto(output),max_input_chars:0};}
refresh.onclick=async()=>{
 if(state.busy||S.mode!=='serve'||S.libraryChanging)return;
 const stamp=owner(),version=++state.version;
 const mode=by('organizerMode').value,body={provider_mode:mode,model:model.value.trim()};
 if(mode==='connection')body.connection_id=by('organizerConnection').value;
 else{body.base_url=by('organizerProviderBaseUrl').value.trim();const key=by('organizerProviderKey').value.trim();if(key)body.api_key=key;}
 state.busy=true;refresh.disabled=true;note.textContent='正在读取当前服务的模型能力…';
 try{
  const result=await api('organizer/models',body,{libraryId:S.libraryId});
  if(version!==state.version||stamp!==owner())return;
  if(result.library_id!==undefined&&result.library_id!==S.libraryId)throw new Error('返回的模型列表不属于当前库');
  state.owner=scope();state.models=Array.isArray(result.models)?result.models.filter(item=>item&&typeof item.id==='string'):[];list.replaceChildren();
  for(const item of state.models){if(typeof item.id!=='string')continue;const itemOption=option(item.id,item.name||item.id);list.append(itemOption);}
  state.selectedModel=mode==='connection'?result.selected_model:model.value.trim();
  const metadata=currentMetadata();
  renderEffort(metadata);describe(metadata);
  if(!state.models.length)note.textContent+='服务未返回模型列表，可手动填写模型名称。';
 }catch(error){if(version===state.version&&stamp===owner()&&!error.staleLibrary){const message=String(error.message||'读取失败'),safe=body.api_key?message.split(body.api_key).join('[密钥已隐藏]'):message;note.textContent='模型列表未读取：'+safe+'；仍可手动填写模型名称。';}}
 finally{if(version===state.version){state.busy=false;refresh.disabled=false;}}
};
const originalRender=renderOrganizer;
renderOrganizer=function(data){
 originalRender(data);
 if(state.owner!==scope()){invalidate();state.owner=scope();}
 if(!ORGANIZER.dirty){const profile=data.settings||{};context.value=profile.context_window?String(profile.context_window):'';output.value=profile.max_output_tokens?String(profile.max_output_tokens):'';const metadata=data.model_capabilities||currentMetadata();renderEffort(metadata,profile.reasoning_effort||'auto');describe(metadata);}
};
if(typeof resetLibraryView==='function'){const originalReset=resetLibraryView;resetLibraryView=function(...args){originalReset(...args);invalidate();state.owner=null;context.value=output.value='';renderEffort(null,'auto');};}
window.LoveHouseOrganizerModels={settingsPayload};renderEffort(null);describe(null);
})();
