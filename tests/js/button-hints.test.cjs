const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.resolve(__dirname, '../../nkb/viz/web/button-hints.js'), 'utf8');

function environment() {
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.nodeType = 1; this.attrs = new Map(); this.children = [];
      this.parentElement = null; this.style = {}; this.id = ''; this.className = ''; this._text = '';
      this.isConnected = true; this.disabled = false; this.hidden = false;
      this.rect = {left:100, top:50, right:134, bottom:84, width:34, height:34};
      this.classList = {contains:name=>this.className.split(/\s+/).includes(name)};
    }
    get textContent() {return this._text + this.children.map(c=>c.textContent).join('');}
    set textContent(value) {this._text=String(value);this.children=[];}
    getAttribute(k) {return this.attrs.has(k)?this.attrs.get(k):null;}
    hasAttribute(k) {return this.attrs.has(k);}
    setAttribute(k,v) {this.attrs.set(k,String(v));}
    removeAttribute(k) {this.attrs.delete(k);}
    append(...nodes) {for(const n of nodes){if(n.parentElement)n.parentElement.children=n.parentElement.children.filter(c=>c!==n);n.parentElement=this;this.children.push(n);}}
    replaceChildren(...nodes) {this._text='';this.children=[];this.append(...nodes);}
    matches(selector) {
      return selector.split(',').some(raw=>{
        const p=raw.trim();
        if(p==='button'||p==='summary')return this.tagName===p.toUpperCase();
        if(p==='dialog[open]')return this.tagName==='DIALOG'&&this.hasAttribute('open');
        const m=p.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);
        if(m)return this.hasAttribute(m[1])&&(m[2]===undefined||this.getAttribute(m[1])===m[2]);
        return false;
      });
    }
    closest(selector) {for(let n=this;n;n=n.parentElement)if(n.matches(selector))return n;return null;}
    querySelectorAll(selector) {return this.children.flatMap(n=>[...(n.matches(selector)?[n]:[]),...n.querySelectorAll(selector)]);}
    querySelector(selector) {if(selector==='.row-label')return this.children.find(n=>n.className==='row-label')||null;return this.querySelectorAll(selector)[0]||null;}
    contains(other) {return this===other||this.children.some(n=>n.contains(other));}
    getBoundingClientRect() {return this.id==='nkb-button-hint'?{...this.rect,width:240,height:100}:this.rect;}
  }
  const handlers={},windowHandlers={},observers=[],timers=new Map();let sequence=0;
  const doc={readyState:'complete',hidden:false,nodeType:9,head:new Element('head'),body:new Element('body'),documentElement:{clientWidth:800,clientHeight:600},hitTarget:null,
    createElement:tag=>new Element(tag),querySelectorAll:selector=>[...doc.head.querySelectorAll(selector),...doc.body.querySelectorAll(selector)],
    getElementById:id=>[doc.head,doc.body,...doc.head.querySelectorAll('button'),...doc.body.children].find(n=>n.id===id)||null,
    elementFromPoint:()=>doc.hitTarget,addEventListener:(type,fn)=>(handlers[type]??=[]).push(fn)};
  const win={innerWidth:800,innerHeight:600,addEventListener:(type,fn)=>(windowHandlers[type]??=[]).push(fn)};
  const context={document:doc,window:win,module:{exports:{}},WeakMap,MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},
    setTimeout:(fn,delay)=>{const id=++sequence;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id)};
  function button(id,label) {const el=new Element('button');el.id=id;el.textContent=label;doc.body.append(el);return el;}
  const add=button('addBtn','+');add.setAttribute('aria-label','添加记忆');add.setAttribute('title','添加');
  const close=button('closeDetail','×');close.setAttribute('aria-label','关闭节点详情');
  vm.runInNewContext(source,context,{filename:'button-hints.js'});
  const fire=(type,event={})=>{if(type==='focusin')doc.activeElement=event.target;event.preventDefault??=()=>{event.prevented=true;};event.stopPropagation??=()=>{event.stopped=true;};for(const fn of handlers[type]||[])fn(event);return event;};
  const flush=()=>{const entries=[...timers];timers.clear();entries.forEach(([,t])=>t.fn());};
  return {doc,win,add,close,button,fire,flush,timers,observers,windowHandlers,api:context.module.exports,tip:doc.getElementById('nkb-button-hint')};
}

test('hover waits, focus is immediate, help names its purpose and preserves existing descriptions',()=>{
  const e=environment();e.add.setAttribute('aria-describedby','existing-note');e.doc.hitTarget=e.add;
  assert.equal(e.add.hasAttribute('title'),false,'native tooltip is removed');
  e.fire('pointerover',{target:e.add,clientX:110,clientY:60,pointerType:'mouse'});
  assert.equal(e.tip.hidden,true);assert.equal([...e.timers.values()][0].delay,260);
  e.flush();assert.equal(e.tip.hidden,false);assert.match(e.tip.textContent,/手动保存一条/);
  assert.equal(e.add.getAttribute('aria-describedby'),'existing-note nkb-button-hint');
  e.fire('pointerout',{target:e.add,relatedTarget:e.doc.body});
  assert.equal(e.tip.hidden,true);assert.equal(e.add.getAttribute('aria-describedby'),'existing-note');
  e.fire('focusin',{target:e.add});assert.equal([...e.timers.values()][0].delay,0);e.flush();
  const escape=e.fire('keydown',{key:'Escape'});assert.equal(e.tip.hidden,true);assert.ok(escape.prevented&&escape.stopped);
});

test('disabled pointer routing explains why, and clamps help at the viewport edge',()=>{
  const e=environment();const disabled=e.button('applyConnectionBtn','应用');disabled.disabled=true;
  disabled.setAttribute('title','请先预览改动');disabled.rect={left:780,top:580,right:814,bottom:614,width:34,height:34};
  e.doc.hitTarget=disabled;e.fire('pointermove',{target:e.doc.body,clientX:790,clientY:590});e.flush();
  assert.match(e.tip.textContent,/请先预览改动/);assert.equal(disabled.hasAttribute('title'),false);
  assert.ok(parseInt(e.tip.style.left)>=10&&parseInt(e.tip.style.left)+240<=790);
  assert.ok(parseInt(e.tip.style.top)>=10&&parseInt(e.tip.style.top)+100<=590);
  e.fire('scroll');assert.equal(e.tip.hidden,true);
});

test('dynamic help is supported without reading inputs or memory bodies, own changes do not loop',()=>{
  const e=environment();const control=e.button('customStep','继续');
  control.setAttribute('data-hint-title','完成连接');control.setAttribute('data-hint-description','等待一轮真实存档。');
  Object.defineProperty(control,'value',{get(){throw new Error('form values must not be read');}});
  const memory=e.button('','');memory.className='node-row';memory.setAttribute('aria-label','短标题，经历，查看完整信息');
  Object.defineProperty(memory,'textContent',{get(){throw new Error('memory body must not be read');}});
  assert.match(e.api.readHint(memory).title,/短标题/);
  e.observers[0]([{type:'childList',target:e.doc.body,addedNodes:[control]}]);
  e.fire('focusin',{target:control});e.flush();assert.match(e.tip.textContent,/等待一轮真实存档/);
  const title=e.tip.children[0];e.observers[0]([{type:'childList',target:e.tip,addedNodes:[title]}]);
  assert.equal(e.tip.children[0],title,'own text changes must not trigger another render');
  control.setAttribute('data-hint-description','新的安全说明');e.observers[0]([{type:'attributes',target:control}]);
  assert.match(e.tip.textContent,/新的安全说明/);
  e.fire('pointerdown',{target:control});assert.equal(e.tip.hidden,true);
  e.fire('focusin',{target:control});e.flush();assert.equal(e.tip.hidden,true,'mouse-driven programmatic focus must not cover the next dialog');
  e.fire('keydown',{key:'Tab'});e.flush();assert.equal(e.tip.hidden,false,'keyboard navigation restores focus help');
});

test('modal help mounts in its dialog and is removed from accessibility descriptions when detached',()=>{
  const e=environment();const dialog=e.doc.createElement('dialog');dialog.setAttribute('open','');e.doc.body.append(dialog);
  const button=e.button('confirmCorrectMemory','保存纠正');dialog.append(button);
  e.fire('focusin',{target:button});e.flush();assert.equal(e.tip.parentElement,dialog);
  assert.match(e.tip.textContent,/新建正确内容/);
  button.isConnected=false;e.observers[0]([{type:'childList',target:dialog,addedNodes:[]}]);
  assert.equal(e.tip.hidden,true);assert.equal(button.getAttribute('aria-describedby'),null);
});
