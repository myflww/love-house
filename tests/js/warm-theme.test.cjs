/* Theme state is independent from graph mode; no browser or private data. */
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createHash}=require('node:crypto');
const test=require('node:test');
const assert=require('node:assert/strict');
const localSource=path.join(__dirname,'warm-theme.js');
const sourcePath=process.env.WARM_THEME_SOURCE||(fs.existsSync(localSource)?localSource:path.resolve(__dirname,'../../nkb/viz/web/warm-theme.js'));
const source=fs.readFileSync(sourcePath,'utf8');

function environment({saved,theme='dark',legacy='blossom',storageFails=false,buttons=true,hasSchedule=true}={}){
 class Element{
  constructor(tag,id=''){
   this.tagName=tag.toUpperCase();this.id=id;this.attrs=new Map();this.textContent='';this.onclick=null;
   const classes=new Set();this.classList={add:name=>classes.add(name),contains:name=>classes.has(name)};
   this.style={properties:{},setProperty(key,value){this.properties[key]=String(value);}};
  }
  setAttribute(key,value){this.attrs.set(key,String(value));}
  getAttribute(key){return this.attrs.get(key)||null;}
 }
 const html={dataset:{theme,colorway:legacy}},styles=[];
 const themeButton=new Element('button','themeBtn'),viewButton=new Element('button','viewBtn');
 const ids=new Map(buttons?[[themeButton.id,themeButton],[viewButton.id,viewButton]]:[]);
 let viewCalls=0,scheduled=0;
 const originalView=()=>{viewCalls++;html.dataset.art=html.dataset.art==='true'?'false':'true';};
 viewButton.onclick=originalView;
 const storage=new Map([['love-house-colorway',legacy]]);if(saved!==undefined)storage.set('nkb-theme',saved);
 const reads=[],writes=[];
 const localStorage={
  getItem(key){reads.push(key);if(storageFails)throw new Error('storage unavailable');return storage.get(key)??null;},
  setItem(key,value){if(storageFails)throw new Error('storage unavailable');storage.set(key,String(value));writes.push([key,String(value)]);}
 };
 const document={documentElement:html,head:{append:element=>styles.push(element)},body:{},
  getElementById:id=>ids.get(id)||styles.find(s=>s.id===id)||null,
  createElement:tag=>new Element(tag),querySelector:()=>null,querySelectorAll:selector=>selector==='button'?[...ids.values()]:[]};
 const context={document,window:{},localStorage,MutationObserver:class{observe(){}},queueMicrotask:fn=>fn()};
 if(hasSchedule)context.schedule=()=>{scheduled++;};
 vm.runInNewContext(source,context,{filename:sourcePath});
 return{html,themeButton,viewButton,originalView,styles,storage,reads,writes,api:context.window.LoveHouseAppearance,
  get viewCalls(){return viewCalls;},get scheduled(){return scheduled;}};
}

test('graph black/white preference and original UI colorway restore independently',()=>{
 const dark=environment({saved:'dark',theme:'light'});
 assert.equal(dark.html.dataset.theme,'dark');assert.equal(dark.html.dataset.houseTheme,'pixel');
 assert.equal(dark.html.dataset.colorway,'blossom');
 assert.deepEqual(dark.reads,['love-house-colorway','nkb-theme']);assert.deepEqual(dark.writes,[]);
 assert.equal(dark.themeButton.getAttribute('aria-label'),'切换星云画布白色主题');
 assert.equal(dark.themeButton.getAttribute('data-hint-title'),'切换星云画布白色主题');
 assert.match(dark.themeButton.getAttribute('data-hint-description'),/仅将神经星云画布.*白底黑色.*奶油粉色像素界面与彩色按钮保持原样/);
 assert.equal(environment({saved:'light'}).html.dataset.theme,'light');
 assert.equal(environment({legacy:null}).html.dataset.colorway,'cream');
 assert.equal(environment({legacy:'cream'}).html.dataset.colorway,'cream');
 assert.equal(environment({saved:'invalid',theme:'light'}).html.dataset.theme,'light');
 assert.equal(environment({saved:'blossom',theme:'invalid'}).html.dataset.theme,'dark');
});

test('theme button persists nkb-theme and restores it after reopening',()=>{
 const e=environment();const before=e.scheduled,initialStyle=JSON.stringify(e.themeButton.style.properties);assert.equal(e.themeButton.getAttribute('aria-pressed'),null);e.themeButton.onclick();
 assert.equal(e.html.dataset.theme,'light');assert.equal(e.scheduled,before+1);
 assert.deepEqual(e.writes,[['nkb-theme','light']]);
 assert.equal(e.themeButton.getAttribute('aria-label'),'切换星云画布黑色主题');
 assert.equal(e.themeButton.getAttribute('aria-pressed'),null);assert.equal(JSON.stringify(e.themeButton.style.properties),initialStyle);
 assert.match(e.themeButton.getAttribute('data-hint-description'),/仅将神经星云画布.*黑底白色.*奶油粉色像素界面与彩色按钮保持原样/);
 const reopened=environment({saved:e.storage.get('nkb-theme')});assert.equal(reopened.html.dataset.theme,'light');
 e.themeButton.onclick();assert.equal(e.html.dataset.theme,'dark');
 assert.equal(e.themeButton.getAttribute('aria-pressed'),null);assert.equal(JSON.stringify(e.themeButton.style.properties),initialStyle);
 assert.deepEqual(e.writes.at(-1),['nkb-theme','dark']);
});

test('view handler is preserved by identity and changing mode preserves both themes',()=>{
 const e=environment();assert.equal(e.viewButton.onclick,e.originalView);
 e.viewButton.onclick();assert.equal(e.viewCalls,1);assert.equal(e.html.dataset.theme,'dark');
 e.api.setTheme('light');e.viewButton.onclick();
 assert.equal(e.viewCalls,2);assert.equal(e.html.dataset.theme,'light');assert.deepEqual(e.writes,[]);
});

test('public setTheme and legacy wrapper never resurrect old colorway forcing',()=>{
 const e=environment();
 assert.equal(e.api.setTheme('light',true),'light');assert.equal(e.html.dataset.theme,'light');
 assert.equal(e.api.setColorway('cream'),'light');assert.equal(e.api.setColorway('blossom'),'light');
 assert.equal(e.api.setTheme('invalid'),'light');
 assert.equal(e.api.setColorway('dark',true),'dark');assert.equal(e.html.dataset.theme,'dark');
 assert.equal(e.html.dataset.colorway,'blossom');
 assert.deepEqual(e.writes,[['nkb-theme','light'],['nkb-theme','dark']]);
});

test('blocked storage, absent controls and absent scheduler remain usable',()=>{
 const e=environment({theme:'light',storageFails:true,buttons:false,hasSchedule:false});
 assert.equal(e.html.dataset.theme,'light');
 assert.equal(e.api.setTheme('dark',true),'dark');assert.equal(e.html.dataset.theme,'dark');
 assert.equal(e.styles.length,1);
});

// Original licensed pixel UI/style + embedded asset prefix, from 0.9.2 HEAD.
// A graph theme must not recolor controls or replace these established surfaces.
test('original cream/pink UI CSS, colorful button assets and fonts are byte-preserved',()=>{
 const marker='/* Graph canvas appearance only.';
 const boundary=source.indexOf(marker);assert.ok(boundary>0);
 assert.equal(createHash('sha256').update(source.slice(0,boundary)).digest('hex'),'96b3e9c0f7ade6d49559983bffe7d0aef22c79865ec77826c79fd3a49ffe2c3d');
 const graphStyle=source.slice(boundary,source.indexOf('document.head.append(style);',boundary));
 const properties=[...graphStyle.matchAll(/(--[a-z-]+)\s*:/g)].map(match=>match[1]);
 assert.deepEqual([...new Set(properties)].sort(),['--graph-bg','--graph-ink','--graph-line','--graph-muted','--halo']);
 assert.doesNotMatch(graphStyle,/filter:|border-image:|background-image:|color-scheme:/);
 const e=environment({legacy:'blossom'}),css=e.styles[0].textContent;
 assert.match(css,/--bg:#fff6df;--paper:#fffaf0/);
 assert.match(css,/background-image:var\(--house-secondary-image\)/);
 assert.match(css,/border-image-source:var\(--house-primary-image\)/);
 const unchanged=e.styles[0].textContent;
 e.themeButton.onclick();assert.equal(e.html.dataset.colorway,'blossom');assert.equal(e.html.dataset.houseTheme,'pixel');
 assert.equal(e.styles[0].textContent,unchanged);
});
