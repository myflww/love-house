from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from ..errors import ValidationError

class ConnectionStore:
    """Connection bindings and a durable receipt/outbox journal, independent of graph decay."""
    def __init__(self,root):
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
            receipt_fields={r['name'] for r in db.execute('PRAGMA table_info(receipts)')}
            for field,kind in (('semantic_type','TEXT'),('is_automatic','INTEGER')):
                if field not in receipt_fields:db.execute(f'ALTER TABLE receipts ADD COLUMN {field} {kind}')
            # Classify existing receipts once. Original payloads/hashes/IDs remain
            # untouched; future status polling does not reparse private texts.
            for row in db.execute('SELECT id,payload FROM receipts WHERE semantic_type IS NULL OR is_automatic IS NULL'):
                semantic_type,automatic=self._payload_semantics(row['payload'])
                db.execute('UPDATE receipts SET semantic_type=?,is_automatic=? WHERE id=?',
                           (semantic_type,int(automatic),row['id']))
            db.execute('CREATE INDEX IF NOT EXISTS receipts_capture_state ON receipts(connection_id,status,semantic_type,is_automatic)')
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
            if kind not in ('turn','tool','persona_import') or normalized.get('status','complete')!='complete':kind=''
            automatic=record.get('schema') in ('deepseek-harness-event/v1','love-house-agent-hook/v1',
                                                'neural-api-proxy/v1','neural-api-tool/v1')
            return kind,bool(automatic)
        except (ValueError,TypeError,RecursionError):return '',False
    def _capture(self,cid):
        with self.db() as db:
            row=db.execute('''SELECT
              SUM(CASE WHEN status='saved' AND semantic_type='turn' THEN 1 ELSE 0 END) complete_dialogues_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='turn' AND is_automatic=1 THEN 1 ELSE 0 END) automatic_dialogues_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='tool' THEN 1 ELSE 0 END) tool_observations_saved,
              SUM(CASE WHEN status='saved' AND semantic_type='tool' AND is_automatic=1 THEN 1 ELSE 0 END) automatic_tool_observations_saved,
              SUM(CASE WHEN status='archived' THEN 1 ELSE 0 END) raw_events_only,
              SUM(CASE WHEN status IN ('pending','retry') THEN 1 ELSE 0 END) pending_records,
              MAX(CASE WHEN status='saved' AND semantic_type='turn' THEN applied END) last_dialogue_at
              FROM receipts WHERE connection_id=?''',(cid,)).fetchone()
        return {k:(row[k] if k=='last_dialogue_at' else int(row[k] or 0)) for k in row.keys()}
    def public(self,row):
        result=dict(row);result.pop('token',None)
        result['enabled']=bool(result['enabled']);result['revoked']=bool(result['revoked'])
        result['archive_status']=result['archive_status'] or 'waiting'
        capture=self._capture(result['id']);result['capture']=capture
        if not result['revoked']:
            # A completed tool result proves automatic observation capture, not
            # that a human/assistant conversation pair has reached the graph.
            if capture['automatic_dialogues_saved']:result['archive_status']='automatic_connected'
            elif capture['automatic_tool_observations_saved']:result['archive_status']='observations_only'
            elif capture['complete_dialogues_saved'] or capture['tool_observations_saved']:result['archive_status']='tools_only'
            elif result['archive_status'] in ('automatic_connected','observations_only','tools_only'):result['archive_status']='waiting'
        result['last_received_at']=result.pop('last_received',None)
        result['host_seen_at']=result.pop('host_seen',None)
        result['host_online']=bool(result['host_seen_at'] and time.time()-result['host_seen_at']<65 and result['enabled'] and not result['revoked'])
        return result
    def create(self,name,host,library_id,session_scope='connection'):
        if not isinstance(name,str) or not name.strip() or len(name)>80:raise ValidationError('连接名称须为1~80字')
        if host not in ('harness','api','agent'):raise ValidationError('连接方式须为harness、agent或api')
        if not isinstance(session_scope,str) or not session_scope.strip() or len(session_scope)>200:raise ValidationError('会话范围不合法')
        cid='conn_'+uuid.uuid4().hex;token=secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('INSERT INTO connections(id,name,host,library_id,session_scope,token,enabled,revoked,created,last_received,archive_status,error) VALUES(?,?,?,?,?,?,1,0,?,NULL,?,NULL)',
                       (cid,name.strip(),host,library_id,session_scope,token,time.time(),'waiting'))
        return self.get(cid)
    def heartbeat(self,cid,data):
        for key in ('host_version','adapter_version','bound_session_id'):
            if key in data and (not isinstance(data[key],str) or len(data[key])>200):raise ValidationError('宿主状态字段不正确')
        with self.db() as db:db.execute('UPDATE connections SET host_seen=?,error=NULL WHERE id=?',(time.time(),cid))
        return {'ok':True,'host_online':True,'archive_status':self.get(cid)['archive_status']}
    def configured(self,cid):
        with self.db() as db:db.execute('UPDATE connections SET configured_at=? WHERE id=?',(time.time(),cid))
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
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT session_scope FROM connections WHERE id=?',(cid,)).fetchone()
            if row is None:raise ValidationError('连接不存在')
            scope=row['session_scope']
            if scope=='next_session':
                db.execute('UPDATE connections SET session_scope=? WHERE id=?',(sid,cid))
            elif scope!='connection' and scope!=sid:
                raise ValidationError('此连接绑定了另一对话窗口，未保存当前会话')
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
        key=hashlib.sha256(json.dumps([connection['id'],sid,str(event_id)],ensure_ascii=False).encode()).hexdigest()
        digest=hashlib.sha256(payload.encode()).hexdigest();kind=str(event.get('event_type',event.get('type','event')))[:80]
        # Raw host events are already fully archived. Only normalized complete
        # semantic records need applying to the graph; partial stays an archive.
        normalized=event.get('normalized') or (event.get('record') or {}).get('normalized') or (event if event.get('type') in ('turn','tool','persona_import') else None)
        pending=bool(normalized and normalized.get('status','complete')=='complete')
        semantic_type,automatic=self._payload_semantics(event)
        with self.db() as db:
            old=db.execute('SELECT * FROM receipts WHERE id=?',(key,)).fetchone()
            if old:
                if old['status']=='forgotten':return {'accepted':True,'duplicate':True,'receipt_id':key,'status':'forgotten'}
                if old['payload_hash'] not in (digest,original_digest):raise ValidationError('同一事件ID已用于不同内容')
                return {'accepted':True,'duplicate':True,'receipt_id':key,'status':old['status']}
            db.execute('INSERT INTO receipts(id,connection_id,library_id,session_id,kind,status,payload,payload_hash,received,semantic_type,is_automatic) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (key,connection['id'],connection['library_id'],sid,kind,'pending' if pending else 'archived',payload,digest,time.time(),semantic_type,int(automatic)))
            db.execute('UPDATE connections SET last_received=?,error=NULL WHERE id=?',(time.time(),connection['id']))
        return {'accepted':True,'duplicate':False,'receipt_id':key,'status':'pending' if pending else 'archived'}
    def pending(self,limit=50):
        with self.db() as db:rows=db.execute("SELECT * FROM receipts WHERE status IN ('pending','retry') ORDER BY received LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]
    def receipt(self,cid,sid,event_id):
        key=hashlib.sha256(json.dumps([cid,sid,str(event_id)],ensure_ascii=False).encode()).hexdigest()
        with self.db() as db:r=db.execute('SELECT * FROM receipts WHERE id=?',(key,)).fetchone()
        return dict(r) if r else None
    def read_archive(self,receipt_id,library_id):
        with self.db() as db:r=db.execute('SELECT * FROM receipts WHERE id=? AND library_id=?',(receipt_id,library_id)).fetchone()
        if r is None or r['status']=='forgotten':raise ValidationError('当前库没有这条事件档案，或已被用户忘记')
        item=dict(r);item['record']=json.loads(item.pop('payload'));item.pop('payload_hash',None)
        return item
    def applied(self,rid,node_ids,automatic=True):
        with self.db() as db:
            row=db.execute('SELECT connection_id,semantic_type,is_automatic FROM receipts WHERE id=?',(rid,)).fetchone()
            automatic=bool(automatic and row['is_automatic'])
            db.execute("UPDATE receipts SET status='saved',applied=?,attempts=attempts+1,error=NULL,node_ids=?,is_automatic=? WHERE id=?",
                       (time.time(),json.dumps(node_ids),int(automatic),rid))
            if automatic and row['semantic_type']=='turn':db.execute("UPDATE connections SET archive_status='automatic_connected',error=NULL WHERE id=?",(row['connection_id'],))
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
