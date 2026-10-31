from __future__ import annotations
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import time
import threading
import uuid
from pathlib import Path
from contextlib import contextmanager
from ..errors import ValidationError

class ConnectionStore:
    """Connection bindings and a durable receipt/outbox journal, independent of graph decay."""
    def __init__(self,root):
        self.binding_lock=threading.RLock()
        self.path=Path(root)/'capture.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY,name TEXT,host TEXT,library_id TEXT,
              session_scope TEXT,token TEXT,enabled INTEGER,revoked INTEGER,created REAL,last_received REAL,
              archive_status TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,connection_id TEXT,library_id TEXT,
              session_id TEXT,kind TEXT,status TEXT,payload TEXT,payload_hash TEXT,received REAL,
              attempts INTEGER DEFAULT 0,error TEXT,applied REAL,node_ids TEXT);
            CREATE INDEX IF NOT EXISTS receipts_pending ON receipts(status,received);
            CREATE TABLE IF NOT EXISTS forgotten_texts(library_id TEXT,hash TEXT,PRIMARY KEY(library_id,hash));
            ''')
            fields={r['name'] for r in db.execute('PRAGMA table_info(connections)')}
            for field in ('host_seen','configured_at'):
                if field not in fields:db.execute(f'ALTER TABLE connections ADD COLUMN {field} REAL')
            if 'host_options' not in fields:db.execute('ALTER TABLE connections ADD COLUMN host_options TEXT')
            for field,kind in (('session_scope_policy','TEXT'),('bound_session_id','TEXT'),('binding_revision','INTEGER NOT NULL DEFAULT 0')):
                if field not in fields:db.execute(f'ALTER TABLE connections ADD COLUMN {field} {kind}')
            # Upgrade the old overloaded field without changing a chosen window.
            db.execute("""UPDATE connections SET
                bound_session_id=CASE WHEN session_scope NOT IN ('connection','any','next_session','fixed') THEN session_scope ELSE bound_session_id END,
                session_scope_policy=CASE WHEN session_scope IN ('connection','any') THEN 'any' WHEN session_scope='next_session' THEN 'next_session' ELSE 'fixed' END
                WHERE session_scope_policy IS NULL""")
            db.execute('UPDATE connections SET session_scope=session_scope_policy')
            if 'last_recall' not in fields:db.execute('ALTER TABLE connections ADD COLUMN last_recall TEXT')
            receipt_fields={r['name'] for r in db.execute('PRAGMA table_info(receipts)')}
            for field,kind in (('semantic_type','TEXT'),('is_automatic','INTEGER'),('source_schema','TEXT'),('binding_revision','INTEGER NOT NULL DEFAULT 0')):
                if field not in receipt_fields:db.execute(f'ALTER TABLE receipts ADD COLUMN {field} {kind}')
            # Classify existing receipts once. Original payloads/hashes/IDs remain
            # untouched; future status polling does not reparse private texts.
            for row in db.execute('SELECT id,payload FROM receipts WHERE semantic_type IS NULL OR is_automatic IS NULL'):
                semantic_type,automatic=self._payload_semantics(row['payload'])
                db.execute('UPDATE receipts SET semantic_type=?,is_automatic=? WHERE id=?',
                           (semantic_type,int(automatic),row['id']))
            for row in db.execute('SELECT id,payload FROM receipts WHERE source_schema IS NULL'):
                try:
                    payload=json.loads(row['payload']);record=payload.get('record') or {}
                    schema=record.get('schema','') if isinstance(record,dict) else ''
                except (ValueError,TypeError,AttributeError):schema=''
                db.execute('UPDATE receipts SET source_schema=? WHERE id=?',(schema,row['id']))
            db.execute('CREATE INDEX IF NOT EXISTS receipts_capture_state ON receipts(connection_id,status,semantic_type,is_automatic)')
            db.execute('CREATE INDEX IF NOT EXISTS receipts_library_pending ON receipts(library_id,status,received)')
        self.path.chmod(0o600)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db: yield db
        finally:db.close()
    @staticmethod
    def _payload_semantics(payload):
        try:
            event=json.loads(payload) if isinstance(payload,str) else payload
            if not isinstance(event,dict):return '',False
            record=event.get('record') if isinstance(event.get('record'),dict) else {}
            normalized=event.get('normalized') or record.get('normalized') or event
            if not isinstance(normalized,dict):return '',False
            kind=normalized.get('type')
            if kind not in ('turn','tool','output','persona_import') or normalized.get('status','complete')!='complete':kind=''
            automatic=record.get('schema') in ('deepseek-harness-event/v1','love-house-agent-hook/v1',
                                                'neural-api-proxy/v1','neural-api-tool/v1')
            return kind,bool(automatic)
        except (ValueError,TypeError,RecursionError):return '',False
    def _capture(self,cid,revision=0):
        # Event schema is an assertion by the sender, not proof of an installed
        # adapter. In generic Agent mode only a server-confirmed Harness setup
        # from before receipt can make Harness records eligible for automation.
        eligible="""((source_schema='deepseek-harness-event/v1' AND
            (connections.host='harness' OR (connections.host='agent' AND
             connections.configured_at IS NOT NULL AND connections.configured_at<=receipts.received))) OR
            (connections.host='api' AND source_schema IN ('neural-api-proxy/v1','neural-api-tool/v1')))"""
        with self.db() as db:
            # Registered source IDs are issued by the management API and checked
            # on every receive. Their adapters use the generic Hook wire schema,
            # but unrelated MCP clients cannot become registered by naming it.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_sources'").fetchone():
                eligible += """ OR (source_schema='love-house-agent-hook/v1' AND EXISTS
                    (SELECT 1 FROM agent_sources WHERE agent_sources.connection_id=connections.id
                     AND agent_sources.library_id=connections.library_id))"""
            eligible='('+eligible+')'
            row=db.execute(f'''SELECT
              SUM(CASE WHEN status='saved' AND semantic_type='turn' THEN 1 ELSE 0 END) complete_dialogues_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='turn' AND is_automatic=1 AND {eligible} THEN 1 ELSE 0 END) automatic_dialogues_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='tool' THEN 1 ELSE 0 END) tool_observations_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='tool' AND is_automatic=1 AND {eligible} THEN 1 ELSE 0 END) automatic_tool_observations_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='output' THEN 1 ELSE 0 END) outputs_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='output' AND is_automatic=1 AND {eligible} THEN 1 ELSE 0 END) automatic_outputs_saved,
              SUM(CASE WHEN status='archived' THEN 1 ELSE 0 END) raw_events_only,
              SUM(CASE WHEN status IN ('pending','retry') THEN 1 ELSE 0 END) pending_records,
              MAX(CASE WHEN status='saved' AND semantic_type='output' THEN applied END) last_output_at,
              MAX(CASE WHEN status='saved' AND semantic_type='turn' THEN applied END) last_dialogue_at,
              SUM(CASE WHEN source_schema='love-house-agent-hook/v1' AND status!='forgotten' THEN 1 ELSE 0 END) hook_event_count,
              SUM(CASE WHEN source_schema='love-house-agent-hook/v1' AND status='saved' AND semantic_type='turn' THEN 1 ELSE 0 END) hook_dialogues_saved,
              MAX(CASE WHEN source_schema='love-house-agent-hook/v1' AND status!='forgotten' THEN received END) last_hook_at
              FROM receipts JOIN connections ON connections.id=receipts.connection_id
              WHERE connection_id=? AND receipts.binding_revision=?''',(cid,revision)).fetchone()
        result={k:(row[k] if k in ('last_dialogue_at','last_output_at','last_hook_at') else int(row[k] or 0)) for k in row.keys()}
        # Caller-controlled events cannot attest that a host installed/enabled hooks.
        result['auto_streak']=0
        return result
    def record_recall(self,cid,coverage):
        """Metadata for the returned material only, never a query or transcript."""
        if (not isinstance(coverage,dict) or any(type(coverage.get(k)) is not int or not 0<=coverage[k]<=1000
                for k in ('organized','raw','other'))):
            raise ValidationError('召回统计格式不正确')
        value={'at':time.time(),'organized_count':coverage['organized'],
               'source_count':coverage['raw'],'other_count':coverage['other']}
        with self.db() as db:
            db.execute('UPDATE connections SET last_recall=? WHERE id=? AND enabled=1 AND revoked=0',
                       (json.dumps(value,separators=(',',':')),cid))
    def public(self,row):
        result=dict(row);result.pop('token',None)
        result.pop('host_options',None)
        encoded=result.pop('last_recall',None);last=None
        try:
            item=json.loads(encoded) if encoded else None
            if (isinstance(item,dict) and type(item.get('at')) in (int,float) and math.isfinite(item['at']) and item['at']>=0
                    and all(type(item.get(k)) is int and 0<=item[k]<=1000
                            for k in ('organized_count','source_count','other_count'))):
                last={k:item[k] for k in ('at','organized_count','source_count','other_count')}
        except (TypeError,ValueError):pass
        result['last_recall']=last
        result['enabled']=bool(result['enabled']);result['revoked']=bool(result['revoked'])
        result['archive_status']=result['archive_status'] or 'waiting'
        capture=self._capture(result['id'],result.get('binding_revision',0));result['capture']=capture
        if not result['revoked']:
            # A completed tool result proves automatic observation capture, not
            # that a human/assistant conversation pair has reached the graph.
            if capture['automatic_dialogues_saved']:result['archive_status']='automatic_connected'
            elif capture['automatic_outputs_saved']:result['archive_status']='outputs_only'
            elif capture['hook_dialogues_saved']:result['archive_status']='host_reported'
            elif capture['automatic_tool_observations_saved']:result['archive_status']='observations_only'
            elif capture['complete_dialogues_saved'] or capture['tool_observations_saved'] or capture['outputs_saved']:result['archive_status']='tools_only'
            elif result['archive_status'] in ('automatic_connected','host_reported','observations_only','outputs_only','tools_only'):result['archive_status']='waiting'
        active=result['enabled'] and not result['revoked']
        result.update(can_read=active,can_write=bool(active and (result['host']!='agent' or result['session_scope']=='any' or result.get('bound_session_id'))),
                      memory_only=result['host']=='agent',automatic_memory=bool(active and result['archive_status'] in ('automatic_connected','outputs_only')))
        result['read_only']=not result['can_write']
        result['capture_mode']=('host_hook_received' if capture['hook_event_count'] else 'tools_only') if not result['automatic_memory'] else 'adapter_events_received'
        result['binding_state']='bound' if result.get('bound_session_id') else 'all_sessions' if result['session_scope']=='any' else 'awaiting_source_turn'
        result['last_received_at']=result.pop('last_received',None)
        result['host_seen_at']=result.pop('host_seen',None)
        result['host_online']=bool(result['host_seen_at'] and time.time()-result['host_seen_at']<65 and result['enabled'] and not result['revoked'])
        return result
    def create(self,name,host,library_id,session_scope='connection'):
        if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValidationError('连接名称须为1~80字')
        if host not in ('harness','api','agent'):raise ValidationError('连接方式须为harness、agent或api')
        if not isinstance(session_scope,str) or not session_scope.strip() or len(session_scope)>200:raise ValidationError('会话范围不合法')
        cid='conn_'+uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        policy='any' if session_scope in ('connection','any') else 'next_session' if session_scope=='next_session' else 'fixed'
        bound=session_scope if policy=='fixed' else None
        if bound=='fixed':raise ValidationError('固定窗口必须指定真实会话标识')
        with self.db() as db:
            db.execute('INSERT INTO connections(id,name,host,library_id,session_scope,token,enabled,revoked,created,last_received,archive_status,error,session_scope_policy,bound_session_id) VALUES(?,?,?,?,?,?,1,0,?,NULL,?,NULL,?,?)',
                       (cid,name.strip(),host,library_id,policy,token,time.time(),'waiting',policy,bound))
        return self.get(cid)
    def heartbeat(self,cid,data):
        for key in ('host_version','adapter_version','bound_session_id'):
            if key in data and (not isinstance(data[key],str) or len(data[key])>200):raise ValidationError('宿主状态字段不正确')
        with self.db() as db:db.execute('UPDATE connections SET host_seen=?,error=NULL WHERE id=?',(time.time(),cid))
        return {'ok':True,'host_online':True,'archive_status':self.get(cid)['archive_status']}
    def host_options(self,cid):
        row=self.get(cid,secret=True)
        value=json.loads(row.get('host_options') or '{}')
        return value if isinstance(value,dict) else {}
    def configured(self,cid,host_options=None):
        with self.db() as db:
            if host_options is None:db.execute('UPDATE connections SET configured_at=? WHERE id=?',(time.time(),cid))
            else:db.execute('UPDATE connections SET configured_at=?,host_options=? WHERE id=?',
                            (time.time(),json.dumps(host_options,ensure_ascii=False),cid))
    def get(self,cid,secret=False):
        with self.db() as db:r=db.execute('SELECT * FROM connections WHERE id=?',(cid,)).fetchone()
        if r is None:raise ValidationError('连接不存在')
        return dict(r) if secret else self.public(r)
    def list(self,library_id=None):
        with self.db() as db:
            rows=db.execute('SELECT * FROM connections'+(' WHERE library_id=?' if library_id else '')+' ORDER BY created',
                            (library_id,) if library_id else ()).fetchall()
        return [self.public(r) for r in rows]
    def authenticate(self,cid,token):
        r=self.get(cid,secret=True)
        if r['revoked'] or not r['enabled']:raise ValidationError('连接已暂停或断开')
        if not isinstance(token,str) or not hmac.compare_digest(r['token'],token):raise ValidationError('连接凭证不正确')
        return r
    def authorize_session(self,cid,sid):
        if not isinstance(sid,str) or not sid or len(sid)>200:raise ValidationError('缺少稳定会话标识')
        with self.binding_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT session_scope,bound_session_id FROM connections WHERE id=?',(cid,)).fetchone()
            if row is None:raise ValidationError('连接不存在')
            scope=row['session_scope']
            if scope=='any':return
            if row['bound_session_id']:
                if row['bound_session_id']!=sid:raise ValidationError('此连接绑定了另一对话窗口，未保存当前会话')
            elif scope=='next_session':
                db.execute('UPDATE connections SET bound_session_id=? WHERE id=?',(sid,cid))
            else:
                raise ValidationError('此连接绑定了另一对话窗口，未保存当前会话')
    @staticmethod
    def adapter_scope(connection):
        """Legacy host plugins receive the effective scope, never a policy as an ID."""
        return connection.get('bound_session_id') or ('connection' if connection['session_scope']=='any' else 'next_session')
    def rebind(self,cid,data):
        if not isinstance(data,dict) or set(data)-{'confirm','expected_bound_session_id'} or data.get('confirm') is not True or 'expected_bound_session_id' not in data:
            raise ValidationError('请确认重新绑定并提供当前窗口标识；已有记忆会保留，旧连接配置将失效')
        with self.binding_lock,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM connections WHERE id=?',(cid,)).fetchone()
            if row is None or row['host']!='agent' or row['revoked']:raise ValidationError('仅可重新绑定未断开的通用Agent连接')
            if row['bound_session_id']!=data['expected_bound_session_id']:raise ValidationError('窗口绑定已变更，请刷新后重新确认')
            db.execute("UPDATE connections SET session_scope='next_session',session_scope_policy='next_session',bound_session_id=NULL,binding_revision=binding_revision+1,token=?,host_seen=NULL,configured_at=NULL,last_received=NULL,archive_status='waiting',error=NULL WHERE id=?",(secrets.token_urlsafe(32),cid))
        return self.get(cid)
    def toggle(self,cid,enabled,disconnect=False):
        if type(enabled) is not bool:raise ValidationError('enabled必须是布尔值')
        self.get(cid)
        with self.db() as db:
            if disconnect:db.execute('UPDATE connections SET enabled=0,revoked=1,token=?,archive_status=? WHERE id=?',('', 'waiting',cid))
            else:db.execute('UPDATE connections SET enabled=? WHERE id=? AND revoked=0',(int(enabled),cid))
        return self.get(cid)
    def status(self,cid,status=None,error=None):
        with self.db() as db:
            if status:db.execute('UPDATE connections SET archive_status=?,error=? WHERE id=?',(status,error,cid))
            else:db.execute('UPDATE connections SET error=? WHERE id=?',(error,cid))
    def receive(self,connection,event):
        with self.binding_lock:
            self.authenticate(connection['id'],connection['token'])
            return self._receive(connection,event)
    @staticmethod
    def _receipt_key(cid,sid,event_id,revision=0):
        parts=[cid,sid,str(event_id)]
        if revision:parts.append(revision)
        return hashlib.sha256(json.dumps(parts,ensure_ascii=False).encode()).hexdigest()
    def _receive(self,connection,event):
        if not isinstance(event,dict):raise ValidationError('事件必须是对象')
        original=json.dumps(event,ensure_ascii=False,sort_keys=True,allow_nan=False)
        original_digest=hashlib.sha256(original.encode()).hexdigest()
        # Exact old role texts are not stored again through a client's repeated history.
        with self.db() as db:blocked={r[0] for r in db.execute('SELECT hash FROM forgotten_texts WHERE library_id=?',(connection['library_id'],))}
        def scrub(value):
            if isinstance(value,str) and hashlib.sha256(value.encode()).hexdigest() in blocked:return '[用户已忘记]'
            if isinstance(value,dict):return {k:scrub(v) for k,v in value.items()}
            if isinstance(value,list):return [scrub(v) for v in value]
            return value
        event=scrub(event) if blocked else event
        sid=event.get('session_id');event_id=event.get('event_id') or event.get('turn_id')
        if not isinstance(sid,str) or not sid or len(sid)>200:raise ValidationError('事件缺少稳定会话标识')
        if not isinstance(event_id,(str,int)) or not str(event_id) or len(str(event_id))>300:raise ValidationError('事件缺少稳定事件标识')
        payload=json.dumps(event,ensure_ascii=False,sort_keys=True,allow_nan=False)
        if len(payload.encode())>32*1024*1024:raise ValidationError('单事件超过32MiB，请按真实消息拆分')
        self.authorize_session(connection['id'],sid)
        key=self._receipt_key(connection['id'],sid,event_id,connection.get('binding_revision',0))
        digest=hashlib.sha256(payload.encode()).hexdigest();kind=str(event.get('event_type',event.get('type','event')))[:80]
        # Raw host events are already fully archived. Only normalized complete
        # semantic records need applying to the graph; partial stays an archive.
        normalized=event.get('normalized') or (event.get('record') or {}).get('normalized') or (event if event.get('type') in ('turn','tool','output','persona_import') else None)
        pending=bool(normalized and normalized.get('status','complete')=='complete')
        semantic_type,automatic=self._payload_semantics(event)
        with self.db() as db:
            old=db.execute('SELECT * FROM receipts WHERE id=?',(key,)).fetchone()
            if old:
                if old['status']=='forgotten':return {'accepted':True,'duplicate':True,'receipt_id':key,'status':'forgotten'}
                if old['payload_hash'] not in (digest,original_digest):raise ValidationError('同一事件ID已用于不同内容')
                return {'accepted':True,'duplicate':True,'receipt_id':key,'status':old['status']}
            schema=(event.get('record') or {}).get('schema','') if isinstance(event.get('record'),dict) else ''
            db.execute('INSERT INTO receipts(id,connection_id,library_id,session_id,kind,status,payload,payload_hash,received,semantic_type,is_automatic,source_schema,binding_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (key,connection['id'],connection['library_id'],sid,kind,'pending' if pending else 'archived',payload,digest,time.time(),semantic_type,int(automatic),schema,connection.get('binding_revision',0)))
            db.execute('UPDATE connections SET last_received=?,error=NULL WHERE id=?',(time.time(),connection['id']))
        return {'accepted':True,'duplicate':False,'receipt_id':key,'status':'pending' if pending else 'archived'}
    def pending(self,limit=50,*,library_id=None,receipt_id=None):
        where="status IN ('pending','retry')";values=[]
        if library_id is not None:where+=' AND library_id=?';values.append(library_id)
        if receipt_id is not None:where+=' AND id=?';values.append(receipt_id)
        with self.db() as db:rows=db.execute('SELECT * FROM receipts WHERE '+where+' ORDER BY received LIMIT ?',(*values,limit)).fetchall()
        return [dict(r) for r in rows]
    def pending_count(self,library_id):
        with self.db() as db:return db.execute("SELECT COUNT(*) FROM receipts WHERE library_id=? AND status IN ('pending','retry')",(library_id,)).fetchone()[0]
    def receipt(self,cid,sid,event_id):
        key=self._receipt_key(cid,sid,event_id,self.get(cid).get('binding_revision',0))
        with self.db() as db:r=db.execute('SELECT * FROM receipts WHERE id=?',(key,)).fetchone()
        return dict(r) if r else None
    def read_archive(self,receipt_id,library_id):
        with self.db() as db:r=db.execute('SELECT * FROM receipts WHERE id=? AND library_id=?',(receipt_id,library_id)).fetchone()
        if r is None or r['status']=='forgotten':raise ValidationError('当前库没有这条事件档案，或已被用户忘记')
        item=dict(r);item['record']=json.loads(item.pop('payload'));item.pop('payload_hash',None)
        return item
    def applied(self,rid,node_ids,automatic=True):
        with self.db() as db:
            row=db.execute('SELECT connection_id,semantic_type,is_automatic,source_schema FROM receipts WHERE id=?',(rid,)).fetchone()
            automatic=bool(automatic and row['is_automatic'])
            db.execute("UPDATE receipts SET status='saved',applied=?,attempts=attempts+1,error=NULL,node_ids=?,is_automatic=? WHERE id=?",
                       (time.time(),json.dumps(node_ids),int(automatic),rid))
            if automatic and row['semantic_type']=='turn' and row['source_schema']=='love-house-agent-hook/v1':db.execute("UPDATE connections SET archive_status='host_reported',error=NULL WHERE id=?",(row['connection_id'],))
            elif automatic and row['semantic_type']=='turn':db.execute("UPDATE connections SET archive_status='automatic_connected',error=NULL WHERE id=?",(row['connection_id'],))
            elif automatic and row['semantic_type']=='output':db.execute("UPDATE connections SET archive_status=CASE WHEN archive_status='automatic_connected' THEN archive_status ELSE 'outputs_only' END,error=NULL WHERE id=?",(row['connection_id'],))
            elif automatic and row['semantic_type']=='tool':db.execute("UPDATE connections SET archive_status=CASE WHEN archive_status='automatic_connected' THEN archive_status ELSE 'observations_only' END,error=NULL WHERE id=?",(row['connection_id'],))
            else:db.execute("UPDATE connections SET archive_status=CASE WHEN archive_status='automatic_connected' THEN archive_status ELSE 'tools_only' END,error=NULL WHERE id=?",(row['connection_id'],))
    def failed(self,rid,error):
        with self.db() as db:
            db.execute("UPDATE receipts SET status='retry',attempts=attempts+1,error=? WHERE id=?",(str(error)[:300],rid))
    def activity(self,library_id=None,limit=50):
        with self.db() as db:
            rows=db.execute('SELECT id,connection_id,library_id,session_id,kind,status,received,attempts,error,node_ids FROM receipts'+
              (' WHERE library_id=?' if library_id else '')+' ORDER BY received DESC LIMIT ?',
              (library_id,limit) if library_id else (limit,)).fetchall()
        events=[]
        for r in rows:
            item=dict(r);item['received_at']=item.pop('received');item['node_ids']=json.loads(item.get('node_ids') or '[]')
            item['summary']=item['kind'];events.append(item)
        return {'events':events,'revision':max((e['received_at'] for e in events),default=0)}

    def archives(self,library_id):
        with self.db() as db:rows=db.execute("SELECT * FROM receipts WHERE library_id=? AND status!='forgotten' ORDER BY received",(library_id,)).fetchall()
        return [dict(r) for r in rows]

    def forgetting(self,library_id,raw_ids,texts):
        copies=[]
        for row in self.archives(library_id):
            if row['id'] not in raw_ids and any(t and json.dumps(t,ensure_ascii=False)[1:-1] in row['payload'] for t in texts):copies.append(row['id'])
        return {'raw_ids':list(raw_ids),'node_ids':[],'redacted_receipt_ids':copies}

    def forget(self,library_id,raw_ids,texts):
        def scrub(value):
            if isinstance(value,str):
                for text in texts:
                    if len(text)>3:value=value.replace(text,'[用户已忘记]')
                    elif value==text:value='[用户已忘记]'
                return value
            if isinstance(value,dict):return {k:scrub(v) for k,v in value.items()}
            if isinstance(value,list):return [scrub(v) for v in value]
            return value
        with self.db() as db:
            for text in texts:db.execute('INSERT OR IGNORE INTO forgotten_texts VALUES(?,?)',(library_id,hashlib.sha256(text.encode()).hexdigest()))
            for rid in raw_ids:
                db.execute("UPDATE receipts SET status='forgotten',payload='{}',node_ids='[]',error=NULL WHERE id=? AND library_id=?",(rid,library_id))
            rows=db.execute("SELECT id,payload FROM receipts WHERE library_id=? AND status!='forgotten'",(library_id,)).fetchall()
            for row in rows:
                redacted=json.dumps(scrub(json.loads(row['payload'])),ensure_ascii=False,sort_keys=True)
                if redacted!=row['payload']:db.execute('UPDATE receipts SET payload=? WHERE id=?',(redacted,row['id']))
        checkpointed=False
        try:
            with self.db() as db:
                row=db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone();checkpointed=row[0]==0
        except sqlite3.Error:pass
        return {'archives_forgotten':len(raw_ids),'checkpointed':checkpointed}
