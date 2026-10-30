"""Connection-bound, vendor-key-free memory transport for local Agent hosts.

The client never opens a brain or a model credential. Runtime discovery is
loopback-only; durable submissions are acknowledged only after server storage.
"""
from __future__ import annotations
from contextlib import contextmanager
from http.client import HTTPException
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

SCHEMA='love-house-agent-connection/v1'
HOOK_SCHEMA='love-house-agent-hook/v1'
TOOL_SCHEMA='love-house-agent-tool/v1'
MAX_EVENT=32*1024*1024
MAX_CONFIG=65536
MAX_QUEUE_EVENTS=5000
MAX_QUEUE_BYTES=128*1024*1024
_ID=re.compile(r'^[A-Za-z0-9_-]{1,200}$')
try:
    import fcntl
except ImportError:
    fcntl=None
try:
    import msvcrt
except ImportError:
    msvcrt=None

class AgentConnectionError(ValueError):
    def __init__(self,message,code='connection_error'):
        super().__init__(message);self.code=code

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise AgentConnectionError('记忆服务重定向已拒绝','redirect_blocked')

def _constant(_):raise ValueError('nonfinite')
def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('duplicate key')
        value[key]=item
    return value

def _json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def _text(value,field,maximum=40000,empty=False):
    if not isinstance(value,str) or (not empty and not value.strip()) or len(value)>maximum:
        raise AgentConnectionError(field+'格式不正确','invalid_input')
    try:value.encode('utf-8')
    except UnicodeError:raise AgentConnectionError(field+'不能保存为UTF-8','invalid_input') from None
    return value

def _atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=None
    try:
        descriptor,temporary=tempfile.mkstemp(dir=str(path.parent),prefix=path.name+'.',suffix='.tmp')
        if hasattr(os,'fchmod'):os.fchmod(descriptor,0o600)
        with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
            stream.write(_json(value));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path);temporary=None
    finally:
        if temporary:Path(temporary).unlink(missing_ok=True)

@contextmanager
def _spool_lock(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (directory/'.delivery.lock').open('a+b') as lock:
        try:
            if hasattr(os,'fchmod'):os.fchmod(lock.fileno(),0o600)
        except OSError:pass
        if fcntl:fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        elif msvcrt:
            # Lock an existing byte; an empty file is not a reliable Windows
            # record lock. Other hook processes must wait rather than overwrite.
            lock.seek(0,2)
            if lock.tell()==0:lock.write(b'\0');lock.flush()
            deadline=time.monotonic()+15
            while True:
                try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()>=deadline:
                        raise AgentConnectionError('待发送队列正被其他进程使用，本次未覆盖记录，请稍后重试','queue_busy') from None
                    time.sleep(.05)
        try:yield
        finally:
            if fcntl:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
            elif msvcrt:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def _read_json(path,limit):
    try:
        with Path(path).open('rb') as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError()
        value=json.loads(raw,parse_constant=_constant,object_pairs_hook=_unique)
        if not isinstance(value,dict):raise ValueError()
        return value
    except (OSError,ValueError,UnicodeError,RecursionError):
        raise AgentConnectionError('本机记忆配置或待发送记录不可读，未覆盖原文件','invalid_file') from None

def validate_config(value):
    allowed={'schema','connection_id','library_id','token','runtime_dir','outbox_dir','enabled','revoked','session_scope','session_scope_policy','bound_session_id','binding_revision'}
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA or set(value)-allowed:
        raise AgentConnectionError('记忆连接配置版本不支持','invalid_config')
    result=dict(value)
    for key in ('connection_id','library_id'):
        if not isinstance(result.get(key),str) or not _ID.fullmatch(result[key]):
            raise AgentConnectionError('记忆连接身份无效','invalid_config')
    for key in ('enabled','revoked'):
        if type(result.get(key)) is not bool:raise AgentConnectionError('记忆连接启停状态无效','invalid_config')
    # v1 files created before single-window capture remain explicitly broad.
    # Do not silently change a previously authorised connection's meaning.
    scope=_text(result.get('session_scope_policy',result.get('session_scope','connection')),'session_scope',200)
    bound=result.get('bound_session_id')
    if bound is not None:bound=_text(bound,'bound_session_id',200)
    if scope=='connection':scope='any'
    elif scope not in ('any','fixed','next_session'):
        if bound not in (None,scope):raise AgentConnectionError('本机窗口范围发生冲突，未改绑','scope_conflict')
        bound=scope;scope='fixed'
    if scope=='fixed' and not bound:raise AgentConnectionError('固定窗口尚未配置会话ID','invalid_config')
    revision=result.get('binding_revision',0)
    if type(revision) is not int or not 0<=revision<=2147483647:raise AgentConnectionError('窗口绑定版本无效','invalid_config')
    result.update(session_scope=scope,session_scope_policy=scope,bound_session_id=bound,binding_revision=revision)
    token=result.get('token')
    if not isinstance(token,str) or len(token)>4096 or any(ord(c)<33 for c in token):
        raise AgentConnectionError('本地连接凭证格式无效','invalid_config')
    if result['enabled'] and not result['revoked'] and not token:
        raise AgentConnectionError('本地连接凭证未配置','invalid_config')
    for key in ('runtime_dir','outbox_dir'):
        path=_text(result.get(key),key,4096)
        if not Path(path).is_absolute():raise AgentConnectionError('本机记忆路径必须为绝对路径','invalid_config')
        result[key]=str(Path(path).expanduser().resolve())
    return result

def _runtime_paths(*,python_path=None,bridge_path=None,hook_path=None):
    if sys.platform=='win32' and getattr(sys,'frozen',False) and python_path is None:
        install=Path(sys.executable).resolve().parent
        # The GUI exe is windowed and has no stdio. The two console bundles are
        # independent and keep their own _internal runtime directories.
        return (None,Path(bridge_path).resolve() if bridge_path else install/'bridge/LoveHouseBridge.exe',
                Path(hook_path).resolve() if hook_path else install/'hook/LoveHouseHook.exe',
                {'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1'})
    source=Path(__file__).resolve().parents[2]
    contents=next((p for p in Path(__file__).resolve().parents if p.name=='Contents'),None)
    if contents:
        resources=contents/'Resources'
        defaults=(resources/'python/bin/python3.12',resources/'backend/agent_memory_bridge.py',resources/'backend/agent_memory_hook.py')
        environment={'PYTHONHOME':str(resources/'python')}
    else:
        defaults=(Path(sys.executable).resolve(),source/'desktop/agent_memory_bridge.py',source/'desktop/agent_memory_hook.py')
        environment={}
    selected=[Path(value).expanduser().resolve() if value is not None else default
              for value,default in zip((python_path,bridge_path,hook_path),defaults)]
    environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    return (*selected,environment)

def make_agent_config(root,connection_secret,*,python_path=None,bridge_path=None,hook_path=None,persist=False):
    """Build a standard MCP configuration; only persist=True writes the private token file.

    The returned public code has paths, not a model/vendor key or a local token.
    Calling again with enabled=False/revoked=True also stops offline collection.
    """
    if type(persist) is not bool:raise AgentConnectionError('persist须为布尔值','invalid_config')
    root=Path(root).expanduser().resolve();c=connection_secret
    if not isinstance(c,dict):raise AgentConnectionError('连接配置须为对象','invalid_config')
    cid=c.get('id',c.get('connection_id'));library=c.get('library_id')
    if not isinstance(cid,str) or not _ID.fullmatch(cid):raise AgentConnectionError('连接编号无效','invalid_config')
    revision=c.get('binding_revision',0)
    if type(revision) is not int or not 0<=revision<=2147483647:raise AgentConnectionError('窗口绑定版本无效','invalid_config')
    private=root/'agent-connections'/(cid+(('.binding-'+str(revision)) if revision else '')+'.json')
    value=validate_config({'schema':SCHEMA,'connection_id':cid,'library_id':library,
      'token':c.get('token',''),'runtime_dir':str(root/'.runtime'),'outbox_dir':str(root/'agent-outbox'/cid/(('binding-'+str(c['binding_revision'])) if c.get('binding_revision',0) else '')),
      'enabled':bool(c.get('enabled',True)),'revoked':bool(c.get('revoked',False)),
      'session_scope':c.get('session_scope','connection'),'session_scope_policy':c.get('session_scope_policy',c.get('session_scope','connection')),
      'binding_revision':c.get('binding_revision',0),'bound_session_id':c.get('bound_session_id')})
    scope_conflict=False
    def preserve_local_claim():
        nonlocal value,scope_conflict
        candidates=[root/'agent-connections'/(cid+'.json'),*private.parent.glob(cid+'.binding-*.json')]
        previous=None
        for candidate in set(candidates):
            if not candidate.exists():continue
            item=validate_config(_read_json(candidate,MAX_CONFIG))
            if item['connection_id']!=cid or item['library_id']!=library:
                raise AgentConnectionError('既有本机配置属于另一个记忆身份，未覆盖','invalid_config')
            if previous is None or item['binding_revision']>previous['binding_revision']:previous=item
        if previous is None:return
        if previous['binding_revision']>value['binding_revision']:
            raise AgentConnectionError('连接绑定版本已更新；请刷新连接配置，未恢复旧凭据','scope_conflict')
        if previous['binding_revision']<value['binding_revision']:return
        local=previous['bound_session_id']
        if local:
            if value['bound_session_id'] not in (None,local):
                scope_conflict=True
            value['session_scope']=previous['session_scope'] if previous['session_scope']!='any' else 'next_session'
            value['session_scope_policy']=value['session_scope']
            value['bound_session_id']=local
        value=validate_config(value)
    if persist:
        # The first real hook claim and app-side enable/revoke/config refresh
        # serialize on this SAME lock. A server ACK can never erase the claim.
        with _spool_lock(private.parent):
            preserve_local_claim()
            # Old host processes retain their old config path. Never let them
            # read the new credential and claim the newly selected window.
            for old_path in [private.parent/(cid+'.json'),*private.parent.glob(cid+'.binding-*.json')]:
                if old_path==private or not old_path.exists():continue
                old=validate_config(_read_json(old_path,MAX_CONFIG))
                if old['binding_revision']<revision:
                    _atomic_json(old_path,{**old,'enabled':False,'revoked':True,'token':''})
            _atomic_json(private,value)
    else:preserve_local_claim()
    python,bridge,hook,environment=_runtime_paths(python_path=python_path,bridge_path=bridge_path,hook_path=hook_path)
    command={'command':str(python or bridge),'args':(['-s','-u',str(bridge)] if python else [])+['--connection-config',str(private)],'env':environment}
    mcp={'mcpServers':{'love-house-memory-'+cid[-8:]:command}}
    hook_config={'command':str(python or hook),'args':(['-s','-u',str(hook)] if python else [])+['--connection-config',str(private)],
      'env':environment,'stdin_format':'JSON','event_schema':HOOK_SCHEMA,
      'example':{'session_id':'宿主提供的稳定会话ID','turn_id':'宿主提供的真实轮次ID','status':'complete','user':'真实用户原话','assistant':'真实助手回复'},
      'requires_host_turn_end_hook':True,'copies_model_credentials':False}
    hook_config['matcher']='.*'
    validate_hook_matcher(hook_config['matcher'])
    return {'private_path':str(private),'mcp_config':mcp,'hook_config':hook_config,
      'connection_config_public':{'schema':SCHEMA,'connection_id':cid,'library_id':library,
        'enabled':value['enabled'],'revoked':value['revoked'],'capture_mode':'tools_only_until_host_hook',
        'session_scope':value['session_scope'],'session_scope_policy':value['session_scope_policy'],'binding_revision':value['binding_revision'],
        'bound_session_id':value['bound_session_id'],'scope_conflict':scope_conflict,
        'window_only':value['session_scope']!='any',
        'model_api_key_required':False,'transport':'local-mcp-stdio','automatic_reconnect':True},
      'persisted':persist,'supported':True,'requires_host_hook_for_automatic_capture':True}

def validate_hook_matcher(matcher):
    """Use a real match-all regex; host wildcard extensions are not portable."""
    if not isinstance(matcher,str) or len(matcher)>512:
        raise AgentConnectionError('Hook matcher须为长度不超过512的正则表达式','invalid_matcher')
    try:re.compile(matcher)
    except re.error:
        raise AgentConnectionError('Hook matcher正则无效；匹配全部请使用 .*，不要使用裸 *','invalid_matcher') from None
    return matcher

def connection_config_diagnostic(path,code='invalid_file'):
    """Public startup diagnostics contain paths and actions, never file contents."""
    selected=Path(path).expanduser().absolute()
    expected_dir=(Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'LoveHouse/agent-connections'
                  if sys.platform=='win32' else Path.home()/'Library/Application Support/LoveHouse/agent-connections'
                  if sys.platform=='darwin' else Path.home()/'.local/share/LoveHouse/agent-connections')
    missing=not selected.is_file()
    return {'schema':'love-house-connection-diagnostic/v1','status':'error',
      'code':'connection_config_not_found' if missing else code,'config_path':str(selected),
      'expected_directory':str(expected_dir),'next_action':'copy_connection_config_path',
      'message':'连接配置不存在；程序安装目录与用户数据目录不同。' if missing else '连接配置不可读或版本不支持；原文件未覆盖。',
      'repair':'打开爱之屋 → 连接 → 此Agent连接 → 复制连接配置完整路径；用生成的MCP片段替换手写路径，信任连接器后重试。'}

def configure_workbuddy(root,connection_secret,*,apply=False,home=None):
    """Merge only this MCP entry. Never create WorkBuddy/CodeBuddy hooks settings."""
    if type(apply) is not bool:raise AgentConnectionError('apply须为布尔值','invalid_input')
    bundle=make_agent_config(root,connection_secret,persist=False)
    home=Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    folder=home/'.workbuddy';target=folder/'mcp.json'
    plan={'supported':True,'host':'workbuddy','config_path':str(target),'private_path':bundle['private_path'],
      'mcp_config':bundle['mcp_config'],'applied':False,'readback_verified':False,
      'hook_supported':False,'hook_support_status':'desktop_user_hooks_unverified','requires_trust':True,
      'restart_if_tools_missing':True,'expected_tool_count':10,'tools_loaded':None,
      'next_steps':['打开 WorkBuddy → 连接器 → 自定义连接器，确认并信任此爱之屋连接器。',
                    '在目标会话调用 memory_status 验证工具已加载；如看不到工具，完全退出并重启 WorkBuddy 后新建会话重试。',
                    '这里只安装 MCP 工具；WorkBuddy 桌面用户 Hook 尚未验证。不会修改 settings.json，也不能据此宣称每轮自动存档。']}
    plan['configure_endpoint']='/api/connections/'+str(connection_secret.get('id',connection_secret.get('connection_id')))+'/workbuddy/configure'
    if not apply:
        plan['config_exists']=target.is_file()
        if target.is_file() and not target.is_symlink() and not folder.is_symlink():
            try:
                actual=_read_json(target,1024*1024)
                name,entry=next(iter(bundle['mcp_config']['mcpServers'].items()))
                plan['readback_verified']=isinstance(actual.get('mcpServers'),dict) and actual['mcpServers'].get(name)==entry
            except AgentConnectionError:plan['configuration_error']='invalid_file'
        return plan
    if not bundle['connection_config_public']['enabled'] or bundle['connection_config_public']['revoked']:
        raise AgentConnectionError('连接已暂停或断开，未安装宿主配置','paused')
    if folder.is_symlink() or target.is_symlink():
        raise AgentConnectionError('WorkBuddy配置使用符号链接，请在宿主中手动合并生成的MCP配置','unsafe_config_path')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with _spool_lock(folder):
        existed=target.exists()
        try:raw=target.read_bytes() if existed else b''
        except OSError:raise AgentConnectionError('WorkBuddy配置不可读，原文件未修改','invalid_file') from None
        if len(raw)>1024*1024:raise AgentConnectionError('WorkBuddy配置超过1MiB，请在宿主中手动配置','invalid_file')
        try:old=json.loads(raw.decode('utf-8-sig'),parse_constant=_constant,object_pairs_hook=_unique) if existed else {}
        except (ValueError,UnicodeError,RecursionError):raise AgentConnectionError('WorkBuddy配置JSON无效，原文件未修改','invalid_file') from None
        if not isinstance(old,dict) or not isinstance(old.get('mcpServers',{}),dict):
            raise AgentConnectionError('WorkBuddy mcpServers须为对象，原文件未修改','invalid_file')
        expected=json.loads(_json(old));servers=expected.setdefault('mcpServers',{})
        name,entry=next(iter(bundle['mcp_config']['mcpServers'].items()))
        previous=servers.get(name)
        if previous is not None and previous!=entry:
            args=previous.get('args') if isinstance(previous,dict) else None
            owned=False
            if isinstance(args,list) and len(args)>=2 and args[-2]=='--connection-config' and isinstance(args[-1],str):
                previous_path=Path(args[-1]);current_path=Path(bundle['private_path'])
                cid=bundle['connection_config_public']['connection_id']
                owned=(previous_path.parent==current_path.parent and re.fullmatch(re.escape(cid)+r'(?:\.binding-\d+)?\.json',previous_path.name) is not None)
            if not owned:
                raise AgentConnectionError('同名MCP服务属于不同配置，未覆盖；请在WorkBuddy中核对','mcp_name_conflict')
        servers[name]=entry
        if (target.read_bytes() if target.exists() else b'')!=raw:
            raise AgentConnectionError('WorkBuddy配置刚被修改，请重试；原文件未覆盖','config_changed')
        backup=None
        if existed:
            backup=folder/('mcp.json.lovehouse-'+uuid.uuid4().hex+'.bak')
            with backup.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            backup.chmod(0o600)
        make_agent_config(root,connection_secret,persist=True)
        _atomic_json(target,expected)
        verified=_read_json(target,1024*1024)==expected
        if not verified:raise AgentConnectionError('WorkBuddy配置回读不一致，请检查备份并重新配置','readback_failed')
    return {**plan,'applied':True,'readback_verified':True,'backup_path':str(backup) if backup else None,
      'message':'MCP配置已写入并回读；仍需在WorkBuddy信任连接器并调用memory_status验证。'}

def _safe_url(value):
    value=_text(value,'source_url',4000)
    if any(c.isspace() or ord(c)<32 for c in value) or '\\' in value:raise AgentConnectionError('来源URL不能包含空白或控制字符','invalid_input')
    try:p=urlsplit(value);port=p.port
    except ValueError:raise AgentConnectionError('来源URL格式不正确','invalid_input') from None
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or (port is not None and not 1<=port<=65535):
        raise AgentConnectionError('来源URL须为无认证信息的HTTP/HTTPS地址','invalid_input')
    return p._replace(query='',fragment='').geturl()

def event_from_hook(data):
    """Keep only real role/result fields. Unknown host fields/credentials never enter the event."""
    if not isinstance(data,dict):raise AgentConnectionError('钩子输入须为JSON对象','invalid_input')
    sid=_text(data.get('session_id'),'session_id',200);rid=_text(data.get('turn_id',data.get('request_id')),'turn_id',200)
    status=data.get('status','complete')
    if status not in ('complete','partial'):raise AgentConnectionError('status须为complete或partial','invalid_input')
    kind=data.get('type','turn')
    if kind=='turn':
        normalized={'type':'turn','turn_id':rid,'status':status,'user':_text(data.get('user','' if status=='partial' else None),'user',empty=status=='partial'),
          'assistant':_text(data.get('assistant','' if status=='partial' else None),'assistant',empty=status=='partial'),'origin':'agent_host_hook'}
    elif kind=='tool':
        outcome=data.get('outcome','observed')
        if outcome not in ('observed','success','failed'):raise AgentConnectionError('工具结果状态无效','invalid_input')
        normalized={'type':'tool','turn_id':rid,'status':status,'text':_text(data.get('text',data.get('content')),'text',empty=status=='partial'),
                    'call_id':_text(data.get('call_id',rid),'call_id',200),'outcome':outcome,'origin':'agent_host_hook'}
        if data.get('source_url'):normalized['source_url']=_safe_url(data['source_url'])
    else:raise AgentConnectionError('钩子只接收turn或tool事件','invalid_input')
    eid='hook:'+rid
    if status=='partial':eid+=':partial:'+hashlib.sha256(_json(normalized).encode()).hexdigest()[:24]
    return {'session_id':sid,'event_id':eid,'event_type':'agent/host-'+kind,
      'record':{'schema':HOOK_SCHEMA},'normalized':normalized}

def event_from_tool(name,args):
    if not isinstance(args,dict):raise AgentConnectionError('工具参数须为对象','invalid_input')
    sid=_text(args.get('session_id'),'session_id',200);rid=_text(args.get('request_id'),'request_id',200)
    if name=='memory_record_turn':
        normalized={'type':'turn','turn_id':rid,'status':'complete','user':_text(args.get('user'),'user'),
                    'assistant':_text(args.get('assistant'),'assistant'),'origin':'manual_record'}
    elif name=='memory_event':
        outcome=args.get('outcome','observed')
        if outcome not in ('observed','success','failed'):raise AgentConnectionError('工具结果状态无效','invalid_input')
        normalized={'type':'tool','turn_id':rid,'status':'complete','text':_text(args.get('text'),'text'),
                    'call_id':rid,'outcome':outcome,'source_url':_safe_url(args.get('source_url')),'origin':'manual_record'}
    else:raise AgentConnectionError('此工具不能离线记录','invalid_input')
    record={'schema':TOOL_SCHEMA}
    for key in ('source_session_id','source_event_id'):
        if key in args:record[key]=_text(args[key],key,200)
    return {'session_id':sid,'event_id':'tool:'+name+':'+rid,'event_type':'agent/tool-'+name,
            'record':record,'normalized':normalized}

class AgentClient:
    def __init__(self,connection_config,*,timeout=8,poll_seconds=15,opener=None):
        self.path=Path(connection_config).expanduser().resolve()
        self.timeout=timeout;self.poll_seconds=max(.05,float(poll_seconds))
        self.opener=opener or build_opener(ProxyHandler({}),NoRedirects())
        self._drain_lock=threading.Lock();self._queue_lock=threading.Lock();self._stopping=threading.Event();self._thread=None
        self.config()
    def config(self):return validate_config(_read_json(self.path,MAX_CONFIG))
    @staticmethod
    def _enabled(c):return c['enabled'] and not c['revoked']
    def _require_enabled(self):
        c=self.config()
        if not self._enabled(c):raise AgentConnectionError('记忆连接已暂停或断开，未新增记录','paused')
        return c
    @staticmethod
    def _bound(c):
        return c.get('bound_session_id')
    def _scope_result(self,code):
        c=self.config()
        return {'accepted':False,'saved':False,'archive_committed':False,'local_queue_committed':False,'queued':False,
                'status':code,'code':code,'connection_id':c['connection_id'],'library_id':c['library_id'],
                'session_scope':c['session_scope'],'session_scope_policy':c['session_scope_policy'],
                'bound_session_id':self._bound(c),'binding_revision':c['binding_revision'],
                'next_action':'wait_for_source_adapter_binding' if code=='awaiting_window_binding' else 'use_bound_window',
                'message':'等待所选来源适配器的首轮完整对话绑定窗口；MCP手动补录不会占用窗口。' if code=='awaiting_window_binding' else '此记录属于其他窗口；请在已绑定窗口使用此连接。'}
    def _preflight_window(self,data,*,hook=False):
        """Reject foreign/undetermined input before normalizing any role text."""
        c=self._require_enabled()
        if c['session_scope']=='any':return None
        sid=data.get('session_id') if isinstance(data,dict) else None
        bound=self._bound(c)
        if bound:
            if sid!=bound:return self._scope_result('ignored_scope')
            return None
        eligible=(hook and isinstance(data,dict) and data.get('type','turn')=='turn'
                  and data.get('status','complete')=='complete'
                  and isinstance(sid,str) and bool(sid.strip()) and len(sid)<=200
                  and all(isinstance(data.get(k),str) and bool(data[k].strip()) for k in ('user','assistant')))
        return None if eligible else self._scope_result('awaiting_window_binding')
    def _scope_gate(self,c,event,*,claim=False):
        """Called under the config lock before ANY outbox serialization/write."""
        if c['session_scope']=='any':return c
        sid=_text(event.get('session_id'),'session_id',200)
        bound=self._bound(c)
        if bound:
            if sid!=bound:raise AgentConnectionError('本条来源不属于所配置窗口，未采集','ignored_scope')
            return c
        record=event.get('record') if isinstance(event.get('record'),dict) else {}
        normalized=event.get('normalized') if isinstance(event.get('normalized'),dict) else record.get('normalized',{})
        eligible=(record.get('schema')==HOOK_SCHEMA and isinstance(normalized,dict)
                  and normalized.get('type')=='turn' and normalized.get('status')=='complete'
                  and normalized.get('origin')=='agent_host_hook'
                  and all(isinstance(normalized.get(k),str) and bool(normalized[k].strip())
                          and len(normalized[k])<=40000 for k in ('user','assistant')))
        if not claim or not eligible:
            raise AgentConnectionError('等待所选窗口的第一轮完整宿主对话，未采集原文','awaiting_window_binding')
        for key in ('user','assistant'):_text(normalized[key],key,40000)
        _text(normalized.get('turn_id'),'turn_id',200)
        _text(event.get('event_id'),'event_id',300)
        c=validate_config({**c,'bound_session_id':sid})
        _atomic_json(self.path,c)
        return c
    @staticmethod
    def _alive(pid):
        if type(pid) is not int or not 0<pid<=2**31-1:return False
        if sys.platform=='win32':
            # os.kill is NOT a harmless liveness probe on Windows. Query only.
            import ctypes
            from ctypes import wintypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
            kernel.OpenProcess.restype=wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype=wintypes.BOOL
            kernel.CloseHandle.argtypes=[wintypes.HANDLE]
            handle=kernel.OpenProcess(0x1000,False,pid)
            if not handle:return False
            try:
                code=wintypes.DWORD()
                return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
            finally:kernel.CloseHandle(handle)
        try:os.kill(pid,0);return True
        except (OSError,OverflowError):return False
    def _read_response(self,response,url,maximum=8*1024*1024):
        if response.geturl()!=url:raise AgentConnectionError('记忆服务重定向已拒绝','redirect_blocked')
        raw=response.read(maximum+1)
        if len(raw)>maximum:raise AgentConnectionError('记忆响应超过上限','invalid_response')
        try:value=json.loads(raw,parse_constant=_constant,object_pairs_hook=_unique)
        except (ValueError,UnicodeError,RecursionError):raise AgentConnectionError('记忆服务返回无效JSON','invalid_response') from None
        if not isinstance(value,dict):raise AgentConnectionError('记忆服务返回结构不正确','invalid_response')
        return value
    def discover(self):
        c=self._require_enabled();runtime=Path(c['runtime_dir'])
        try:files=sorted(runtime.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:128]
        except OSError:files=[]
        for path in files:
            try:
                state=_read_json(path,MAX_CONFIG);port=state.get('controller_port',state.get('port'))
                if type(port) is not int or not 1<=port<=65535 or not self._alive(state.get('pid')):continue
                url=f'http://127.0.0.1:{port}/api/health'
                with self.opener.open(Request(url),timeout=min(2,self.timeout)) as response:health=self._read_response(response,url,65536)
                protocol=health.get('protocol_version',health.get('version',''))
                if health.get('ok') is True and health.get('name')=='爱之屋记忆服务' and isinstance(protocol,str) and re.fullmatch(r'0\.4\.\d+(?:[-+][A-Za-z0-9.]+)?',protocol):return port
            except (AgentConnectionError,OSError,ValueError,URLError,HTTPException):continue
        raise AgentConnectionError('爱之屋尚未打开或服务未就绪；打开后会自动重新发现','offline')
    def _post(self,action,body,*,port=None):
        c=self._require_enabled();port=self.discover() if port is None else port
        if type(port) is not int or not 1<=port<=65535:raise AgentConnectionError('仅支持本机记忆服务端口','invalid_config')
        encoded=_json(body).encode('utf-8')
        if len(encoded)>MAX_EVENT:raise AgentConnectionError('单条记忆超过32MiB，请按真实事件拆分','input_too_large')
        url=f"http://127.0.0.1:{port}/api/connections/{c['connection_id']}/{action}"
        request=Request(url,data=encoded,headers={'Authorization':'Bearer '+c['token'],'Content-Type':'application/json'},method='POST')
        try:
            with self.opener.open(request,timeout=self.timeout) as response:result=self._read_response(response,url)
        except HTTPError as exc:
            raise AgentConnectionError('记忆服务未接受连接或记录（HTTP '+str(exc.code)+'）；原待发送记录已保留','event_conflict' if exc.code==409 else 'connection_rejected') from None
        except AgentConnectionError:raise
        except (OSError,URLError,TimeoutError,HTTPException):raise AgentConnectionError('本机记忆服务暂不可达，等待自动重连','offline') from None
        if result.get('error'):raise AgentConnectionError('记忆服务未完成请求，未宣称保存成功','service_error')
        return result
    def heartbeat(self):return self._post('heartbeat',{'adapter_version':'love-house-agent-memory/1','host_version':'generic-local-agent'})
    def tool(self,name,arguments=None):
        if name in ('memory_record_turn','memory_event'):return self.submit_tool_record(name,arguments or {})
        if name in ('memory_remember','memory_persona_import'):
            ignored=self._preflight_window(arguments or {})
            if ignored:return ignored
        return self._post('tool',{'name':name,'arguments':arguments or {}})
    def pending_count(self):
        try:return len(list(Path(self.config()['outbox_dir']).glob('*.json')))
        except (AgentConnectionError,OSError):return 0
    def _enqueue(self,event):
        try:return self._enqueue_impl(event)
        except OSError:raise AgentConnectionError('本机待发送队列无法落盘，未宣称保存成功','outbox_io_error') from None
        except (TypeError,ValueError) as exc:
            if isinstance(exc,AgentConnectionError):raise
            raise AgentConnectionError('记录必须是可保存的JSON事件','invalid_input') from None
    def _enqueue_impl(self,event):
        if not isinstance(event,dict):raise AgentConnectionError('记录须为JSON对象','invalid_input')
        with self._queue_lock,_spool_lock(self.path.parent):
            c=self._scope_gate(self._require_enabled(),event,claim=True)
            payload=_json(event)
            if len(payload.encode())>MAX_EVENT:raise AgentConnectionError('单事件过大，未写入队列','input_too_large')
            identity=_json([c['connection_id'],event.get('session_id'),event.get('event_id')])
            key=hashlib.sha256(identity.encode()).hexdigest();digest=hashlib.sha256(payload.encode()).hexdigest();path=Path(c['outbox_dir'])/(key+'.json')
            with _spool_lock(path.parent):
                self._require_enabled()
                if path.exists():
                    old=_read_json(path,MAX_EVENT+MAX_CONFIG)
                    if old.get('payload_hash')!=digest:raise AgentConnectionError('同一轮次ID已用于不同原文，旧记录未覆盖','event_conflict')
                    return key
                folder=path.parent;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                existing=list(folder.glob('*.json'))
                if len(existing)>=MAX_QUEUE_EVENTS or sum(p.stat().st_size for p in existing)+len(payload.encode())>MAX_QUEUE_BYTES:
                    raise AgentConnectionError('本地待发送队列已满，未宣称记录成功，请先启动爱之屋','outbox_full')
                _atomic_json(path,{'schema':'love-house-agent-outbox/v1','connection_id':c['connection_id'],
                          'library_id':c['library_id'],'payload_hash':digest,'event':event,'created':time.time()})
        return key
    def drain(self,*,limit=50):
        if type(limit) is not int or not 1<=limit<=1000:raise AgentConnectionError('待发送批数无效','invalid_input')
        if not self._drain_lock.acquire(False):return {'status':'busy','accepted':{},'pending':self.pending_count()}
        try:
            try:c=self._require_enabled();port=self.discover()
            except AgentConnectionError as exc:return {'status':exc.code,'accepted':{},'pending':self.pending_count()}
            accepted={}
            folder=Path(c['outbox_dir'])
            try:files=sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime)[:limit]
            except OSError:files=[]
            error=None
            for path in files:
                try:
                    # Re-read enable/token for every delivery, including after user pause.
                    current=self._require_enabled()
                    if not path.exists():continue
                    item=_read_json(path,MAX_EVENT+MAX_CONFIG)
                    if item.get('schema')!='love-house-agent-outbox/v1' or item.get('connection_id')!=current['connection_id'] or item.get('library_id')!=current['library_id']:
                        raise AgentConnectionError('待发送记录身份不匹配，未提交','invalid_outbox')
                    event=item.get('event')
                    if not isinstance(event,dict) or hashlib.sha256(_json(event).encode()).hexdigest()!=item.get('payload_hash'):
                        raise AgentConnectionError('待发送记录校验失败，未提交','invalid_outbox')
                    self._scope_gate(current,event,claim=False)
                    result=self._post('events',event,port=port)
                    if result.get('accepted') is not True:
                        code=result.get('code',result.get('status'))
                        raise AgentConnectionError('服务未确认此窗口原文落盘，待发送记录保留',code if code in ('scope_conflict','ignored_scope','awaiting_window_binding') else 'not_accepted')
                    # Compare before unlink so a changed local file cannot be silently discarded.
                    with _spool_lock(folder):
                        if path.exists():
                            if _read_json(path,MAX_EVENT+MAX_CONFIG).get('payload_hash')!=item['payload_hash']:
                                raise AgentConnectionError('待发送文件已变化，未清理','event_conflict')
                            path.unlink()
                    accepted[path.stem]=result
                except AgentConnectionError as exc:
                    error=exc.code
                    if exc.code in ('event_conflict','invalid_outbox','invalid_file'):continue
                    break
                except OSError:error='outbox_io_error';break
            return {'status':error or 'delivered','accepted':accepted,'pending':self.pending_count()}
        finally:self._drain_lock.release()
    def submit_event(self,event):
        try:key=self._enqueue(event)
        except AgentConnectionError as exc:
            if exc.code in ('awaiting_window_binding','ignored_scope'):return self._scope_result(exc.code)
            raise
        delivery=self.drain();accepted=delivery.get('accepted',{}).get(key)
        if accepted:
            return {**accepted,'saved':accepted.get('status') in ('saved','stored'),
                    'archive_committed':accepted.get('status')!='forgotten','local_queue_committed':True,'queued':False,'forgotten':accepted.get('status')=='forgotten'}
        return {'accepted':False,'saved':False,'archive_committed':False,'local_queue_committed':True,
                'queued':True,'status':'queued_offline' if delivery.get('status')=='offline' else 'queued',
                'reason':delivery.get('status'),'pending':delivery.get('pending',self.pending_count())}
    def submit_hook(self,data):
        ignored=self._preflight_window(data,hook=True)
        return ignored if ignored else self.submit_event(event_from_hook(data))
    def submit_tool_record(self,name,args):
        ignored=self._preflight_window(args)
        return ignored if ignored else self.submit_event(event_from_tool(name,args))
    def status(self):
        c=self.config()
        public={'library_id':c['library_id'],'connection_id':c['connection_id'],'capture_mode':'tools_only_until_host_hook',
                'pending':self.pending_count(),'model_api_key_required':False,'enabled':c['enabled'],'revoked':c['revoked'],
                'session_scope':c['session_scope'],'session_scope_policy':c['session_scope_policy'],
                'binding_revision':c['binding_revision'],'bound_session_id':self._bound(c),'window_only':c['session_scope']!='any'}
        if not self._enabled(c):return {**public,'connected':False,'status':'paused'}
        try:
            remote=self.tool('memory_status',{})
            connection=remote.get('connection') or {}
            server_scope=remote.get('session_scope') or connection.get('session_scope')
            server_bound=remote.get('bound_session_id') or connection.get('bound_session_id')
            if not server_bound and server_scope not in (None,'any','fixed','connection','next_session'):server_bound=server_scope
            conflict=bool(self._bound(c) and server_bound and server_bound!=self._bound(c))
            return {**public,**remote,'connected':True,'local_bound_session_id':self._bound(c),
                    'scope_conflict':conflict,'server_session_scope':server_scope}
        except AgentConnectionError as exc:return {**public,'connected':False,'status':exc.code}
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._stopping.clear()
        def work():
            while not self._stopping.is_set():
                try:
                    if self._enabled(self.config()):self.heartbeat();self.drain()
                except AgentConnectionError:pass
                if self._stopping.wait(self.poll_seconds):break
        self._thread=threading.Thread(target=work,daemon=True,name='agent-memory-reconnect');self._thread.start()
    def stop(self):
        self._stopping.set()
        if self._thread and self._thread is not threading.current_thread():self._thread.join(timeout=min(2,self.timeout))
