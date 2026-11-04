/* Run the shipped navigation over existing controls and handlers, without a provider. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/workspace-shell.js'),'utf8');

function environment(){
  let document;
  const all=node=>[node,...(node.childNodes||[]).flatMap(all)];
  class Text{
    constructor(text){this.nodeType=3;this.textContent=String(text);this.childNodes=[];}
    remove(){if(this.parentElement)this.parentElement.childNodes=this.parentElement.childNodes.filter(n=>n!==this);this.parentElement=null;}
  }
  class Element{
    constructor(tag){this.nodeType=1;this.tagName=tag.toUpperCase();this.childNodes=[];this.attrs={};this.dataset={};this.events={};this.hidden=false;this.disabled=false;this.open=false;this.style={setProperty(k,v){this[k]=v;}};this.className='';this.id='';this.scrollTop=99;this.classList={add:(...names)=>{this.className=[...new Set([...this.className.split(/\s+/),...names])].filter(Boolean).join(' ');},remove:(...names)=>{this.className=this.className.split(/\s+/).filter(n=>!names.includes(n)).join(' ');},contains:n=>this.className.split(/\s+/).includes(n)};}
    get children(){return this.childNodes.filter(n=>n.nodeType===1);}
    get textContent(){return this.childNodes.map(n=>n.textContent).join('');}
    set textContent(text){this.childNodes=[];this.append(new Text(text));}
    remove(){if(this.parentElement)this.parentElement.childNodes=this.parentElement.childNodes.filter(n=>n!==this);this.parentElement=null;}
    append(...nodes){for(let n of nodes){if(typeof n==='string')n=new Text(n);n.remove();n.parentElement=this;this.childNodes.push(n);}}
    prepend(...nodes){for(const n of [...nodes].reverse()){n.remove();n.parentElement=this;this.childNodes.unshift(n);}}
    before(...nodes){if(!this.parentElement)return;const parent=this.parentElement;for(const n of nodes){n.remove();n.parentElement=parent;parent.childNodes.splice(parent.childNodes.indexOf(this),0,n);}}
    after(...nodes){if(!this.parentElement)return;const parent=this.parentElement;let index=parent.childNodes.indexOf(this)+1;for(const n of nodes){n.remove();n.parentElement=parent;parent.childNodes.splice(index++,0,n);}}
    setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')this.id=String(v);}
    getAttribute(k){if(k==='id')return this.id||null;return this.attrs[k]??null;}
    matches(selector){
      selector=selector.trim();if(selector==='button:not([disabled])')return this.tagName==='BUTTON'&&!this.disabled;
      const attr=selector.match(/\[([^=\]]+)=['"]?([^'"\]]+)['"]?\]/);if(attr&&this.getAttribute(attr[1])!==attr[2])return false;
      selector=selector.replace(/\[[^\]]+\]/g,'');const id=selector.match(/#([\w-]+)/);if(id&&this.id!==id[1])return false;
      const cls=selector.match(/\.([\w-]+)/);if(cls&&!this.classList.contains(cls[1]))return false;
      const tag=selector.match(/^[a-z]+/i);return !tag||this.tagName===tag[0].toUpperCase();
    }
    querySelectorAll(selector){
      if(selector.startsWith(':scope>'))return this.children.filter(n=>n.matches(selector.slice(7)));
      const terms=selector.trim().split(/\s*>\s*|\s+/);return all(this).slice(1).filter(n=>{
        if(n.nodeType!==1||!n.matches(terms.at(-1)))return false;
        let ancestor=n.parentElement;for(let i=terms.length-2;i>=0;i--){while(ancestor&&!ancestor.matches(terms[i]))ancestor=ancestor.parentElement;if(!ancestor)return false;ancestor=ancestor.parentElement;}return true;
      });
    }
    querySelector(s){return this.querySelectorAll(s)[0]||null;}
    closest(s){for(let node=this;node;node=node.parentElement)if(node.matches(s))return node;return null;}
    contains(n){return n===this||this.children.some(c=>c.contains(n));}
    addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
    click(){if(this.disabled)return;const event={target:this};this.onclick?.(event);for(const fn of this.events.click||[])fn(event);}
    focus(){document.activeElement=this;}
    getBoundingClientRect(){return {height:82,width:1200};}
  }
  const root=new Element('html'),head=new Element('head'),body=new Element('body');root.append(head,body);
  document={documentElement:root,head,body,events:{},createElement:tag=>new Element(tag),getElementById:id=>all(root).find(n=>n.id===id)||null,querySelector:s=>root.querySelector(s),addEventListener(type,fn){(this.events[type]??=[]).push(fn);}};
  const make=(tag,id,parent,cls='',text='')=>{const n=new Element(tag);n.id=id;n.className=cls;if(text)n.textContent=text;parent.append(n);return n;};
  const app=make('div','app',body),header=make('header','',app),brand=make('div','',header,'brand'),search=make('form','searchForm',header,'search'),actions=make('div','',header,'head-actions'),main=make('main','',app);
  const names=['menuBtn','companionBtn','addBtn','importBtn','dialogueImportBtn','settingsBtn','filterBtn','timeBtn','detailBtn','layoutBtn','viewBtn','pauseBtn','themeBtn','fullscreenBtn'];
  const originals={},calls=[];
  for(const id of names){const b=make('button',id,actions,'icon-btn','icon');b.setAttribute('aria-label',id==='pauseBtn'?'暂停动效':id==='viewBtn'?'切换平面引力图':id==='themeBtn'?'切换白色星云':id==='fullscreenBtn'?'进入全屏':id);b.onclick=()=>calls.push(id);originals[id]=b;}
  const identity=make('div','',brand,'organizer-library-identity');make('button','libraryMenuBtn',identity);make('button','organizerLibraryApiStatus',identity,'','API已配置');
  const settings=make('section','settings',main),title=make('div','',settings,'setting-title');make('strong','',title,'','设置');const maintenance=make('div','',settings,'maintenance-links');
  make('button','organizeBtn',maintenance,'btn','整理 ');make('small','organizerMiniStatus',document.getElementById('organizeBtn'),'','启用');make('button','backupBtn',maintenance);
  for(const id of ['steps','damping','labels','learn']){const row=make('label','',settings,'setting-row');make(id==='labels'?'select':'input',id,row);}
  make('p','learningNote',settings,'settings-note','学习说明');make('p','',settings,'settings-note','署名说明');
  make('section','organizerPanel',main);const heading=make('div','',document.getElementById('organizerPanel'),'inspector-top');make('strong','',heading,'','记忆整理');make('div','',document.getElementById('organizerPanel'),'companion-scroll');
  make('section','filterPanel',main);
  const organizer=make('details','organizerSettings',document.getElementById('organizerPanel'));make('p','organizerApiPurpose',organizer);make('button','saveOrganizerSettings',organizer);make('button','saveAndEnableOrganizer',organizer);
  for(const id of ['personaOrganizerSettings','personaApiRecommendationConfigure','organizerApiRecommendationConfigure']){const b=make('button',id,body);b.onclick=()=>calls.push(id);}
  const wizard=make('dialog','connectionWizardDialog',body),screen=make('section','',wizard,'wizard-screen');make('h3','',screen,'','旧标题');make('button','startConnectionWizard',body);
  make('button','importMemoryShareBtn',body);const form=make('form','addForm',body);
  for(const id of ['newImpact','newSession','newEventAt','newTags']){const label=make('label','',form);label.setAttribute('for',id);make('input',id,form);}
  const important=make('label','',form);make('input','newImportant',important);make('div','',form,'dialog-actions');
  const detail=make('div','detail',main),detailCalls=[];
  const draw=()=>{detail.childNodes=[];const row=make('div','',detail,'detail-actions');for(const [id,name]of [['correct','纠正内容'],['disable','暂不使用'],['edit','编辑记忆'],['reinforce','强化记忆'],['focus','聚焦邻居'],['forget','真正忘记']]){const b=make('button',id,row,'btn',name);b.onclick=()=>detailCalls.push(id);}};draw();
  const callbacks=Object.fromEntries(Object.entries(originals).map(([id,button])=>[id,button.onclick]));
  const observers=[],context={document,window:{events:{},addEventListener(type,fn){(this.events[type]??=[]).push(fn);}},MutationObserver:class{constructor(fn){this.fn=fn;observers.push(this);}observe(){}},queueMicrotask:fn=>fn(),PANELS:{settings:'settingsBtn'},setPanelOpen:(...args)=>calls.push(args),S:{libraryId:'fish-a',libraryEpoch:1,selected:'memory-a'},renderDetail:draw};
  vm.runInNewContext(source,context,{filename:'workspace-shell.js'});
  const by=id=>document.getElementById(id);
  const fire=(type,event)=>{event.preventDefault??=()=>{event.prevented=true;};event.stopPropagation??=()=>{event.stopped=true;};for(const fn of document.events[type]||[])fn(event);return event;};
  return {context,document,by,all:()=>all(root),originals,callbacks,calls,detailCalls,fire};
}

test('labelled navigation moves original controls, preserving handlers, IDs and status nodes',()=>{
  const e=environment();assert.deepEqual(e.by('companionBtn'),e.originals.companionBtn);assert.equal(e.by('companionBtn').textContent,'连接');
  for(const [id,original]of Object.entries(e.originals)){assert.equal(e.by(id),original);assert.equal(e.by(id).onclick,e.callbacks[id]);}
  assert.equal(e.by('organizerMiniStatus').textContent,'启用');assert.equal(e.by('organizeBtn').querySelector('.workspace-button-label').textContent,'整理');
  for(const id of ['addBtn','importBtn','dialogueImportBtn','importMemoryShareBtn'])assert.equal(e.by(id).parentElement,e.by('workspaceAddMenu').querySelector('.workspace-tool-list'));
  e.by('addBtn').click();assert.equal(e.calls.filter(c=>c==='addBtn').length,1);
  const ids=e.all().filter(n=>n.id).map(n=>n.id);assert.equal(new Set(ids).size,ids.length);
  assert.equal(e.by('steps').closest('details').id,'workspaceRecallAdvanced');assert.equal(e.by('labels').closest('section').id,'workspaceDisplayMenu');
});

test('menus close on Escape or outside click, restore keyboard focus, and preserve disabled actions',()=>{
  const e=environment();e.by('workspaceDisplayButton').click();assert.equal(e.by('workspaceDisplayMenu').hidden,false);assert.equal(e.by('workspaceDisplayButton').getAttribute('aria-expanded'),'true');
  const event=e.fire('keydown',{key:'Escape'});assert.ok(event.prevented&&event.stopped);assert.equal(e.by('workspaceDisplayMenu').hidden,true);assert.equal(e.document.activeElement,e.by('workspaceDisplayButton'));
  e.by('workspaceAddButton').click();e.fire('pointerdown',{target:e.by('searchForm')});assert.equal(e.by('workspaceAddMenu').hidden,true);
  e.by('workspaceDisplayButton').click();e.by('workspaceAddButton').click();assert.equal(e.by('workspaceDisplayMenu').hidden,true);assert.equal(e.by('workspaceAddMenu').hidden,false);
  e.by('addBtn').disabled=true;e.by('addBtn').click();assert.equal(e.calls.filter(c=>c==='addBtn').length,0);
});

test('closing a panel opened from the display menu returns to its visible trigger',()=>{
  const e=environment();e.context.setPanelOpen('filterPanel',false);assert.equal(e.document.activeElement,e.by('workspaceDisplayButton'));
  e.by('companionBtn').focus();e.context.setPanelOpen('filterPanel',false,{restore:false});assert.equal(e.document.activeElement,e.by('companionBtn'));
});

test('organizer keeps one primary save action and no navigation implicitly enables its model',()=>{
  const e=environment();assert.equal(e.by('saveAndEnableOrganizer').hidden,true);assert.equal(e.by('saveOrganizerSettings').classList.contains('primary'),true);
  for(const id of ['menuBtn','companionBtn','organizeBtn','settingsBtn'])assert.equal(e.by(id).getAttribute('aria-label'),e.by(id).querySelector('.workspace-button-label')?.textContent||e.by(id).textContent);
  assert.equal(e.calls.length,0,'building navigation does not save or run anything');
});

test('state labels remain readable after original handlers rewrite glyphs',()=>{
  const e=environment();const pause=e.by('pauseBtn');pause.textContent='▷';pause.setAttribute('aria-label','继续动效');e.context.window.LoveHouseWorkspace.refresh();assert.equal(pause.textContent,'继续动效');
  pause.click();assert.equal(e.calls.filter(c=>c==='pauseBtn').length,1);
});

test('correction and disable stay primary; edit and forget retain independent original handlers and disclosure',()=>{
  const e=environment();assert.equal(e.by('correct').parentElement.className,'detail-actions');assert.equal(e.by('correct').closest('details'),null);
  const advanced=e.by('edit').closest('details'),danger=e.by('forget').closest('details');assert.ok(advanced.classList.contains('workspace-detail-advanced'));assert.ok(danger.classList.contains('workspace-detail-danger'));
  assert.equal(e.by('edit').textContent,'编辑原条目');assert.equal(danger.open,false);e.by('forget').click();assert.deepEqual(e.detailCalls,['forget']);
  advanced.open=true;e.context.renderDetail();assert.equal(e.by('edit').closest('details').open,true);
  e.context.S.selected='memory-b';e.context.renderDetail();assert.equal(e.by('edit').closest('details').open,false);
});
