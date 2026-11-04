import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { patchOwnedEntry } from '../dist/configure.js';

test('Node installer updates A without deleting independently owned B or unknown config',()=>{
  const a={id:'neural-knowledge-host-a',name:'file:///plugin.js',config:{managed_by:'neural-knowledge-host',library:'a'}};
  const b={id:'neural-knowledge-host-b',name:'file:///plugin.js',config:{managed_by:'neural-knowledge-host',library:'b'}};
  const original='# preserve this comment\n- insert:\n    - id: other\n      name: other-plugin\n      config: {credential: untouched}\n';
  const first=patchOwnedEntry(original,a);const second=patchOwnedEntry(first,b);
  const third=patchOwnedEntry(second,{...a,config:{...a.config,updated:true}});
  assert.match(third,/neural-knowledge-host-a/);assert.match(third,/neural-knowledge-host-b/);
  assert.match(third,/credential: untouched/);assert.match(third,/# preserve this comment/);
  assert.equal(third.match(/id: neural-knowledge-host-a/g).length,1);
});

for (const eol of ['\n','\r\n']) test('Python controller helper preserves '+JSON.stringify(eol)+' and independently owned entries',()=>{
  const dir=mkdtempSync(join(tmpdir(),'neural-config-test-'));const profile=join(dir,'profile');mkdirSync(profile);
  const app=join(dir,'Harness.app');mkdirSync(join(app,'Contents'),{recursive:true});
  writeFileSync(join(app,'Contents/Info.plist'),'<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>0.2.1-rc.3</string></dict></plist>');
  writeFileSync(join(profile,'cordis.yml'),'[]\n');
  const original='# original remains byte-identical\n- insert:\n    - id: other-plugin\n      name: other-plugin\n      config: {password: USER-OPAQUE-FIXTURE}\n- insert:\n    - id: legacy-memory\n      name: "@deepseek-ai/dsh-mcp-client"\n      config:\n        serverName: neural-memory\n        command: /Applications/知识星图.app/Contents/Resources/python/bin/python3.12\n        args: ["/Applications/知识星图.app/Contents/Resources/backend/harness_bridge.py"]\n        env: {API_KEY: OPAQUE-ENV-NOT-RETURNED}\n';
  const originalBytes=original.replaceAll('\n',eol);
  writeFileSync(join(profile,'cordis.patch.yml'),originalBytes);
  const helper=resolve('configure.py');
  const call=(id,apply=true)=>{
    const code=`import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('helper',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\np=json.load(sys.stdin);print(json.dumps(m.configure(p,apply=p.pop('_apply'),app_path=p.pop('_app')),ensure_ascii=False))`;
    const result=spawnSync(process.env.PYTHON??'python3',['-B','-c',code,helper],{input:JSON.stringify({_apply:apply,_app:app,config:{connectionId:id,connectionToken:'fixture-private-token',libraryId:'library-'+id,sessionScope:'next_session'},host_options:{profile_dir:profile}}),encoding:'utf8'});
    assert.equal(result.status,0,result.stderr);assert.equal(result.stdout.includes('fixture-private-token'),false);assert.equal(result.stdout.includes('OPAQUE-ENV-NOT-RETURNED'),false);return JSON.parse(result.stdout);
  };
  try{const plan=call('A',false);assert.equal(plan.supported,true);assert.equal(plan.legacy_manual_entries.length,1);assert.equal(plan.legacy_manual_entries[0].id,'legacy-memory');assert.equal(readFileSync(join(profile,'cordis.patch.yml'),'utf8'),originalBytes);
    const a=call('A');const b=call('B');const again=call('A');const final=readFileSync(join(profile,'cordis.patch.yml'),'utf8');
    assert.ok(final.startsWith(originalBytes));assert.ok(final.includes(JSON.stringify(a.connection_file)));assert.ok(final.includes(JSON.stringify(b.connection_file)));
    assert.equal(final.match(/# BEGIN NEURAL-KNOWLEDGE-HOST-/g).length,2);
    assert.equal(JSON.parse(readFileSync(a.connection_file,'utf8')).session_scope,'next_session');
    if(process.platform!=='win32')assert.equal(statSync(a.connection_file).mode&0o777,0o600);assert.ok(again.backup);
    assert.equal(readFileSync(a.backup,'utf8'),originalBytes);
    assert.equal(JSON.parse(readFileSync(join(profile,'.neural-knowledge/package.json'),'utf8')).type,'module');
    assert.ok(readFileSync(join(profile,'.neural-knowledge/configure.js'),'utf8').includes(readFileSync('licenses/yaml-ISC.txt','utf8')),'installed configure bundle must retain complete yaml license');
    const stop=`import importlib.util,json,sys\ns=importlib.util.spec_from_file_location('helper',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\np=json.load(sys.stdin);print(json.dumps(m.set_enabled(p,False,remove=True,app_path=sys.argv[2])))`;
    const paused=spawnSync(process.env.PYTHON??'python3',['-B','-c',stop,helper,app],{input:JSON.stringify({config:{connectionId:'A',connectionToken:'fixture-private-token',libraryId:'library-A'},host_options:{profile_dir:profile}}),encoding:'utf8'});
    assert.equal(paused.status,0,paused.stderr);assert.equal(JSON.parse(paused.stdout).managed_entry_removed,true);
    const afterRemoval=readFileSync(join(profile,'cordis.patch.yml'),'utf8');assert.ok(afterRemoval.startsWith(originalBytes));assert.ok(afterRemoval.includes(JSON.stringify(b.connection_file)));assert.equal(afterRemoval.includes(JSON.stringify(a.connection_file)),false);
    assert.equal(JSON.parse(readFileSync(a.connection_file,'utf8')).enabled,false);assert.equal(JSON.parse(readFileSync(b.connection_file,'utf8')).enabled,true);
  }finally{rmSync(dir,{recursive:true,force:true});}
});
