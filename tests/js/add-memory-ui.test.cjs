/* Execute the real Add flow; default kind does not alter explicit type choices. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/index.html'),'utf8');
const start=html.indexOf('function openAdd(){'),end=html.indexOf('\nfunction ',start+1),code=html.slice(start,end);
function environment(writable=true){
 const nodes={},calls=[],messages=[];for(const id of ['addForm','newKind','memoryDialogTitle','memoryDialogIntro','saveAdd','newEventAt','addDialog','newLabel','newText','newSession','newTags','newImpact','newImportant'])nodes[id]={value:'',checked:false,textContent:'',focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;}};
 nodes.addForm.reset=()=>{for(const n of Object.values(nodes)){n.value='';n.checked=false;}nodes.newKind.value='concept';};nodes.addForm.addEventListener=(_type,fn)=>nodes.addForm.submit=fn;
 const c={S:{libraryId:'library-a',byId:new Map()},editingId:'old',editingBaseline:{},writeBusy:false,$:selector=>nodes[selector.slice(1)],canWrite:()=>writable,writeBlockedReason:()=>'当前不可写',libraryName:id=>id==='library-a'?'松果的记忆库':'其他库',localDateTime:()=> '2026-11-04T12:00',num:value=>Number(value)||0,api:async(...args)=>{calls.push(JSON.parse(JSON.stringify(args)));return {id:'new'};},invalidateRecall(){},updateWriteState(){},resetBrowseAfterWrite(){},reload:async()=>{},select(){},toast:(...args)=>messages.push(args),closeMemoryDialog(){}};
 vm.createContext(c);vm.runInContext(code,c);return {nodes,c,calls,messages};
}
test('ordinary Add explicitly resets stale concept to episode and names the destination library',()=>{
 const e=environment();e.c.openAdd();assert.equal(e.nodes.newKind.value,'episode');assert.equal(e.nodes.newImportant.checked,false);assert(e.nodes.memoryDialogIntro.textContent.includes('松果的记忆库'));assert(e.nodes.memoryDialogIntro.textContent.includes('慢慢淡化'));assert.equal(e.nodes.addDialog.open,true);assert.equal(e.nodes.newLabel.focused,true);assert.equal(e.c.editingId,null);assert.equal(e.calls.length,0);
});
test('saving ordinary notes submits episode and unimportant; explicit advanced concept still submits unchanged',async()=>{
 for(const kind of ['episode','concept']){const e=environment();e.c.openAdd();if(kind==='concept')e.nodes.newKind.value=kind;e.nodes.newLabel.value='普通的一天';e.nodes.newText.value='今天散步看见一只鸟';await e.nodes.addForm.submit({preventDefault(){}});assert.equal(e.calls.length,1);assert.equal(e.calls[0][0],'add');assert.equal(e.calls[0][1].kind,kind);assert.equal(e.calls[0][1].meta.important,false);assert.equal(e.calls[0][1].salience,.6);assert.equal(e.c.writeBusy,false);}
});
test('read-only Add leaves the form closed and never mutates the library',()=>{const e=environment(false);e.c.openAdd();assert.equal(e.nodes.addDialog.open,undefined);assert.equal(e.calls.length,0);assert.equal(e.c.editingId,'old');assert.equal(e.messages[0][0],'当前不可写');});
