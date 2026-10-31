"""Product controller: isolated graph servers, immutable connections, durable event delivery."""
from __future__ import annotations
import copy
import hashlib
import json
import threading
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from ..libraries import LibraryManager
from ..libraries.manager import LibraryError
from ..adapters.http import make_handler, RequestError
from ..errors import ValidationError
from .._version import __version__
from .connections import ConnectionStore
from .credentials import KeyStore,KeyStoreError
from .providers import ProviderStore


def local_json(port,path,body=None,timeout=20):
    headers={'Content-Type':'application/json'}
    req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',
       data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=timeout) as response:
        return json.load(response)

def harness_resources():
    source=Path(__file__).resolve().parents[2]/'extensions/deepseek-harness'
    return source if (source/'configure.py').is_file() else Path(__file__).resolve().parent/'harness'

class MemoryHost:
    def __init__(self,root,*,with_demo=False,adapter_options=None,key_store=None,organizer_transport=None):
        self.root=Path(root).expanduser().resolve()
        self.instance_id=uuid.uuid4().hex
        self.manager=LibraryManager(self.root)
        self.adapter_options=dict(adapter_options or {})
        if with_demo and not self.manager.demo_suppressed:
            path=self.root/'framework-example.brain.json'
            if path.exists():self.manager.register_demo(path)
        self.connections=ConnectionStore(self.root)
        from .agent_sources import AgentSourceRegistry
        self.sources=AgentSourceRegistry(self.root,self.connections)
        from .usage import UsageJournal
        try:self.usage=UsageJournal(self.root)
        except Exception:self.usage=None  # Auxiliary metadata must not block raw archives.
        self._usage_enabled={}
        # A heartbeat belongs to this running controller, not the previous boot.
        with self.connections.db() as db:db.execute("UPDATE connections SET host_seen=NULL WHERE host IN ('harness','agent')")
        self.keys=key_store or KeyStore()
        self.providers=ProviderStore(self.connections,self.keys)
        self._lock=threading.RLock();self._apply_lock=threading.Lock();self._servers={};self._threads=[];self._closing_libraries=set()
        self.stopping=threading.Event();self.controller_port=None
        from ..organizer import Organizer,apply_plan
        self.organizer=Organizer(self.root,snapshot=self.snapshot,
             apply=lambda lib,plan:self.transact(lib,lambda brain:apply_plan(brain,plan,lib)),
             credential=self.organizer_credential,transport=organizer_transport,read_archive=self.read_archive)
        from .backups import BackupStore
        self.backups=BackupStore(self)
        from .sharing import ShareStore
        from .share_summary import ReadingSummaryService
        self.sharing=ShareStore(self)
        self.share_summaries=ReadingSummaryService(self)
        from .updates import UpdateChecker
        self.updates=UpdateChecker(self.root)
        self.worker=threading.Thread(target=self._retry,daemon=True);self.worker.start()
        self.organizer.start()
    def port_for(self,library_id):
        self.library(library_id)
        with self._lock:
            if library_id not in self._servers:
                brain=self.manager.open_library(library_id)
                if not brain.meta.get("demo"):
                    from ..companion.retention import enable_temporal_retention
                    from ..core.transaction import rollback_guard
                    with rollback_guard(brain) as guard:
                        migrated=enable_temporal_retention(brain)
                        if migrated['changed']:guard.persist()
                    self._usage_enabled[library_id]=migrated['usage_reinforcement']
                server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(brain))
                thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.1},daemon=True)
                server.daemon_threads=False;thread.start();self._servers[library_id]=server;self._threads.append(thread)
            return self._servers[library_id].server_port
    def snapshot(self,library_id):
        self.port_for(library_id)
        return self._servers[library_id].RequestHandlerClass.memory_snapshot()
    def transact(self,library_id,callback):
        if self.library(library_id)['is_demo']:raise ValidationError('示例库不能修改')
        self.port_for(library_id)
        try:pending=self.usage.pending(library_id) if self.usage else []
        except Exception:pending=[]
        def apply(brain):
            from ..companion.retention import enable_temporal_retention
            enable_temporal_retention(brain)
            result=callback(brain)
            enable_temporal_retention(brain)
            if pending:
                from ..companion.retention import record_memory_use
                for item in pending:
                    record_memory_use(brain,[item['node_id']],kind=item['kind'],now=item['at'])
            return result
        result=self._servers[library_id].RequestHandlerClass.memory_transaction(apply)
        # The graph has committed. Failure of auxiliary metadata acknowledgement
        # leaves an idempotent pending use; never report the saved body as lost.
        if pending:
            try:self.usage.applied(pending)
            except Exception:pass
        return result
    def retention_view(self,library_id):
        from ..core.brain import Brain
        from ..companion.retention import get_retention_policy
        from collections import Counter
        meta=self.library(library_id);brain=Brain(self.snapshot(library_id));stamp=time.time()
        states=Counter(brain._node_state(node,stamp)['state'] for node in brain.nodes.values())
        try:usage={**self.usage.counts(library_id),'available':True} if self.usage else {'pending':0,'available':False}
        except Exception:usage={'pending':0,'available':False}
        path=self.manager.path_for(library_id)
        try:size=path.stat().st_size
        except OSError:size=None
        policy=get_retention_policy(brain)
        return {**policy,'settings':{k:policy[k] for k in ('mode','forgetting_pace','usage_reinforcement')},
                'node_count':len(brain.nodes),'states':dict(states),'usage':usage,'is_demo':meta['is_demo'],
                'storage':{'engine':'json','bytes':size},'will_call_model':False,
                'library_id':library_id,'library_name':meta['name'],
                'model_note':'借鉴频率、最近性与间隔效应的工程近似，不设统一到期日，不是经人类数据标定的遗忘概率。'}
    def retention_settings(self,library_id,data):
        from ..companion.retention import save_retention_policy
        self.port_for(library_id)
        previous=self._usage_enabled.get(library_id,False)
        self._usage_enabled[library_id]=False
        try:
            saved=self.transact(library_id,lambda brain:save_retention_policy(brain,data))
        except Exception:
            self._usage_enabled[library_id]=previous
            raise
        self._usage_enabled[library_id]=saved['usage_reinforcement']
        return self.retention_view(library_id)
    def queue_memory_use(self,library_id,ids,kind='recall'):
        if not ids or self.usage is None or not self._usage_enabled.get(library_id,False):return
        try:
            for offset in range(0,len(ids),1000):self.usage.enqueue(library_id,ids[offset:offset+1000],kind)
        except Exception:pass  # Optional use metadata must not interrupt raw capture.
    def agent_sources_view(self,library_id):
        meta=self.library(library_id)
        registered=self.sources.list(library_id)
        known={s['connection_id'] for s in registered}
        legacy=[{k:c.get(k) for k in ('id','name','host','enabled','revoked','archive_status','capture')}
                for c in self.connections.list(library_id) if c['id'] not in known]
        return {'agent_id':library_id,'library_id':library_id,'library_name':meta['name'],
                'is_demo':meta['is_demo'],'sources':registered,'legacy_connections':legacy,
                'read_only':True,'full_activity_coverage_verified':False,'model_api_key_required':False}
    def connections_view(self):
        items=[]
        for connection in self.connections.list():
            source=self.sources.for_connection(connection['id'])
            registered=({k:source[k] for k in ('id','adapter','library_id','runtime_agent_id')}
                        if source and source['library_id']==connection['library_id'] else None)
            items.append({**connection,'registered_source':registered,
                          'provider':self.providers.public(connection['id']) if connection['host']=='api' else None})
        return {'connections':items}
    def register_agent_source(self,library_id,data):
        if self.library(library_id)['is_demo']:raise ValidationError('示例不能绑定实际活动来源')
        if not self.controller_port:raise ValidationError('请先启动本机记忆服务')
        return self.sources.register(library_id,data,base_url=f'http://127.0.0.1:{self.controller_port}')
    def agent_source_action(self,library_id,source_id,action,data=None):
        source=self.sources.get(source_id)
        if source['library_id']!=library_id:raise ValidationError('活动来源不属于当前 Agent')
        if action=='config':
            if data not in (None,{}):raise ValidationError('来源配置只接受空请求，不能选择其他身份或地址')
            return self.sources.configuration(source_id,base_url=f'http://127.0.0.1:{self.controller_port}')
        if self.library(library_id)['is_demo']:raise ValidationError('示例不能修改活动来源')
        data=data or {}
        if set(data)-{'enabled','confirm'}:raise ValidationError('来源设置含未声明字段')
        if action=='disconnect' and data.get('confirm') is not True:raise ValidationError('请确认断开该活动来源')
        return {'source':self.sources.set_enabled(source_id,data.get('enabled',False),disconnect=action=='disconnect')}
    def experiences_view(self,library_id,*,limit=30):
        from ..core.brain import Brain
        from ..organizer.experiences import project_experience,render_experience
        if type(limit) is not int or not 1<=limit<=100:raise ValidationError('一次展示1至100条经历')
        brain=Brain(self.snapshot(library_id));entries=[];invalid=0;cache={}
        def archive(rid):
            if rid not in cache:
                try:cache[rid]=self.connections.read_archive(rid,library_id).get('record')
                except ValidationError:cache[rid]=None
            return cache[rid]
        for node in sorted(brain.nodes.values(),key=lambda n:(n.get('event_at') or n.get('created') or 0,n['id']),reverse=True):
            if not isinstance(node.get('meta',{}).get('experience'),dict):continue
            episode=project_experience(brain,node,library_id,read_archive=archive)
            if episode is None:invalid+=1;continue
            refs=[episode.get(k) for k in ('what','reason','outcome')]+episode.get('participants',[])+episode.get('places',[])
            platforms=set()
            for ref in refs:
                source=brain.get(ref.get('id')) if isinstance(ref,dict) else None
                ev=(source or {}).get('meta',{}).get('evidence') or {}
                if isinstance(ev,dict) and isinstance(ev.get('platform'),str):platforms.add(ev['platform'])
            entries.append({'id':node['id'],'label':str(episode.get('what',{}).get('quote','一次经历')).splitlines()[0][:100],'event_at':episode.get('event_at'),
                            'recorded_at':node.get('created'),'display':render_experience(episode),'episode':episode,'platforms':sorted(platforms)})
        raw=sum(n.get('meta',{}).get('source') in ('conversation_turn','tool_observation','agent_output','history_import') for n in brain.nodes.values())
        return {'agent_id':library_id,'entries':entries[:limit],'total':len(entries),'more':len(entries)>limit,
                'source_records':raw,'unavailable_experiences':invalid,'read_only':True,'will_call_model':False,
                'note':'经历按来源整理；原因和结果缺少证据时保持未知，工具记录只作依据。'}
    def astrbot_package(self):
        import importlib.util
        path=Path(__file__).resolve().parents[2]/'extensions/astrbot-love-house/package.py'
        if not path.is_file():raise ValidationError('这个安装包未包含 AstrBot 实验适配器，请从项目获取完整版本')
        spec=importlib.util.spec_from_file_location('_love_house_astrbot_package',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.package_bytes(strict_sdk=True)
    def read_archive(self,library_id,receipt_id):
        tomb=self.snapshot(library_id).get('meta',{}).get('memory_tombstones',{})
        if receipt_id in tomb.get('raw_ids',[]):return None
        try:return self.connections.read_archive(receipt_id,library_id)
        except ValidationError:return None
    def organizer_ref(self,library_id,base_url,session_only=False):
        from .providers import endpoint
        return {'provider':'organizer:'+hashlib.sha256(endpoint(base_url).encode()).hexdigest()+(':session' if session_only else ''),'library_id':library_id,'connection_id':None}
    def organizer_credential(self,library_id,profile):
        provider=profile.get('provider_id','')
        if provider.startswith('connection:'):
            cid=provider.split(':',1)[1];c=self.connections.get(cid)
            if c['library_id']!=library_id or c['revoked']:raise ValidationError('整理连接不属于当前库或已断开')
            return self.providers.credential(cid)
        if not profile.get('base_url'):return ''
        return {'api_key':self.keys.get(self.organizer_ref(library_id,profile['base_url'],provider=='separate:session')),
                'base_url':profile['base_url'],'model':profile['model']}
    def organizer_view(self,library_id):
        from ..core.brain import Brain
        from ..organizer import get_profile
        raw=self.snapshot(library_id);settings=get_profile(Brain(raw));pid=settings['provider_id']
        cid=pid.split(':',1)[1] if pid.startswith('connection:') else ''
        provider={'base_url':settings['base_url'],'model':settings['model'],'storage':'none','key_saved':False,'credential_ready':False}
        if cid:
            c=self.connections.get(cid)
            if c['library_id']==library_id:provider=self.providers.public(cid)
        elif settings['base_url']:provider.update(self.keys.metadata(self.organizer_ref(library_id,settings['base_url'],pid=='separate:session')))
        status=self.organizer.status(library_id);counts=status['counts']
        mapped={**status,'pending':counts.get('pending',0)+counts.get('running',0),'completed':counts.get('done',0),
                'failed':sum(j['status']=='failed' for j in status['jobs']),'retrying':sum(j['status']=='retry' for j in status['jobs']),
                'calls_24h':status['usage_24h']['count'],'chars_24h':status['usage_24h']['chars']}
        return {'settings':{**settings,'provider_mode':'connection' if cid else 'separate','connection_id':cid},
                'status':mapped,'provider':provider,'batches':status['jobs'],'candidates':raw.get('meta',{}).get('organizer_candidates',[])}
    def organizer_settings(self,library_id,data):
        from ..organizer import DEFAULT_PROFILE,save_profile
        raw=self.organizer_view(library_id)['settings'];mode=data.get('provider_mode',raw['provider_mode'])
        if mode not in ('connection','separate'):raise ValidationError('整理模型方式不正确')
        settings={k:data[k] for k in DEFAULT_PROFILE if k in data}
        if mode=='connection':
            cid=data.get('connection_id',raw['connection_id']);c=self.connections.get(cid)
            if c['library_id']!=library_id or c['host']!='api' or c['revoked']:raise ValidationError('请选择本库有效的API连接')
            settings['provider_id']='connection:'+cid
        else:
            settings['provider_id']=raw['provider_id'] if raw['provider_id'].startswith('separate') else 'separate'
            base=data.get('base_url',raw['base_url'])
            key=data.get('api_key','')
            if not isinstance(key,str) or len(key)>32768:raise ValidationError('整理模型密钥格式不正确')
            if key.strip():
                temporary=data.get('save_key',True) is False
                self.keys.set(self.organizer_ref(library_id,base,temporary),key.strip(),persist=data.get('save_key',True))
                settings['provider_id']='separate:session' if temporary else 'separate'
        self.transact(library_id,lambda brain:save_profile(brain,**settings))
        self.enqueue_archives(library_id)
        return self.organizer_view(library_id)
    def enqueue_archives(self,library_id):
        from ..core.brain import Brain
        from ..companion.dedup import is_duplicate
        brain=Brain(self.snapshot(library_id));ids=[]
        for node in brain.nodes.values():
            if is_duplicate(node,brain) or node.get('meta',{}).get('memory_disabled'):continue
            if node.get('meta',{}).get('source') not in ('conversation_turn','tool_observation','agent_output','harness_recorded','persona_import_source'):continue
            ids.append((node['meta'].get('evidence') or {}).get('archive_receipt_id') or node['id'])
        for i in range(0,len(ids),1000):self.organizer.enqueue(library_id,list(dict.fromkeys(ids[i:i+1000])))
    def forget_preview(self,library_id,nid):
        from ..core.brain import Brain
        from .controls import forget_plan
        brain=Brain(self.snapshot(library_id));extra=[]
        while True:
            plan=forget_plan(brain,nid,extra);copies=self.connections.forgetting(library_id,plan['raw_ids'],plan['texts'])
            merged=set(extra)|set(copies['node_ids'])
            if merged==set(extra):break
            extra=sorted(merged)
        plan['raw_ids']=sorted(set(plan['raw_ids'])|set(copies['raw_ids']))
        return plan
    def forget_memory(self,library_id,nid):
        from .controls import forget,forget_plan
        # Recompute the closure under the SAME graph lock used by organizer apply.
        # A newly committed dependent between preview and confirm cannot survive.
        with self._apply_lock:
            actual={}
            def commit(brain):
                plan=forget_plan(brain,nid)
                actual.update(plan)
                self.organizer.forget(library_id,plan['raw_ids'],node_ids=plan['node_ids'])
                return forget(brain,plan)
            result=self.transact(library_id,commit)
            self.connections.forget(library_id,actual['raw_ids'],actual['texts'])
            if self.usage:
                try:
                    for offset in range(0,len(actual['node_ids']),1000):self.usage.forget(library_id,actual['node_ids'][offset:offset+1000])
                except Exception:pass
            result['backups_removed']=self.backups.purge(library_id)
        return result
    def structured_context(self,library_id,data):
        meta=self.library(library_id)
        self.port_for(library_id)
        return self._servers[library_id].RequestHandlerClass.memory_structured_material(
            data,library_id=library_id,library_name=meta['name'])
    def memory_access(self,library_id,action,data):
        from ..core.brain import Brain
        from ..companion.catalog import memory_bootstrap,memory_catalog,memory_read
        from .tool_scope import validate_tool_arguments
        args=validate_tool_arguments('memory_'+action,data)
        meta=self.library(library_id)
        functions={'bootstrap':memory_bootstrap,'list':memory_catalog,'read':memory_read}
        if action not in functions:raise ValidationError('未知记忆读取方式')
        return functions[action](Brain(self.snapshot(library_id)),library_id,meta['name'],**args)
    def window_handoff(self,library_id,data):
        from ..core.brain import Brain
        from ..companion.handoff import window_handoff
        if set(data)-{'profile'}:raise ValidationError('记忆包只接受 S/M/L 大小，不接受其他存档参数')
        meta=self.library(library_id)
        return window_handoff(Brain(self.snapshot(library_id)),library_id,meta['name'],profile=data.get('profile','M'))
    def dialogue_import(self,library_id,data,*,apply=False):
        from ..core.brain import Brain
        from ..ingest.dialogues import plan_dialogues,import_dialogues
        allowed={'content','name','format','confirm','expected_fingerprint'} if apply else {'content','name','format'}
        if set(data)-allowed:raise ValidationError('聊天导入含未声明参数')
        if self.library(library_id)['is_demo']:raise ValidationError('示例库不能导入聊天记录')
        args={key:data[key] for key in ('content','name','format') if key in data}
        args.setdefault('content',None)
        if apply:
            result=self.transact(library_id,lambda brain:import_dialogues(brain,**args,
                confirm=data.get('confirm'),expected_fingerprint=data.get('expected_fingerprint')))
            if result.get('ids'):self.enqueue_nodes(library_id,result['ids'])
            return result
        return plan_dialogues(Brain(self.snapshot(library_id)),**args)
    def enqueue_nodes(self,library_id,node_ids):
        from ..core.brain import Brain
        from ..companion.dedup import canonical_id,is_duplicate
        brain=Brain(self.snapshot(library_id));ids=[]
        for nid in node_ids:
            node=brain.get(nid)
            if node is None or is_duplicate(node,brain) or node.get('meta',{}).get('memory_disabled'):continue
            if node.get('meta',{}).get('source') not in ('conversation_turn','tool_observation','agent_output','harness_recorded','persona_import_source'):continue
            evidence=node['meta'].get('evidence') or {}
            ids.append(evidence.get('archive_receipt_id') or nid)
        ids=list(dict.fromkeys(ids))
        for offset in range(0,len(ids),1000):self.organizer.enqueue(library_id,ids[offset:offset+1000])
        return len(ids)
    def duplicate_view(self,library_id):
        from ..core.brain import Brain
        from ..companion.dedup import possible_groups,is_duplicate,canonical_id,recording_version
        brain=Brain(self.snapshot(library_id));groups=possible_groups(brain)
        merged={}
        for node in brain.nodes.values():
            if is_duplicate(node,brain):merged.setdefault(canonical_id(brain,node),[]).append(node['id'])
        return {'groups':groups,'confirmed_alias_count':sum(len(v) for v in merged.values()),
                'confirmed_groups':merged,'merged_groups':[{'canonical_id':c,'alias_ids':items,'expected':{i:recording_version(brain.get(i)) for i in [c,*items] if brain.get(i)}} for c,items in merged.items()],
                'raw_deleted':0,'read_only':True}
    def library(self,library_id=None):
        selected=library_id or self.manager.default_id
        if selected in self._closing_libraries:raise LibraryError('记忆库正在移入回收站')
        return self.manager.get_library(selected)
    def library_delete_preview(self,library_id):
        item=self.library(library_id)
        return {'library':item,'read_only':True,'recoverable':True,
                'connections_to_disconnect':sum(not c['revoked'] for c in self.connections.list(library_id)),
                'description':'移入回收站并停止接收；原文与记忆保留，可恢复。恢复不会重新启用旧聊天连接。'}
    def delete_library(self,library_id):
        library_meta=self.library(library_id)
        # Make a barrier against both new capture and callbacks from old organizer jobs.
        if library_meta.get('available'):self.port_for(library_id)
        warnings=[]
        with self._apply_lock:
            self._closing_libraries.add(library_id)
            try:
                for c in self.connections.list(library_id):
                    if c['revoked']:continue
                    config=self.connection_config(c['id'])
                    self.connections.toggle(c['id'],False,disconnect=True)
                    if c['host']=='agent':self.update_agent_config(c['id'])
                    if c['host']=='harness' and c.get('configured_at'):
                        import importlib.util
                        path=harness_resources()/'configure.py'
                        try:
                            spec=importlib.util.spec_from_file_location('nkb_trash_harness',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                            module.set_enabled(config,False,remove=True)
                        except Exception:warnings.append('服务已拒绝旧连接；宿主插件停用尚未确认，请重载或移除该连接插件。')
                self.organizer.forget(library_id,[],node_ids=[])
                server=self._servers.get(library_id)
                if server:
                    # This shares the operation lock with every ordinary graph request.
                    def pause(brain):
                        if brain.meta.get('organizer_profile'):brain.meta['organizer_profile']['enabled']=False
                        return {}
                    if not self.manager.get_library(library_id)['is_demo'] and self.manager.path_for(library_id).exists():server.RequestHandlerClass.memory_transaction(pause)
                    server.shutdown();server.server_close()
                    with self._lock:self._servers.pop(library_id,None)
                result=self.manager.delete_library(library_id)
                return {**result,'warnings':warnings,'connections_rebound':False}
            finally:self._closing_libraries.discard(library_id)
    def restore_library(self,library_id):
        return self.manager.restore_library(library_id,select=True)
    def new_connection(self,data):
        lib=self.library(data.get('library_id'))
        if lib['is_demo']:raise ValidationError('演示库不能绑定实际对话')
        provider=data.get('provider') if 'provider' in data else {k:data[k] for k in ('base_url','model','api_key','save_key') if k in data}
        if data.get('host')=='api':
            from .providers import validate_settings
            validate_settings(provider)
        default_scope='next_session' if data.get('host')=='agent' else 'connection'
        c=self.connections.create(data.get('name'),data.get('host'),lib['id'],data.get('session_scope',default_scope))
        try:
            if c['host']=='api':self.providers.save(c['id'],provider)
            if c['host']=='agent':self.update_agent_config(c['id'])
            return self.connection_config(c['id'])
        except Exception:
            if c['host']=='api':
                try:self.keys.delete(self.providers.ref(c['id'],provider.get('base_url')))
                except Exception:pass
            with self.connections.db() as db:
                db.execute('DELETE FROM providers WHERE connection_id=?',(c['id'],))
                db.execute('DELETE FROM connections WHERE id=?',(c['id'],))
            raise
    def update_agent_config(self,cid):
        source=self.sources.for_connection(cid)
        if source:return self.sources.configuration(source['id'],base_url=f'http://127.0.0.1:{self.controller_port}')
        from .agent_client import make_agent_config
        return make_agent_config(self.root,self.connections.get(cid,secret=True),persist=True)
    def drain_agent_outboxes(self):
        if not self.controller_port:return
        from .agent_client import AgentClient
        for connection in self.connections.list():
            if connection['host']!='agent' or not connection['enabled'] or connection['revoked']:continue
            folder=self.root/'agent-outbox'/connection['id']
            if not folder.exists() or not any(folder.glob('*.json')):continue
            try:AgentClient(self.root/'agent-connections'/(connection['id']+'.json'),timeout=3).drain(limit=30)
            except Exception:pass
    def agent_tool(self,cid,token,data):
        c=self.connections.authenticate(cid,token)
        if self.sources.for_connection(cid):raise RequestError('登记的活动来源使用专用事件与上下文接口',403)
        if c['host']!='agent':raise ValidationError('这不是通用Agent记忆连接')
        if not isinstance(data,dict) or set(data)-{'name','arguments'}:raise ValidationError('工具请求不能选择其他库或连接')
        name=data.get('name');args=data.get('arguments',{})
        from .tool_scope import validate_tool_arguments
        args=validate_tool_arguments(name,args)
        self.library(c['library_id'])
        self.connections.heartbeat(cid,{'adapter_version':'agent-memory-tool/v1'})
        if name in ('memory_bootstrap','memory_list','memory_read'):
            return {**self.memory_access(c['library_id'],name.removeprefix('memory_'),args),'connection_id':cid}
        if name=='memory_status':
            lib=self.library(c['library_id']);public=self.connections.get(cid)
            return {'connected':True,'library_id':lib['id'],'library_name':lib['name'],'node_count':lib['node_count'],
                    'model_api_key_required':False,'read_only':True,'connection':public,
                    'capture_mode':'host_hook_verified' if public['archive_status']=='automatic_connected' else 'tools_only',
                    'automatic_memory':public['archive_status']=='automatic_connected'}
        if name=='memory_context':
            context=self.context(cid,token,args)
            return context['memory_context']
        if name=='memory_persona':return local_json(self.port_for(c['library_id']),'/api/persona')
        if name=='memory_remember':
            rejected=self._agent_session_gate(c,args.get('session_id'))
            if rejected:return rejected
            result=local_json(self.port_for(c['library_id']),'/api/ai/remember',{**args,'origin':'harness'})
            self.enqueue_nodes(c['library_id'],[result.get('id')]);return result
        if name=='memory_persona_import':
            if args.get('explicit') is not True or not isinstance(args.get('user_request'),str) or not args['user_request'].strip():raise ValidationError('人格导入需要明确用户请求与原话')
            event={'session_id':args.get('session_id'),'event_id':'persona:'+str(args.get('request_id','')),'event_type':'agent/persona-import',
                   'record':{'schema':'love-house-agent-tool/v1'},'normalized':{'type':'persona_import','turn_id':args.get('request_id'),
                   'text':args.get('text'),'explicit':True,'status':'complete','origin':'agent_user_persona_import','evidence':{'user_request':args['user_request']}}}
            return self.accept(cid,token,event)
        if name in ('memory_record_turn','memory_event'):
            from .agent_client import event_from_tool
            return self.accept(cid,token,event_from_tool(name,args))
        raise ValidationError('未知记忆工具；不会执行任意接口或代码')
    def connection_config(self,cid):
        source=self.sources.for_connection(cid)
        if source:
            descriptor=self.sources.configuration(source['id'],base_url=f'http://127.0.0.1:{self.controller_port}')
            setup=('这个活动来源固定到 '+source['library_id']+'，宿主标识为 '+source['runtime_agent_id']+'。\n'
                   '在同一台机器的适配器中加载私有文件：'+descriptor['private_path']+'\n'
                   '这不是通用MCP配置；配置就绪不证明全部行为已采集。')
            return {'connection':self.connections.get(cid),'source':source,'agent_setup_text':setup,
                    'host_config':'','configuration_ready':True,'supported':True,'requires_apply':False,
                    'api_base_url':'','client_api_key':'','source_config':descriptor,'mode':'registered_source',
                    'instructions':descriptor['instructions']}
        c=self.connections.get(cid);secret=self.connections.get(cid,secret=True)
        if c['revoked']:
            return {'connection':c,'host_config':'','api_base_url':'','configuration_ready':False,
                    'requires_apply':False,'supported':False,'instructions':'连接已断开，原记忆保留；需要时新建连接。'}
        if c['host']=='agent':
            from .agent_client import make_agent_config
            bundle=make_agent_config(self.root,secret,persist=False)
            code=json.dumps(bundle['mcp_config'],ensure_ascii=False,indent=2)
            setup=("这是同一台电脑上的爱之屋长期记忆连接，不需要模型厂商API Key。\n"
                   "此连接固定属于记忆库："+self.library(c['library_id'])['name']+"（"+c['library_id']+"）。\n"
                   "请把下面MCP配置保存到你的宿主设置并加载，随后调用memory_status验证；不要只口头回复已连接，也不要写虚构的测试经历。\n"
                   "在新窗口先调用memory_bootstrap恢复已有身份、人格和初始记忆；全部可用记忆通过memory_list分页及memory_read分块读取。"
                   "不要把初始有界包误称为已经加载全部记忆，不要安装同一窗口下的其他记忆库配置。\n\n"
                   +code+"\n\n若宿主支持真实轮次结束钩子，请将下列命令接入回调，stdin传实际用户发言和最终可见回复。默认只接收首个真实完整hook绑定的窗口。尚未绑定时，手动补录不抢占窗口；其他窗口不记录。没有钩子时，请明确说明尚未自动存档；需手动工具模式时由用户明确选择高级整连接范围。\n"
                   +json.dumps(bundle['hook_config'],ensure_ascii=False,indent=2)+"\n\n同一窗口的稳定会话ID不变时，重启会自动发现服务并重连。要换新窗口，请新建连接并选择原存档，延续记忆身份。此配置不是跨设备公网地址。")
            if c['session_scope']=='connection':
                setup=setup.replace('默认只接收首个真实完整hook绑定的窗口。尚未绑定时，手动补录不抢占窗口；其他窗口不记录。',
                    '当前配置采用高级整连接范围，可能记录多个窗口。若只需要一个窗口，请在爱之屋新建单窗口连接；不要把此配置说成仅限一个窗口。')
            return {'connection':c,**bundle,'host_config':code,'agent_setup_text':setup,'api_base_url':'','client_api_key':'',
                    'configuration_ready':Path(bundle['private_path']).is_file(),'requires_apply':False,'supported':True,
                    'instructions':'复制给具备本机MCP/工具配置能力的Agent；自动每轮记录还需要真实宿主钩子。'}
        base=f'http://127.0.0.1:{self.controller_port}'
        config={'connectionId':cid,'connectionToken':secret['token'],'libraryId':c['library_id'],
                'sessionScope':c['session_scope'],'runtimeDir':str(self.root/'.runtime')}
        plugin=harness_resources()/'dist/index.js'
        # A local absolute path is resolved on this installation, never published as a user's path.
        overlay=("- insert:\n    - id: neural-memory-autocapture-"+cid[-8:]+"\n"
                 +"      name: "+json.dumps(str(plugin),ensure_ascii=False)+"\n      config:\n"
                 +''.join('        '+k+': '+json.dumps(v,ensure_ascii=False)+'\n' for k,v in config.items()))
        setup=None
        helper=plugin.parent.parent/'configure.py'
        if c['host']=='harness' and helper.exists():
            import importlib.util
            spec=importlib.util.spec_from_file_location('nkb_harness_plan',helper)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            setup=module.configure({'connection':c,'config':config,'host_options':self.adapter_options},apply=False)
            overlay=setup.get('overlay',overlay)
        return {'connection':c,'provider':self.providers.public(cid) if c['host']=='api' else None,
                'client_api_key':secret['token'] if c['host']=='api' else '',
                'host_config':overlay if c['host']=='harness' else base+'/connections/'+cid+'/v1',
                'api_base_url':base+'/connections/'+cid+'/v1','config':config,
                'host_options':self.adapter_options,
                'setup':setup,'supported': bool(setup and setup.get('supported')) if c['host']=='harness' else True,
                'requires_apply':c['host']=='harness' and not bool(c.get('configured_at')),
                'configuration_ready':c['host']=='api' or bool(c.get('configured_at')),
                'instructions':('将本地API地址和连接凭证填入聊天客户端；请求经过这里才会自动存档。' if c['host']=='api' else '加载宿主自动存档插件后发起一轮新对话；首条完整记录落盘后才显示自动存档。')}
    def _agent_session_gate(self,connection,sid,*,claim=False,read=False,automatic=False):
        """Scope before any receipt/raw write. Reads never enroll an Agent window.

        The host supplies the real session id. A pending generic connection can
        only be enrolled by a complete automatic host turn; model tools, partial
        streams and observations cannot claim whichever window happens to run
        first. The matching local client filters before its outbox as well.
        """
        current=self.connections.get(connection['id'],secret=True)
        scope=current['session_scope']
        def rejection(code,message):
            return {'accepted':False,'saved':False,'status':code,'code':code,'message':message,
                    'connection_id':current['id'],'library_id':current['library_id'],
                    'session_scope':scope,'bound_session_id':None if scope in ('connection','next_session') else scope}
        if read and scope=='next_session':
            if sid is not None and (not isinstance(sid,str) or not sid.strip() or len(sid)>200):
                raise ValidationError('读取记忆需要有效的宿主会话标识')
            return None
        if not isinstance(sid,str) or not sid.strip() or len(sid)>200:
            raise ValidationError('请由宿主提供当前窗口的真实会话ID；不会用占位ID绑定窗口')
        if scope=='next_session' and not claim:
            return rejection('awaiting_window_binding','等待目标窗口提交首轮完整对话；本次内容没有存档')
        if scope not in ('connection','next_session') and scope!=sid:
            if read:raise ValidationError('此连接只读取已绑定窗口的记忆；当前会话ID不匹配')
            return rejection('scope_conflict' if automatic else 'ignored_scope','此连接已固定到另一窗口；本次内容没有采集或存档')
        # BEGIN IMMEDIATE in authorize_session makes competing first turns
        # choose one window; the loser cannot create even a raw receipt.
        try:self.connections.authorize_session(current['id'],sid)
        except ValidationError:
            if read:raise
            latest=self.connections.get(current['id'],secret=True)
            scope=latest['session_scope']
            return rejection('scope_conflict' if automatic else 'ignored_scope','窗口绑定发生冲突，本次内容没有采集或存档')
        if scope=='next_session':self.update_agent_config(current['id'])
        return None
    @staticmethod
    def _agent_claimable_turn(event):
        if not isinstance(event,dict):return False
        record=event.get('record') if isinstance(event.get('record'),dict) else {}
        normalized=event.get('normalized') or record.get('normalized')
        return bool(record.get('schema')=='love-house-agent-hook/v1' and isinstance(normalized,dict)
                    and normalized.get('type')=='turn' and normalized.get('status')=='complete'
                    and normalized.get('origin')=='agent_host_hook'
                    and all(isinstance(normalized.get(role),str) and bool(normalized[role].strip())
                            and len(normalized[role])<=40000 for role in ('user','assistant')))
    def accept(self,cid,token,event):
        c=self.connections.authenticate(cid,token)
        self.sources.check_source_event(c,event)
        if c['host']=='agent':
            if not isinstance(event,dict):raise ValidationError('事件必须是对象')
            record=event.get('record') if isinstance(event.get('record'),dict) else {}
            rejected=self._agent_session_gate(c,event.get('session_id'),claim=self._agent_claimable_turn(event),
                                               automatic=record.get('schema')=='love-house-agent-hook/v1')
            if rejected:return rejected
        result=self.connections.receive(c,event)
        self.process_pending(library_id=c['library_id'],receipt_id=result['receipt_id'],limit=1)
        current=self.connections.get(cid)
        return {**result,'status':next((e['status'] for e in self.connections.activity(c['library_id'])['events'] if e['id']==result['receipt_id']),result['status']),
                'library_id':c['library_id'],'session_scope':current['session_scope'],
                'bound_session_id':None if current['session_scope'] in ('connection','next_session') else current['session_scope']}
    def context(self,cid,token,data):
        from ..companion import connected_session_id
        c=self.connections.authenticate(cid,token)
        data=self.sources.check_context(c,data)
        sid=data.get('session_id')
        if set(data)-{'query','session_id','max_chars'}:raise ValidationError('连接上下文不能选择其他记忆库')
        if c['host']=='agent':
            self._agent_session_gate(c,sid or ('agent-default' if c['session_scope']=='connection' else None),read=True)
            sid=sid or ('agent-default' if c['session_scope']=='connection' else 'unbound-memory-read')
        else:self.connections.authorize_session(cid,sid)
        if not isinstance(data.get('query'),str) or not data['query'].strip():raise ValidationError('查询内容不能为空')
        # Ingestion is the receipt/worker path's responsibility. A read must not
        # wait for another source's queued graph saves before the next action.
        result=self.structured_context(c['library_id'],{'query':data['query'],'session_id':connected_session_id(cid,sid),
                                                      'max_chars':data.get('max_chars',8000)})
        try:
            coverage=result.get('source_coverage')
            if not isinstance(coverage,dict):
                coverage={'organized':0,'raw':0,'other':0}
                for item in result.get('memory_context',{}).get('records',[]):
                    kind=item.get('source',{}).get('kind')
                    category='organized' if kind in ('organizer','user_confirmed') else 'raw' if kind in ('conversation_turn','tool_observation','agent_output','harness_recorded','history_import') else 'other'
                    coverage[category]+=1
            self.connections.record_recall(c['id'],coverage)
        except Exception:pass  # Optional counters never interrupt scoped recall.
        # Queue opaque use IDs only after authenticated, scoped context retrieval.
        # Bootstrap/catalog/export/preview never count as rehearsal. The material
        # itself remains read-only; use effects join the next actual graph save.
        if c['session_scope']!='next_session':
            self.queue_memory_use(c['library_id'],[r['id'] for r in result.get('memory_context',{}).get('records',[])])
        backlog=self.connections.pending_count(c['library_id'])
        return {**result,'library_id':c['library_id'],'connection_id':cid,'archive_pending':backlog}
    def process_pending(self,*,library_id=None,receipt_id=None,limit=50):
        if not self._apply_lock.acquire(False):return
        try:
            for receipt in self.connections.pending(limit,library_id=library_id,receipt_id=receipt_id):
                try:self.library(receipt['library_id'])
                except LibraryError:continue
                try:
                    outer=json.loads(receipt['payload'])
                    normalized=outer.get('normalized') or (outer.get('record') or {}).get('normalized') or outer
                    e={**normalized,'connection_id':receipt['connection_id'],'session_id':receipt['session_id']}
                    e.setdefault('status','complete');e.setdefault('turn_id',str(outer.get('event_id',receipt['id'])))
                    e.setdefault('origin','harness_hook' if outer.get('record',{}).get('schema')=='deepseek-harness-event/v1' else 'api_proxy')
                    e['evidence']={**(e.get('evidence') if isinstance(e.get('evidence'),dict) else {}),'archive_receipt_id':receipt['id'],'raw_event_preserved':True}
                    record=outer.get('record') or {}
                    source=self.sources.for_connection(receipt['connection_id'])
                    if source:
                        e['evidence'].update(platform=outer.get('platform'),source_id=source['id'],
                            source_runtime_agent_id=source['runtime_agent_id'],source_event_at=outer.get('occurred_at'),
                            source_time_unknown=outer.get('occurred_at') is None)
                        if e.get('type')=='turn':
                            raw=record.get('raw_event') if isinstance(record.get('raw_event'),dict) else {}
                            details=raw.get('details') if isinstance(raw.get('details'),dict) else {}
                            sender=details.get('sender_id')
                            sender=str(sender) if type(sender) in (str,int) else ''
                            if len(sender)>200 or any(ord(c)<32 for c in sender):sender=''
                            e['evidence'].update(participant_scope='external_participant',participant_id=sender or 'unspecified_platform_peer')
                    if record.get('schema')=='love-house-agent-tool/v1':
                        for field in ('source_session_id','source_event_id'):
                            if isinstance(record.get(field),str):e[field]=record[field]
                    for key in ('user','assistant'):
                        if isinstance(e.get(key),str) and len(e[key])>40000:
                            e[key]=e[key][:39950]+'…[节点摘录；完整原文保存在事件档案]'
                            e['evidence']['content_truncated']=True
                    if e.get('type') in ('tool','output'):
                        # Output has one validated text field. The legacy tool
                        # content alias must not replace it with unchecked text
                        # that differs from the organizer's archived evidence.
                        content=e.get('text','') if e['type']=='output' else e.get('content',e.get('text',''))
                        e['text']=content if isinstance(content,str) else json.dumps(content,ensure_ascii=False)
                        if e.get('type')=='tool':
                            call_key=json.dumps([e['turn_id'],e.get('call_id')],ensure_ascii=False)
                            e['evidence']['call_id']=str(e.get('call_id',''))[:200]
                            e['turn_id']='tool:'+hashlib.sha256(call_key.encode()).hexdigest()[:40]
                        if len(e['text'])>40000:
                            e['text']=e['text'][:39950]+'…[节点摘录；完整结果保存在事件档案]'
                            e['evidence']['content_truncated']=True
                    def ingest(brain):
                        from ..companion import ingest_event
                        from ..companion.retention import match_mentions,record_memory_use
                        if e.get('type')=='turn' and e.get('status')=='complete' and isinstance(e.get('user'),str):
                            from ..companion.ingestion import connected_session_id
                            from ..companion.memory import turn_id
                            own_id=turn_id(connected_session_id(e['connection_id'],e['session_id']),e['turn_id'])
                            matches=match_mentions(brain,e['user'])
                            record_memory_use(brain,[item['id'] for item in matches if item['id']!=own_id],kind='mention')
                        return ingest_event(brain,e)
                    result=self.transact(receipt['library_id'],ingest)
                    if result.get('status')=='forgotten':
                        self.connections.forget(receipt['library_id'],[receipt['id']],[])
                    else:
                        self.connections.applied(receipt['id'],result.get('node_ids',[]),automatic=outer.get('record',{}).get('schema')!='love-house-agent-tool/v1')
                        if result.get('node_ids') and not result.get('duplicate_of'):self.enqueue_nodes(receipt['library_id'],result.get('node_ids',[]))
                except Exception as exc:
                    self.connections.failed(receipt['id'],'暂未写入图谱，将重试（'+type(exc).__name__+'）')
        finally:self._apply_lock.release()
    def _retry(self):
        while not self.stopping.wait(3):
            self.process_pending()
            self.drain_agent_outboxes()
    def stop(self):
        self.updates.stop()
        self.stopping.set();self.organizer.stop();self.worker.join(timeout=5)
        with self._lock:
            for server in self._servers.values():server.shutdown();server.server_close()
            for thread in self._threads:thread.join(timeout=3)


def make_controller(host):
    # Reuse the audited host/origin/JSON validation and response headers, not graph mutation routing.
    from ..core.brain import Brain
    Base=make_handler(Brain.new())
    class Controller(Base):
        def _guard_connection_surface(self,path):
            # A memory bearer is a per-connection capability, not a desktop
            # management credential. Local desktop requests without a bearer
            # remain in the user's local trust domain.
            if (self.headers.get('Authorization') or self.headers.get('X-NKB-Connection-Key')) and not (
                    path.startswith('/api/connections/') or path.startswith('/connections/')):
                raise RequestError('记忆连接凭证不能访问桌面管理或其他库接口',403)
            # The advanced proxy also accepts a caller's vendor key. A known
            # local memory token must never be mistaken for that vendor key or
            # forwarded to another connection's upstream.
            token=self._token()
            if token:
                import hmac
                from urllib.parse import parse_qs,urlsplit
                with host.connections.db() as db:bindings=db.execute('SELECT id,token,library_id FROM connections').fetchall()
                for binding in bindings:
                    if hmac.compare_digest(token,binding['token']):
                        parts=path.strip('/').split('/')
                        cid=parts[2] if parts[:2]==['api','connections'] and len(parts)>2 else parts[1] if parts[:1]==['connections'] and len(parts)>1 else None
                        query=parse_qs(urlsplit(self.path).query)
                        if (cid!=binding['id'] or self.headers.get('X-NKB-Library') not in (None,binding['library_id'])
                            or any(value!=binding['library_id'] for value in query.get('library_id',[]))):
                            raise RequestError('记忆凭证只属于它创建时绑定的连接和存档',403)
                        break
        def _chosen(self):
            from urllib.parse import parse_qs,urlsplit
            q=parse_qs(urlsplit(self.path).query)
            selected=self.headers.get('X-NKB-Library') or q.get('library_id',[host.manager.default_id])[0]
            try:host.library(selected)
            except LibraryError:raise RequestError('记忆库不存在或已移入回收站',404) from None
            return selected
        def _proxy(self,path,body=None):
            lib=self._chosen();meta=host.library(lib)
            if path.split('?',1)[0]=='/api/ai/chat':
                raise RequestError('星图只负责记忆存储；请在你的客户端聊天，并使用连接页的API网关或宿主自动存档插件',410)
            if meta['is_demo'] and self.command=='POST' and path not in ('/api/recall','/api/preview','/api/ai/context','/api/memory/context','/api/import/preview'):
                raise RequestError('演示库只供浏览；请选择实际记忆库')
            if path.split('?',1)[0] in ('/api/ai/context','/api/memory/context') and body is not None:
                result=host.structured_context(lib,body)
                # Existing MCP bridge processes also receive one compact object.
                # Their code may stay loaded while the desktop service upgrades.
                return result['memory_context'] if path.split('?',1)[0]=='/api/ai/context' and body.get('origin')=='harness' else result
            try:
                result=local_json(host.port_for(lib),path,body)
                if body is not None and path.split('?',1)[0] in ('/api/ai/record','/api/ai/event','/api/ingest'):
                    if not result.get('duplicate_of'):host.enqueue_nodes(lib,[result.get('id')] if result.get('id') else result.get('node_ids',[]))
                return result
            except urllib.error.HTTPError as exc:
                try:message=json.load(exc).get('error','记忆服务请求失败')
                except Exception:message='记忆服务请求失败'
                raise RequestError(str(message),exc.code) from None
        def _error(self,exc):
            if isinstance(exc,RequestError):return self._json({'error':str(exc)},exc.status)
            if isinstance(exc,LibraryError):return self._json({'error':str(exc)},400)
            if isinstance(exc,ValidationError):return self._json({'error':str(exc)},400)
            if isinstance(exc,KeyStoreError):return self._json({'error':str(exc)},503)
            return self._json({'error':'记忆服务暂时不可用'},500)
        def _token(self):
            h=self.headers.get('Authorization','')
            return h[7:] if h.startswith('Bearer ') else self.headers.get('X-NKB-Connection-Key','')
        def do_GET(self):
            try:
                parsed=self._check_request();path=parsed.path
                self._guard_connection_surface(path)
                if self.headers.get('Authorization') or self.headers.get('X-NKB-Connection-Key'):
                    raise RequestError('记忆连接只接受绑定工具和事件请求',403)
                if path in ('/','/index.html'):
                    from ..viz.builder import html_for_serve
                    return self._html(html_for_serve())
                if path=='/api/health':return self._json({'ok':True,'name':'爱之屋记忆服务','version':__version__,'protocol_version':'0.4.0','mode':'storage','controller_instance_id':host.instance_id})
                if path=='/api/updates':
                    host.updates.start()
                    return self._json(host.updates.status())
                if path=='/api/retention':return self._json(host.retention_view(self._chosen()))
                if path=='/api/agent/sources':return self._json(host.agent_sources_view(self._chosen()))
                if path=='/api/experiences':
                    from urllib.parse import parse_qs
                    try:limit=int(parse_qs(parsed.query).get('limit',['30'])[0])
                    except (ValueError,TypeError):raise ValidationError('经历数量须为1至100的整数') from None
                    return self._json(host.experiences_view(self._chosen(),limit=limit))
                if path=='/api/adapters/astrbot/package':return self._respond(host.astrbot_package(),200,'application/zip')
                if path=='/api/memory/status':
                    lib=host.library(self._chosen())
                    return self._json({'memory_connected':True,'storage':'local','mode':'memory_service',
                        'library_id':lib['id'],'library_name':lib['name'],'node_count':lib['node_count'],
                        'is_demo':lib['is_demo'],'api_key_required':False,
                        'connections':host.connections.list(lib['id'])})
                if path=='/api/libraries':return self._json({'libraries':host.manager.list_libraries(),'selected_id':host.manager.selected_id,'trashed_count':len(host.manager.list_trash())})
                if path=='/api/libraries/trash':return self._json({'libraries':host.manager.list_trash(),'read_only':True})
                if path=='/api/connections':return self._json(host.connections_view())
                if path.startswith('/api/connections/') and path.endswith('/config'):
                    return self._json(host.connection_config(path.split('/')[3]))
                if path=='/api/duplicates':return self._json(host.duplicate_view(self._chosen()))
                if path=='/api/organizer':return self._json(host.organizer_view(self._chosen()))
                if path=='/api/organizer/rules':
                    from ..core.brain import Brain
                    from ..organizer.rules import guidance_view
                    lib=self._chosen()
                    return self._json(guidance_view(Brain(host.snapshot(lib))))
                if path=='/api/backups':return self._json({'backups':host.backups.list(self._chosen())})
                if path=='/api/activity':
                    lib=self._chosen();result=host.connections.activity(lib)
                    try:result['graph_revision']=host.manager.path_for(lib).stat().st_mtime_ns
                    except OSError:result['graph_revision']=None
                    return self._json(result)
                if path.startswith('/api/activity/'):
                    record=host.read_archive(self._chosen(),path.split('/')[-1])
                    if record is None:raise RequestError('当前库没有这条事件档案，或已忘记',404)
                    return self._json(record)
                if path=='/api/adapters/harness/detect':return self._json(self._adapter('detect'))
                return self._json(self._proxy(self.path))
            except Exception as exc:return self._error(exc)
        def _adapter(self,action,cid=None,data=None):
            # Optional installer is shipped with the extension; no credentials are inspected.
            import importlib.util
            path=harness_resources()/'configure.py'
            if not path.exists():return {'detected':False,'supported':False,'message':'适配器正在准备，可使用兼容API接入'}
            spec=importlib.util.spec_from_file_location('nkb_harness_configure',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            if action=='detect':
                result=module.detect((data or {}).get('app_path'),host.adapter_options.get('profile_dir'))
                if host.adapter_options.get('profile_dir'):
                    result['profile_dir']=host.adapter_options['profile_dir']
                    result['profile_exists']=(Path(result['profile_dir'])/'cordis.yml').exists()
                return result
            config=host.connection_config(cid)
            try:result=module.configure(config,apply=(data or {}).get('apply') is True,app_path=(data or {}).get('app_path'))
            except ValueError as exc:raise RequestError(str(exc)[:300],400) from None
            except OSError:raise RequestError('无法写入宿主配置；原有配置与凭据已保留，请检查目录权限',503) from None
            if result.get('applied') is True:host.connections.configured(cid)
            return result
        def do_POST(self):
            try:
                parsed=self._check_request();path=parsed.path;parts=path.strip('/').split('/')
                self._guard_connection_surface(path)
                if len(parts)>=3 and parts[0]=='connections' and parts[2]=='v1':
                    from .proxy import forward_chat
                    return forward_chat(self,host,parts[1])
                if len(parts)==4 and parts[:2]==['api','connections'] and parts[3] in ('events','context','heartbeat','tool'):
                    cid=parts[2];token=self._token();bound=host.connections.authenticate(cid,token)
                    if self.headers.get('X-NKB-Library') not in (None,bound['library_id']):
                        raise RequestError('请求的记忆库与固定连接不一致',403)
                    data=self._body(limit=32*1024*1024 if parts[3]=='events' else 1024*1024)
                    result=(host.accept(cid,token,data) if parts[3]=='events' else
                            host.connections.heartbeat(cid,data) if parts[3]=='heartbeat' else
                            host.agent_tool(cid,token,data) if parts[3]=='tool' else host.context(cid,token,data))
                    return self._json(result)
                if self.headers.get('Authorization') or self.headers.get('X-NKB-Connection-Key'):
                    raise RequestError('记忆连接只接受绑定工具和事件请求',403)
                data=self._body(limit=130*1024*1024 if path in ('/api/sharing/import-preview','/api/sharing/import') else 25*1024*1024 if path in ('/api/dialogue-import/preview','/api/dialogue-import/apply') else 1024*1024)
                if path=='/api/memory/handoff':return self._json(host.window_handoff(self._chosen(),data))
                if path in ('/api/dialogue-import/preview','/api/dialogue-import/apply'):
                    return self._json(host.dialogue_import(self._chosen(),data,apply=path.endswith('/apply')))
                if path=='/api/updates/check':return self._json(host.updates.request_check())
                if path=='/api/updates/settings':return self._json(host.updates.settings(data))
                if path=='/api/retention/settings':return self._json(host.retention_settings(self._chosen(),data))
                if path=='/api/agent/sources':return self._json(host.register_agent_source(self._chosen(),data))
                if len(parts)==5 and parts[:3]==['api','agent','sources'] and parts[4] in ('config','enabled','disconnect'):
                    return self._json(host.agent_source_action(self._chosen(),parts[3],parts[4],data))
                if path=='/api/sharing/preview':
                    lib=self._chosen();preview=host.sharing.preview(lib)
                    provider=host.organizer_view(lib)['provider']
                    return self._json({**preview,'summary_provider':provider})
                if path=='/api/sharing/download':
                    if data.get('confirm') is not True:raise ValidationError('请先确认分享文件包含本库的个人记忆')
                    lib=self._chosen();revision=data.get('expected_revision')
                    if not isinstance(revision,str) or len(revision)!=64:raise ValidationError('请先预览当前存档的分享范围')
                    summary=host.share_summaries.resolve(lib,data.get('summary_id'),revision)
                    return self._json(host.sharing.download(lib,format=data.get('format','json'),expected_revision=revision,reading_summary=summary))
                if path=='/api/sharing/summary':
                    return self._json(host.share_summaries.generate(self._chosen(),expected_revision=data.get('expected_revision'),confirm=data.get('confirm')))
                if path=='/api/sharing/import-preview':return self._json(host.sharing.import_preview(data.get('content')))
                if path=='/api/sharing/import':
                    if data.get('confirm') is not True:raise ValidationError('请先检查分享包并确认创建独立新存档')
                    return self._json(host.sharing.import_file(data.get('content'),name=data.get('name')))
                if path in ('/api/memory/bootstrap','/api/memory/list','/api/memory/read'):
                    return self._json(host.memory_access(self._chosen(),parts[-1],data))
                if len(parts)==4 and parts[:2]==['api','libraries']:
                    lib,action=parts[2:]
                    if action=='delete-preview':return self._json(host.library_delete_preview(lib))
                    if action=='delete':
                        if data.get('confirm') is not True:raise ValidationError('请先查看影响并确认移入回收站')
                        return self._json(host.delete_library(lib))
                    if action=='restore':
                        if data.get('confirm') is not True:raise ValidationError('请确认恢复记忆库；旧连接不会重新启用')
                        return self._json(host.restore_library(lib))
                if path=='/api/libraries':
                    created=host.manager.create_library(data.get('name'));host.manager.select(created['id'])
                    return self._json({'library':created,'selected_id':created['id']})
                if path=='/api/library/select':
                    item=host.manager.select(data.get('library_id'));return self._json({'selected_id':item['id'],'library':item})
                if path=='/api/duplicates/reconcile':
                    from ..companion.dedup import reconcile_recordings
                    result=host.transact(self._chosen(),reconcile_recordings)
                    return self._json({**result,**host.duplicate_view(self._chosen())})
                if path=='/api/duplicates/confirm':
                    from ..companion.dedup import confirm_duplicate
                    lib=self._chosen()
                    result=host.transact(lib,lambda brain:confirm_duplicate(brain,data.get('canonical_id'),data.get('alias_ids'),data.get('expected')))
                    host.enqueue_nodes(lib,[result['canonical_id']])
                    return self._json(result)
                if path=='/api/duplicates/separate':
                    from ..companion.dedup import separate_recordings
                    return self._json(host.transact(self._chosen(),lambda brain:separate_recordings(brain,data.get('node_id'),data.get('expected'))))
                if path=='/api/organizer/settings':return self._json(host.organizer_settings(self._chosen(),data))
                if path=='/api/organizer/preview':return self._json(host.organizer.preview(self._chosen()))
                if path=='/api/organizer/run':
                    lib=self._chosen()
                    if not host.organizer_view(lib)['settings']['enabled']:raise ValidationError('请先启用整理模型，再开始整理；自动采集的原文不受影响')
                    host.enqueue_archives(lib)
                    threading.Thread(target=host.organizer.run_once,args=(lib,),daemon=True).start()
                    return self._json({'queued':True,'library_id':lib})
                if len(parts)==4 and parts[:3]==['api','organizer','candidates']:
                    from ..organizer import review_candidate
                    return self._json(host.transact(self._chosen(),lambda b:review_candidate(b,parts[3],data.get('action'))))
                if len(parts)==5 and parts[:3]==['api','organizer','jobs'] and parts[4] in ('retry','reject'):
                    jobs=host.organizer.status(self._chosen())['jobs']
                    if not any(j['id']==parts[3] for j in jobs):raise ValidationError('本库没有该任务')
                    return self._json(getattr(host.organizer,parts[4])(parts[3]))
                if len(parts)==4 and parts[:2]==['api','memories']:
                    lib=self._chosen();nid=parts[2];action=parts[3]
                    from .controls import set_enabled,correct
                    if action=='enabled':return self._json(host.transact(lib,lambda b:set_enabled(b,nid,data.get('enabled'))))
                    if action=='correct':return self._json(host.transact(lib,lambda b:correct(b,nid,data.get('text'),data.get('label'))))
                    if action=='forget-preview':
                        plan=host.forget_preview(lib,nid)
                        return self._json({'read_only':True,'node_count':len(plan['node_ids']),'archive_count':len(plan['raw_ids']),'copied_archive_count':len(host.connections.forgetting(lib,plan['raw_ids'],plan['texts'])['redacted_receipt_ids']),
                          'node_ids':plan['node_ids'],'backup_count':len(host.backups.list(lib)),
                          'note':'移除相关原文、派生记忆、整理缓存与本库旧备份；人格学习历史将清理。其他客户端及外部副本需要在原处管理。'})
                    if action=='forget':
                        if data.get('confirm') is not True:raise ValidationError('请先查看影响并明确确认忘记')
                        return self._json(host.forget_memory(lib,nid))
                if path=='/api/backups':return self._json(host.backups.create(self._chosen()))
                if len(parts)==4 and parts[:2]==['api','backups']:
                    if parts[3]=='restore-preview':return self._json(host.backups.preview(parts[2],self._chosen()))
                    if parts[3]=='restore':
                        if data.get('confirm') is not True:raise ValidationError('请先预览并确认恢复为新库')
                        return self._json(host.backups.restore(parts[2],self._chosen(),data.get('name')))
                if path=='/api/connections':return self._json(host.new_connection(data))
                if len(parts)==4 and parts[:2]==['api','connections']:
                    cid,action=parts[2:]
                    if action in ('enabled','disconnect'):
                        config=host.connection_config(cid)
                        changed=host.connections.toggle(cid,data.get('enabled',False),disconnect=action=='disconnect')
                        result={'connection':changed}
                        if changed['host']=='agent':host.update_agent_config(cid)
                        if changed['host']=='harness' and config.get('configuration_ready'):
                            import importlib.util
                            path=harness_resources()/'configure.py'
                            try:
                                spec=importlib.util.spec_from_file_location('nkb_harness_pause',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                                result['host_change']=module.set_enabled(config,changed['enabled'],remove=action=='disconnect')
                            except Exception:
                                result['warning']='服务端已暂停接收；宿主侧停用尚未确认，请重载或移除本连接插件。'
                        return self._json(result)
                    if action=='provider':return self._json({'provider':host.providers.save(cid,data)})
                    if action=='configure':return self._json(self._adapter('configure',cid,data))
                return self._json(self._proxy(self.path,data))
            except Exception as exc:return self._error(exc)
        def do_OPTIONS(self):
            try:self._check_request();return self._respond(b'',204,'application/json')
            except Exception as exc:return self._error(exc)
    return Controller
