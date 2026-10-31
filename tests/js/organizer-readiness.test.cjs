const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/index.html'),'utf8');
const fn=source.slice(source.indexOf('function updateMaintenanceButtons()'),source.indexOf('\nfunction organizerSummary('));
function check(provider,batches=[]){
 const elements=new Map();
 const $=id=>{if(!elements.has(id))elements.set(id,{disabled:false,title:'',checked:true});return elements.get(id);};
 const ctx={$ ,canWrite:()=>true,MEMORY:{busy:false},writeBusy:false,
  S:{mode:'serve',libraryChanging:false},ORGANIZER:{data:{provider,batches,settings:{enabled:true}}},
  MAINTENANCE:{restore:{ready:true},forget:{ready:true}},document:{querySelectorAll:()=>[]}};
 vm.runInNewContext(fn+';updateMaintenanceButtons()',ctx);
 return $('#runOrganizer');
}
test('a saved key without a usable model cannot enable an organizer call',()=>{
 const button=check({credential_ready:true,model_ready:false,configuration_error:'请配置模型名称'});
 assert.equal(button.disabled,true);assert.equal(button.title,'请配置模型名称');
});
test('usable saved settings enable a call but an active task still blocks duplicate clicks',()=>{
 assert.equal(check({credential_ready:true,model_ready:true}).disabled,false);
 assert.equal(check({credential_ready:true,model_ready:true},[{status:'running'}]).disabled,true);
 assert.equal(check({credential_ready:false,model_ready:false}).disabled,true);
});
