import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { HostAdapter, SOURCE_KIND, sanitize, apply } from '../dist/index.js';
import { createProxy } from '../dist/proxy.js';
import { Context } from '@deepseek-ai/cordis';
import SessionStore, { SessionId } from '@deepseek-ai/dsh-session';
import { createUserMessage, createAssistantMessage } from '@deepseek-ai/dsh-llm';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function eventually(check) { for (let i=0;i<80;i++) { if(check())return; await sleep(25); } assert.ok(check(), 'condition not reached'); }
async function mockController({reject=false}={}) {
  const events=[]; const contexts=[]; const server=http.createServer(async(req,res)=>{
    let raw='';for await(const part of req)raw+=part;
    const body=raw?JSON.parse(raw):null;
    res.setHeader('content-type','application/json');
    if(req.url==='/api/health')return res.end('{"ok":true,"version":"0.4.0"}');
    if(!req.headers.authorization?.startsWith('Bearer fixture-')){res.statusCode=401;return res.end('{}');}
    if(req.url.endsWith('/heartbeat'))return res.end('{"host_online":true}');
    if(req.url.endsWith('/context')){contexts.push({url:req.url,body});return res.end(JSON.stringify({packet:'已选库的真实人格和记忆材料',memory_ids:['memory-1']}));}
    events.push({url:req.url,body});res.end(JSON.stringify({accepted:!reject,status:'pending'}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {events,contexts,server,base:`http://127.0.0.1:${server.address().port}`,close:()=>new Promise(resolve=>server.close(resolve))};
}
function fixture(base, extra={}) {
  const dir=mkdtempSync(join(tmpdir(),'neural-host-test-'));const config=join(dir,'connection.json');
  writeFileSync(config,JSON.stringify({connection_id:'connection-a',connection_token:'fixture-secret-not-a-real-token',library_id:'library-a',base_url:base,...extra}));
  const options={connection_file:config,host_version:'0.2.1-rc.3',state_dir:join(dir,'outbox'),retry_ms:20,timeout_ms:300};
  return {dir,config,options,clean:()=>rmSync(dir,{recursive:true,force:true})};
}
const session={id:'actual-session-id',header:{id:'actual-session-id',origin:undefined}};
const message=(id,role,text,source={kind:role==='assistant'?'model':'user'})=>({id,role,source,content:[{type:'text',text}]});
function turn(adapter,{start=0,reason='completed',interrupted=false}={}) {
  let seq=start;const emit=(type,data)=>adapter.capture(session,{type,data,seq:seq++,time:1800000000000+seq});
  emit('turn/start',{turn:1});
  emit('user/message',{...message('user-message-1','user','用户实际原话，api_key这个词不能被改写'),content:[{type:'text',text:'用户实际原话，api_key这个词不能被改写'},{type:'file',attachment:{id:'attachment-1',path:'/reference/not-read.txt',name:'笔记.txt',size:123}}]});
  emit('tool/call',{turn:1,step:1,callId:'call-real-1',name:'browser.click',arguments:'{"target":"submit","api_key":"must-not-leak"}'});
  emit('tool/result',{turn:1,step:1,message:{...message('tool-message-1','tool','真实工具结果：操作失败',{kind:'tool',callId:'call-real-1'}),toolCallId:'call-real-1',isError:true},meta:{authorization:'must-not-leak',kept:'visible'}});
  emit('assistant/message',{turn:1,step:1,message:message('assistant-message-1','assistant','实际助手正文'),interrupted});
  emit('turn/end',{turn:1,reason:{kind:reason}});
}

test('passive session events preserve real roles, attachments and failed tool outcomes; ACK pending is not graph success',async()=>{
  const mock=await mockController();const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{turn(adapter);await adapter.flush();assert.equal(mock.events.length,6);
    const raw=mock.events.find(e=>e.body.event_type==='user/message').body.record.raw_event;
    assert.equal(raw.data.id,'user-message-1');assert.equal(raw.data.content[1].attachment.path,'/reference/not-read.txt');
    assert.equal(raw.data.content[0].text,'用户实际原话，api_key这个词不能被改写');
    const tool=mock.events.find(e=>e.body.event_type==='tool/result').body.record;
    assert.equal(tool.normalized.outcome,'failed');assert.equal(tool.normalized.call_id,'call-real-1');assert.equal(tool.normalized.tool_name,'browser.click');
    assert.equal(tool.raw_event.data.meta.authorization,undefined);
    assert.equal(JSON.stringify(mock.events).includes('must-not-leak'),false);
    const normalized=mock.events.at(-1).body.record.normalized;
    assert.equal(normalized.status,'complete');assert.equal(normalized.messages[0].id,'user-message-1');assert.equal(normalized.messages[1].role,'assistant');
    assert.equal(normalized.user,'用户实际原话，api_key这个词不能被改写');
    assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,0);
    assert.ok(mock.events.every(e=>e.url==='/api/connections/connection-a/events'&&e.body.library_id===undefined));
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('pre-step automatically injects actual context, preserves downstream decision, excludes its synthetic event',async()=>{
  const mock=await mockController();const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{const original=message('u-2','user','这是新一轮真实问题');const payload={agent:{session},messages:[original],turn:2,step:1,signal:new AbortController().signal};
    const result=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[original],startsRequestSeries:true}));
    assert.equal(result.startsRequestSeries,true);assert.equal(result.messages.length,2);assert.equal(result.messages[0].source.kind,SOURCE_KIND);
    assert.ok(result.messages[0].content[0].text.includes('已选库的真实人格和记忆材料'));assert.ok(result.messages[0].content[0].text.includes('library-a'));assert.equal(result.messages[1],original);
    adapter.capture(session,{type:'user/message',seq:99,time:1,data:result.messages[0]});await adapter.flush();assert.equal(mock.events.length,0);
    assert.equal(mock.contexts[0].body.session_id,session.id);assert.equal(mock.contexts[0].url,'/api/connections/connection-a/context');
    const again=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[original]}));assert.equal(again.messages.length,1);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('aborted or interrupted output cannot be normalized as complete',async()=>{
  const mock=await mockController();const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{turn(adapter,{reason:'aborted'});await adapter.flush();assert.equal(mock.events.at(-1).body.record.normalized.status,'partial');
    turn(adapter,{start:10,interrupted:true});await adapter.flush();assert.equal(mock.events.at(-1).body.record.normalized.status,'partial');
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('durable outbox survives unload/restart and only accepted:true removes it',async()=>{
  const mock=await mockController({reject:true});const f=fixture(mock.base);let adapter=new HostAdapter(f.options);
  try{turn(adapter);await adapter.flush();const firstId=mock.events[0].body.event_id;assert.ok(readdirSync(adapter.stateDir).some(p=>p.endsWith('.event.json')));await adapter.dispose();
    await mock.close();const recovered=await mockController();const cfg=JSON.parse(readFileSync(f.config));cfg.base_url=recovered.base;writeFileSync(f.config,JSON.stringify(cfg));
    adapter=new HostAdapter(f.options);await adapter.flush();assert.equal(recovered.events.length,6);assert.equal(recovered.events[0].body.event_id,firstId);
    assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,0);await recovered.close();
  }finally{await adapter.dispose();f.clean();}
});

test('official hook names are registered by apply without model tool calls and disposed through Cordis effect',async()=>{
  const mock=await mockController();const f=fixture(mock.base);const listeners=new Map();const cleanup=[];
  const ctx={logger:{warn(){}},on(name,handler){listeners.set(name,handler);},effect(factory){cleanup.push(factory());}};
  try{apply(ctx,f.options);assert.ok(listeners.has('session/event'));assert.ok(listeners.has('agent/pre-step'));
    listeners.get('session/event')(session,{type:'turn/start',data:{turn:1},seq:0,time:10});
    await eventually(()=>mock.events.length===1);
  }finally{for(const stop of cleanup)await stop();await mock.close();f.clean();}
});

test('multiple next-session instances ignore boot/synthetic input and bind distinct human windows',async()=>{
  const mock=await mockController();const a=fixture(mock.base,{session_scope:'next_session'});const b=fixture(mock.base,{session_scope:'next_session',connection_id:'connection-b',library_id:'library-b'});
  const first=new HostAdapter(a.options);const second=new HostAdapter(b.options);
  const s1={id:'isolated-window-A',header:{}};const s2={id:'isolated-window-B',header:{}};
  const pre=(session,source={kind:'user'})=>({agent:{session},messages:[message('actual-'+session.id,'user','窗口真实发言',source)],turn:1,step:1,signal:new AbortController().signal});
  try{
    const boot=pre(s1,{kind:'startup-notice'});
    await first.beforeStep(boot,async()=>({kind:'enter',messages:boot.messages}));
    assert.equal(mock.contexts.length,0);
    for(const adapter of [first,second])adapter.capture(s1,{type:'turn/start',data:{turn:1},seq:0,time:1});
    const one=pre(s1);await first.beforeStep(one,async()=>({kind:'enter',messages:one.messages}));await second.beforeStep(one,async()=>({kind:'enter',messages:one.messages}));
    for(const adapter of [first,second])adapter.capture(s1,{type:'user/message',data:one.messages[0],seq:1,time:2});
    for(const adapter of [first,second])adapter.capture(s2,{type:'turn/start',data:{turn:1},seq:0,time:1});
    const two=pre(s2);await second.beforeStep(two,async()=>({kind:'enter',messages:two.messages}));
    for(const adapter of [first,second])adapter.capture(s2,{type:'user/message',data:two.messages[0],seq:1,time:2});
    await first.flush();await second.flush();
    assert.ok(mock.events.filter(e=>e.url.includes('connection-a')).every(e=>e.body.session_id==='isolated-window-A'));
    assert.ok(mock.events.filter(e=>e.url.includes('connection-b')).every(e=>e.body.session_id==='isolated-window-B'));
    assert.equal(mock.events.filter(e=>e.url.includes('connection-a')).length,2);assert.equal(mock.events.filter(e=>e.url.includes('connection-b')).length,2);
  }finally{await first.dispose();await second.dispose();await mock.close();a.clean();b.clean();}
});

test('wire-only proxy really forwards provider traffic and archives it without claiming a host turn',async()=>{
  const mock=await mockController();const f=fixture(mock.base);let authorization;
  const upstream=http.createServer(async(req,res)=>{authorization=req.headers.authorization;for await(const part of req){}res.setHeader('content-type','application/json');res.end(JSON.stringify({choices:[{message:{role:'assistant',content:'mock provider response'},finish_reason:'stop'}]}));});
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  const proxy=createProxy({connection_file:f.config,state_dir:join(f.dir,'proxy-outbox'),session_id:'explicit-proxy-session',upstream:`http://127.0.0.1:${upstream.address().port}`,allow_upstream_http:true});
  const port=await proxy.listen();
  try{const response=await fetch(`http://127.0.0.1:${port}/v1/chat/completions`,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer provider-key-not-for-memory'},body:JSON.stringify({model:'mock',messages:[{role:'user',content:'real provider-bound input'}]})});
    assert.equal((await response.json()).choices[0].message.content,'mock provider response');assert.equal(authorization,'Bearer provider-key-not-for-memory');
    await proxy.delivery.flush();assert.equal(mock.events[0].body.event_type,'proxy/completion');assert.equal(mock.events[0].body.record.normalized.status,'partial');
    assert.equal(JSON.stringify(mock.events).includes('provider-key-not-for-memory'),false);
  }finally{await proxy.delivery.dispose();await new Promise(resolve=>proxy.server.close(resolve));await new Promise(resolve=>upstream.close(resolve));await mock.close();f.clean();}
});

test('live private enabled=false stops new capture, context and retry but retains pending files and session claim',async()=>{
  const mock=await mockController({reject:true});const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{turn(adapter);await adapter.flush();const count=readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length;const received=mock.events.length;
    const config=JSON.parse(readFileSync(f.config));config.enabled=false;writeFileSync(f.config,JSON.stringify(config));
    turn(adapter,{start:100});await adapter.flush();assert.equal(mock.events.length,received);assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,count);
    const input=message('paused-input','user','暂停时仍正常聊天');const payload={agent:{session},messages:[input],turn:5,step:1,signal:new AbortController().signal};
    const decision=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[input]}));assert.equal(decision.messages.length,1);assert.equal(mock.contexts.length,0);
    config.enabled=true;writeFileSync(f.config,JSON.stringify(config));assert.equal(adapter.enabled,true);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('real rc3 Cordis and SessionStore publish canonical committed events into the plugin without a model call',async()=>{
  const mock=await mockController();const f=fixture(mock.base);const ctx=new Context();
  const store=ctx.plugin(SessionStore);await store.await();
  const owner=ctx.plugin({name:'isolated-host-contract-fixture',apply(inner){apply(inner,f.options);}});await owner.await();
  try{
    const actual=ctx.sessions.create(SessionId('rc3-real-session-offline'));
    actual.append('turn/start',{turn:1});actual.append('step/start',{turn:1,step:1});
    actual.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:'隔离rc3实际会话服务测试'}]}),{surfaceOp:'append'});
    const text='未调用模型，仅追加公开canonical事件';
    actual.append('assistant/message',{turn:1,step:1,message:createAssistantMessage({source:{provider:'offline-fixture',model:'no-network'},content:[{type:'text',text}]}),stream:[{type:'text-chunks',time0:1800000000000,index:0,dt:[0],texts:[text]}]},{surfaceOp:'append'});
    actual.append('step/end',{turn:1,step:1});actual.append('turn/end',{turn:1,reason:{kind:'completed'}});
    await eventually(()=>mock.events.length===6);
    assert.deepEqual(mock.events.map(x=>x.body.seq),[0,1,2,3,4,5]);assert.equal(mock.events.at(-1).body.record.normalized.status,'complete');
    assert.equal(mock.events.at(-1).body.record.normalized.assistant,text);
  }finally{await owner.dispose();await store.dispose();await mock.close();f.clean();}
});
