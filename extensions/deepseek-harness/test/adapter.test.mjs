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

const hostVersion = process.env.LOVE_HOUSE_HARNESS_TEST_VERSION || '0.2.1-rc.3';
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function eventually(check) { for (let i=0;i<80;i++) { if(check())return; await sleep(25); } assert.ok(check(), 'condition not reached'); }
async function mockController({reject=false,eventDelay=0}={}) {
  const events=[]; const contexts=[]; const server=http.createServer(async(req,res)=>{
    let raw='';for await(const part of req)raw+=part;
    const body=raw?JSON.parse(raw):null;
    res.setHeader('content-type','application/json');
    if(req.url==='/api/health')return res.end('{"ok":true,"version":"0.4.0"}');
    if(!req.headers.authorization?.startsWith('Bearer fixture-')){res.statusCode=401;return res.end('{}');}
    if(req.url.endsWith('/heartbeat'))return res.end('{"host_online":true}');
    if(req.url.endsWith('/context')){contexts.push({url:req.url,body});return res.end(JSON.stringify({packet:'已选库的真实人格和记忆材料',memory_ids:['memory-1']}));}
    events.push({url:req.url,body});if(eventDelay)await sleep(eventDelay);res.end(JSON.stringify({accepted:!reject,status:'pending'}));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {events,contexts,server,base:`http://127.0.0.1:${server.address().port}`,close:()=>new Promise(resolve=>server.close(resolve))};
}
function fixture(base, extra={}) {
  const dir=mkdtempSync(join(tmpdir(),'neural-host-test-'));const config=join(dir,'connection.json');
  writeFileSync(config,JSON.stringify({connection_id:'connection-a',connection_token:'fixture-secret-not-a-real-token',library_id:'library-a',base_url:base,...extra}));
  const options={connection_file:config,host_version:hostVersion,state_dir:join(dir,'outbox'),retry_ms:20,timeout_ms:300};
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

test('real supported Cordis and SessionStore publish canonical committed events into the plugin without a model call',async()=>{
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

test('MCP connection installs Harness capture without claiming or persisting incomplete candidate windows',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{connection_id:'agent-complete-binding',connection_host:'agent',session_scope:'next_session'});
  const adapter=new HostAdapter(f.options);const candidate={id:'agent-candidate',header:{}};
  const original=message('pending-user','user','候选窗口在完整结束前不能落盘');
  try{
    const payload={agent:{session:candidate},messages:[original],turn:1,step:1,signal:new AbortController().signal};
    const recalled=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[original]}));
    assert.equal(recalled.messages.length,2);assert.equal(mock.contexts.length,1);
    adapter.capture(candidate,{type:'turn/start',data:{turn:1},seq:0,time:1});
    adapter.capture(candidate,{type:'user/message',data:original,seq:1,time:2});
    await adapter.flush();assert.equal(mock.events.length,0);
    assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,0);
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,undefined);
    adapter.capture(candidate,{type:'turn/end',data:{turn:1,reason:{kind:'aborted'}},seq:2,time:3});
    await adapter.flush();assert.equal(mock.events.length,0);
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,undefined);
    turn(adapter,{start:20});await adapter.flush();
    assert.equal(mock.events.length,1);const first=mock.events[0].body;
    assert.equal(first.event_type,'turn/end');assert.equal(first.record.normalized.status,'complete');
    assert.equal(first.record.raw_events.length,6);assert.equal(first.record.raw_events[3].type,'tool/result');
    assert.ok(!JSON.stringify(first).includes('must-not-leak'));
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,session.id);
    adapter.capture(candidate,{type:'user/message',data:original,seq:3,time:4});await adapter.flush();
    assert.equal(mock.events.length,1);assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,0);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('Agent Harness mode uses real supported committed events and its first complete turn survives reconnect',async()=>{
  const mock=await mockController({reject:true});const f=fixture(mock.base,{connection_id:'agent-rc3-binding',connection_host:'agent',session_scope:'next_session'});
  const ctx=new Context();const store=ctx.plugin(SessionStore);await store.await();
  const owner=ctx.plugin({name:'isolated-agent-host-fixture',apply(inner){apply(inner,f.options);}});await owner.await();
  try{
    const actual=ctx.sessions.create(SessionId('agent-rc3-real-session'));
    actual.append('turn/start',{turn:1});
    actual.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:'这轮必须由宿主事件自动上报'}]}),{surfaceOp:'append'});
    await sleep(30);assert.equal(mock.events.length,0);
    const text='完整真实回复无需memory_record_turn调用';
    actual.append('assistant/message',{turn:1,step:1,message:createAssistantMessage({source:{provider:'offline-fixture',model:'no-network'},content:[{type:'text',text}]}),stream:[]},{surfaceOp:'append'});
    actual.append('turn/end',{turn:1,reason:{kind:'completed'}});
    await eventually(()=>mock.events.length>0);
    assert.ok(mock.events.every(e=>e.body.event_type==='turn/end'));
    await owner.dispose();await store.dispose();await mock.close();
    const recovered=await mockController();const cfg=JSON.parse(readFileSync(f.config));cfg.base_url=recovered.base;writeFileSync(f.config,JSON.stringify(cfg));
    const restarted=new HostAdapter(f.options);
    try{await restarted.flush();assert.equal(recovered.events.length,1);assert.equal(recovered.events[0].body.record.normalized.assistant,text);
      assert.equal(readdirSync(restarted.stateDir).filter(p=>p.endsWith('.event.json')).length,0);
    }finally{await restarted.dispose();await recovered.close();}
  }finally{await owner.dispose();await store.dispose();if(mock.server.listening)await mock.close();f.clean();}
});


test('shutdown drains events queued after the in-flight snapshot before aborting the controller',async()=>{
  const mock=await mockController({eventDelay:30});const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{
    adapter.capture(session,{type:'turn/start',data:{turn:1},seq:0,time:1});
    await eventually(()=>mock.events.length===1);
    adapter.capture(session,{type:'user/message',data:message('shutdown-user','user','退出前必须自动保存原话'),seq:1,time:2});
    adapter.capture(session,{type:'assistant/message',data:{turn:1,message:message('shutdown-assistant','assistant','退出前的完整回复')},seq:2,time:3});
    adapter.capture(session,{type:'turn/end',data:{turn:1,reason:{kind:'completed'}},seq:3,time:4});
    await Promise.all([adapter.dispose(),adapter.dispose()]);
    assert.equal(mock.events.length,4);assert.equal(mock.events.at(-1).body.record.normalized.status,'complete');
    assert.equal(mock.events.at(-1).body.record.normalized.assistant,'退出前的完整回复');
    assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,0);
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'status.json'))).last_error,null);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('shutdown retains rejected records and never starts new capture while draining',async()=>{
  const mock=await mockController({reject:true,eventDelay:20});const f=fixture(mock.base);const adapter=new HostAdapter(f.options);
  try{
    turn(adapter);const closing=adapter.dispose();turn(adapter,{start:100});await closing;
    assert.equal(readdirSync(adapter.stateDir).filter(p=>p.endsWith('.event.json')).length,6);
    assert.ok(mock.events.length<=1);assert.ok(mock.events.every(e=>e.body.seq<100));
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('fixed root window waits for completed turn/end and stores only the last committed visible assistant output',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{session_scope:session.id});const adapter=new HostAdapter(f.options);
  let seq=200;const emit=(type,data)=>adapter.capture(session,{type,data,seq:seq++,time:1800000000000+seq});
  try{
    emit('turn/start',{turn:8});
    emit('assistant/message',{turn:8,step:1,message:message('middle-message','assistant','准备检查，然后继续处理。')});
    emit('assistant/attempt',{turn:8,step:2,stream:[]});
    emit('assistant/message',{turn:8,step:3,message:message('final-output-id','assistant','我已检查公开页面，确认标题仍然可见。')});
    await adapter.flush();
    assert.equal(mock.events.filter(e=>e.body.record.normalized?.type==='output').length,0);
    emit('turn/end',{turn:8,reason:{kind:'completed'}});
    await adapter.flush();
    const outputs=mock.events.filter(e=>e.body.record.normalized?.type==='output');
    assert.equal(outputs.length,1);
    const normalized=outputs[0].body.record.normalized;
    assert.equal(outputs[0].body.event_type,'turn/end');
    assert.equal(normalized.status,'complete');assert.equal(normalized.role,'assistant');
    assert.equal(normalized.text,'我已检查公开页面，确认标题仍然可见。');
    assert.equal(normalized.evidence.assistant_message_id,'final-output-id');
    assert.equal('user' in normalized,false);assert.equal('assistant' in normalized,false);assert.equal('messages' in normalized,false);
    assert.equal(JSON.stringify(normalized).includes('准备检查'),false);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('new independent output path never double-records a normal user turn',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{session_scope:session.id});const adapter=new HostAdapter(f.options);
  try{turn(adapter);await adapter.flush();
    assert.equal(mock.events.filter(e=>e.body.record.normalized?.type==='output').length,0);
    assert.equal(mock.events.filter(e=>e.body.record.normalized?.type==='turn'&&e.body.record.normalized.status==='complete').length,1);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('output cannot claim next_session but works after a real human bound the same root window',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{session_scope:'next_session'});const adapter=new HostAdapter(f.options);
  const root={id:'output-cannot-claim-root',header:{}};
  const emit=(type,data,seq)=>adapter.capture(root,{type,data,seq,time:1800000000000+seq});
  try{
    emit('turn/start',{turn:1},0);
    emit('assistant/message',{turn:1,step:1,message:message('unclaimed-output','assistant','不能自行绑定这个窗口。')},1);
    emit('turn/end',{turn:1,reason:{kind:'completed'}},2);
    await adapter.flush();assert.equal(mock.events.length,0);
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,undefined);
    emit('turn/start',{turn:2},10);
    emit('user/message',message('claim-human','user','这才是首次真实用户发言。'),11);
    emit('assistant/message',{turn:2,step:1,message:message('claim-reply','assistant','收到。')},12);
    emit('turn/end',{turn:2,reason:{kind:'completed'}},13);
    emit('turn/start',{turn:3},20);
    emit('assistant/message',{turn:3,step:1,message:message('bound-independent-output','assistant','在同一已绑定窗口内完成独立工作。')},21);
    emit('turn/end',{turn:3,reason:{kind:'completed'}},22);
    await adapter.flush();
    assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,root.id);
    const outputs=mock.events.filter(e=>e.body.record.normalized?.type==='output');
    assert.equal(outputs.length,1);assert.equal(outputs[0].body.record.normalized.evidence.assistant_message_id,'bound-independent-output');
    assert.ok(mock.events.every(e=>e.body.session_id===root.id&&e.body.seq>=10));
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('errors, aborts, missing starts, mismatched turn IDs, empty text and tool-call messages never become independent complete output',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{session_scope:session.id});const adapter=new HostAdapter(f.options);
  let seq=300;
  try{
    const scenarios=[{reason:'error'},{reason:'aborted'},{reason:'blocked'},{interrupted:true},{start:false},{endTurn:999},{assistantTurn:999},{text:''},
      {tailAttempt:true},{tailTool:true},{nextStep:true},
      {content:[{type:'text',text:'这是工具中间步骤。'},{type:'tool-call',id:'call-x',name:'ignored',arguments:'{}'}]}];
    for(let i=0;i<scenarios.length;i++){
      const opts=scenarios[i],number=i+20;
      const emit=(type,data)=>adapter.capture(session,{type,data,seq:seq++,time:1800000000000+seq});
      if(opts.start!==false)emit('turn/start',{turn:number});
      const final=message('not-final-'+number,'assistant',opts.text??'未完成的可见文字');
      if(opts.content)final.content=opts.content;
      emit('assistant/message',{turn:opts.assistantTurn??number,step:1,message:final,interrupted:opts.interrupted});
      if(opts.tailAttempt)emit('assistant/attempt',{turn:number,step:2,stream:[]});
      if(opts.tailTool)emit('tool/call',{turn:number,step:1,callId:'later-tool',name:'ignored',arguments:'{}'});
      if(opts.nextStep)emit('step/start',{turn:number,step:2});
      emit('turn/end',{turn:opts.endTurn??number,reason:{kind:opts.reason??'completed'}});
    }
    await adapter.flush();assert.equal(mock.events.filter(e=>e.body.record.normalized?.type==='output').length,0);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('other windows and subagents are not captured or supplied with this root memory',async()=>{
  const mock=await mockController();const f=fixture(mock.base,{session_scope:session.id});const adapter=new HostAdapter(f.options);
  try{
    for(const target of [{id:'another-root-window',header:{}},{id:'child-window',header:{origin:'subagent'}},{id:session.id,header:{origin:'subagent'}}]){
      adapter.capture(target,{type:'turn/start',data:{turn:1},seq:0,time:1});
      adapter.capture(target,{type:'assistant/message',data:{turn:1,step:1,message:message('other-output','assistant','不属于当前鱼窗口')},seq:1,time:2});
      adapter.capture(target,{type:'turn/end',data:{turn:1,reason:{kind:'completed'}},seq:2,time:3});
      const original=message('child-human','user','不能让子代理读取此库');
      const payload={agent:{session:target},messages:[original],turn:1,step:1,signal:new AbortController().signal};
      const result=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[original]}));
      assert.equal(result.messages.length,1);
    }
    await adapter.flush();assert.equal(mock.events.length,0);assert.equal(mock.contexts.length,0);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});

test('independent root output survives durable retry without changing identity or becoming a user turn',async()=>{
  const mock=await mockController({reject:true});const f=fixture(mock.base,{session_scope:session.id});let adapter=new HostAdapter(f.options);
  try{
    adapter.capture(session,{type:'turn/start',data:{turn:90},seq:900,time:1});
    adapter.capture(session,{type:'assistant/message',data:{turn:90,step:1,message:message('retry-output','assistant','可补交的独立输出。')},seq:901,time:2});
    adapter.capture(session,{type:'turn/end',data:{turn:90,reason:{kind:'completed'}},seq:902,time:3});
    const pending=readdirSync(adapter.stateDir).filter(name=>name.endsWith('.event.json')).map(name=>JSON.parse(readFileSync(join(adapter.stateDir,name))));
    const output=pending.find(e=>e.record.normalized?.type==='output');assert.ok(output);
    await adapter.flush();await adapter.dispose();await mock.close();
    const recovered=await mockController();const cfg=JSON.parse(readFileSync(f.config));cfg.base_url=recovered.base;writeFileSync(f.config,JSON.stringify(cfg));
    adapter=new HostAdapter(f.options);await adapter.flush();
    const replay=recovered.events.filter(e=>e.body.record.normalized?.type==='output');
    assert.equal(replay.length,1);assert.equal(replay[0].body.event_id,output.event_id);assert.equal(replay[0].body.record.normalized.role,'assistant');
    assert.equal('user' in replay[0].body.record.normalized,false);await recovered.close();
  }finally{await adapter.dispose();f.clean();}
});

test('official rc3 SessionStore commits a no-user final output only at completed turn/end',async()=>{
  const mock=await mockController();const sid='rc3-independent-root-offline';const f=fixture(mock.base,{session_scope:sid});const ctx=new Context();
  const store=ctx.plugin(SessionStore);await store.await();
  const owner=ctx.plugin({name:'isolated-output-contract-fixture',apply(inner){apply(inner,f.options);}});await owner.await();
  try{
    const actual=ctx.sessions.create(SessionId(sid));actual.append('turn/start',{turn:1});actual.append('step/start',{turn:1,step:1});
    const text='由真实SessionStore提交的最终独立助手文字，没有模型调用。';
    actual.append('assistant/message',{turn:1,step:1,message:createAssistantMessage({source:{provider:'offline-fixture',model:'no-network'},content:[{type:'text',text}]}),stream:[{type:'text-chunks',time0:1800000000000,index:0,dt:[0],texts:[text]}]},{surfaceOp:'append'});
    actual.append('step/end',{turn:1,step:1});actual.append('turn/end',{turn:1,reason:{kind:'completed'}});
    await eventually(()=>mock.events.length===5);
    assert.equal(mock.events.filter(e=>e.body.record.normalized?.type==='output').length,1);
    assert.deepEqual(mock.events.at(-1).body.record.normalized.text,text);
    assert.equal(mock.events.at(-1).body.record.normalized.role,'assistant');
    assert.equal(mock.events.slice(0,-1).some(e=>e.body.record.normalized?.type==='output'),false);
  }finally{await owner.dispose();await store.dispose();await mock.close();f.clean();}
});

for(const scope of ['fixed','next_session'])test(`real rc3 SessionStore supplies its latest public human task before no-human work (${scope})`,async()=>{
  const mock=await mockController();const sid='rc3-no-human-recall-'+scope;
  const f=fixture(mock.base,{session_scope:scope==='fixed'?sid:'next_session'});const ctx=new Context();
  const store=ctx.plugin(SessionStore);await store.await();let preStep;
  const owner=ctx.plugin({name:'isolated-before-work-'+scope,apply(inner){
    apply({logger:inner.logger,on(name,handler){if(name==='agent/pre-step')preStep=handler;return inner.on(name,handler);},effect:inner.effect.bind(inner)},f.options);
  }});await owner.await();
  try{
    const actual=ctx.sessions.create(SessionId(sid));
    actual.append('turn/start',{turn:1});actual.append('step/start',{turn:1,step:1});
    actual.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:'更早的任务不应代替最近任务。'}]}),{surfaceOp:'append'});
    const task='下一次继续检查公开示例网页是否仍然可访问。';
    actual.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:task}]}),{surfaceOp:'append'});
    const first='助手旧回复不能当成用户任务或私有目标。';
    actual.append('assistant/message',{turn:1,step:1,message:createAssistantMessage({source:{provider:'offline-fixture',model:'no-network'},content:[{type:'text',text:first}]}),stream:[{type:'text-chunks',time0:1800000000000,index:0,dt:[0],texts:[first]}]},{surfaceOp:'append'});
    actual.append('step/end',{turn:1,step:1});actual.append('turn/end',{turn:1,reason:{kind:'completed'}});
    // A fresh turn has no new human input. Read only this exact Session's
    // committed public surface through its real deriveMessages() API.
    actual.append('turn/start',{turn:2});
    const payload={agent:{session:actual},messages:[],turn:2,step:1,signal:new AbortController().signal};
    const result=await preStep(payload,async()=>({kind:'enter',messages:[],startsRequestSeries:true}));
    assert.equal(mock.contexts.length,1);assert.deepEqual(mock.contexts[0].body,{session_id:sid,query:task});
    assert.equal(result.messages.length,1);assert.equal(result.messages[0].source.kind,SOURCE_KIND);
    assert.ok(result.messages[0].content[0].text.includes('已选库的真实人格和记忆材料'));assert.equal(result.startsRequestSeries,true);
    const again=await preStep(payload,async()=>({kind:'enter',messages:[]}));
    assert.equal(mock.contexts.length,1);assert.equal(again.messages.length,0);
    // Publishing our recall contribution must not create a fake human message.
    actual.append('user/message',result.messages[0],{surfaceOp:'append'});
    actual.append('step/start',{turn:2,step:1});
    const final='自动工作完成后只归档本轮助手输出。';
    actual.append('assistant/message',{turn:2,step:1,message:createAssistantMessage({source:{provider:'offline-fixture',model:'no-network'},content:[{type:'text',text:final}]}),stream:[{type:'text-chunks',time0:1800000000001,index:0,dt:[0],texts:[final]}]},{surfaceOp:'append'});
    actual.append('step/end',{turn:2,step:1});actual.append('turn/end',{turn:2,reason:{kind:'completed'}});
    await eventually(()=>mock.events.some(e=>e.body.record.normalized?.type==='output'));
    const output=mock.events.find(e=>e.body.record.normalized?.type==='output').body.record.normalized;
    assert.equal(output.role,'assistant');assert.equal(output.text,final);assert.equal('user' in output,false);
    assert.equal(mock.events.filter(e=>e.body.event_type==='user/message').length,2);
    assert.ok(mock.events.every(e=>e.body.session_id===sid));
  }finally{await owner.dispose();await store.dispose();await mock.close();f.clean();}
});

test('fixed root with a real empty public SessionStore uses only a fixed baseline query',async()=>{
  const mock=await mockController();const sid='rc3-empty-root-baseline';const f=fixture(mock.base,{session_scope:sid});const ctx=new Context();
  const store=ctx.plugin(SessionStore);await store.await();const actual=ctx.sessions.create(SessionId(sid));const adapter=new HostAdapter(f.options);
  const stop=ctx.on('session/event',(session,event)=>adapter.capture(session,event));
  try{
    actual.append('turn/start',{turn:1});
    const payload={agent:{session:actual},messages:[],turn:1,step:1,signal:new AbortController().signal};
    const result=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[]}));
    assert.equal(mock.contexts.length,1);assert.equal(mock.contexts[0].body.query,'当前已绑定存档的长期基线和约定');
    assert.equal(result.messages[0].source.kind,SOURCE_KIND);
    await adapter.flush();assert.equal(mock.events.some(e=>e.body.event_type==='user/message'),false);
  }finally{stop();await adapter.dispose();await store.dispose();await mock.close();f.clean();}
});

test('no-human recall never reads an unbound, different, broad, child, missing-start or interrupted public session',async()=>{
  const mock=await mockController();const setups=[
    {scope:'next_session',id:'unbound-task'},
    {scope:'fixed-task',id:'another-task'},
    {scope:'connection',id:'broad-task'},
    {scope:'child-task',id:'child-task',origin:'subagent'},
    {scope:'missing-start-task',id:'missing-start-task',noStart:true},
    {scope:'interrupted-task',id:'interrupted-task',interrupted:true},
  ];
  try{for(const setup of setups){
    const f=fixture(mock.base,{session_scope:setup.scope});const adapter=new HostAdapter(f.options);let reads=0;
    const target={id:setup.id,header:{origin:setup.origin},deriveMessages(){reads++;throw new Error('Must not read this session');}};
    try{
      if(!setup.noStart)adapter.capture(target,{type:'turn/start',data:{turn:1},seq:0,time:1});
      if(setup.interrupted)adapter.capture(target,{type:'assistant/message',data:{turn:1,step:1,interrupted:true,message:message('stopped','assistant','中断')},seq:1,time:2});
      const payload={agent:{session:target},messages:[],turn:1,step:1,signal:new AbortController().signal};
      const result=await adapter.beforeStep(payload,async()=>({kind:'enter',messages:[]}));
      assert.equal(result.messages.length,0);assert.equal(reads,0);
      if(setup.scope==='next_session')assert.equal(JSON.parse(readFileSync(join(adapter.stateDir,'identity.json'))).bound_session,undefined);
    }finally{await adapter.dispose();f.clean();}
  }assert.equal(mock.contexts.length,0);}finally{await mock.close();}
});

test('unavailable or failed public Session projection does not guess a task or block the host',async()=>{
  const mock=await mockController();const sid='failed-public-task';const f=fixture(mock.base,{session_scope:sid});const warnings=[];const adapter=new HostAdapter(f.options,message=>warnings.push(message));
  try{
    for(const deriveMessages of [undefined,()=>{throw new Error('PRIVATE_PROJECTION_DETAIL_MUST_NOT_LEAK');}]){
      const target={id:sid,header:{},...(deriveMessages?{deriveMessages}:{})};
      adapter.capture(target,{type:'turn/start',data:{turn:1},seq:0,time:1});
      const original={kind:'enter',messages:[]};
      const result=await adapter.beforeStep({agent:{session:target},messages:[],turn:1,step:1,signal:new AbortController().signal},async()=>original);
      assert.equal(result,original);
    }
    assert.equal(mock.contexts.length,0);assert.equal(JSON.stringify(warnings).includes('PRIVATE_PROJECTION_DETAIL'),false);
  }finally{await adapter.dispose();await mock.close();f.clean();}
});
