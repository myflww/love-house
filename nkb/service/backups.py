"""Private portable snapshots, restored into a new identity with no live bindings/keys."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from ..core.brain import Brain
from ..errors import ValidationError
from ..storage.jsonfile import JsonFileStorage

class BackupStore:
    def __init__(self,host):
        self.host=host;self.directory=host.root/'backups';self.directory.mkdir(exist_ok=True,mode=0o700)
    def path(self,bid):
        if not isinstance(bid,str) or not re.fullmatch(r'backup_[a-f0-9]{32}',bid):raise ValidationError('备份编号不正确')
        return self.directory/(bid+'.lovehouse.json')
    def read(self,bid,library_id):
        p=self.path(bid)
        if not p.is_file() or p.stat().st_size>256*1024*1024:raise ValidationError('备份不存在或超过256MiB')
        value=json.loads(p.read_text('utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
        if value.get('format')!='love-house-backup/v1' or value.get('library_id')!=library_id:raise ValidationError('这不是当前库的备份')
        brain=value.get('brain');archives=value.get('archives')
        if not isinstance(brain,dict) or not isinstance(brain.get('nodes'),dict) or not isinstance(archives,list):raise ValidationError('备份结构不完整')
        if len(brain['nodes'])>100000 or len(archives)>100000:raise ValidationError('备份超过恢复上限')
        try:
            checked=Brain(deepcopy(brain))
            for nid,n in checked.nodes.items():
                if n['id']!=nid or not isinstance(n['text'],str) or not isinstance(n['meta'],dict):raise ValueError()
            for key in checked.edges:
                a,b=key.split('|')
                if a not in checked.nodes or b not in checked.nodes:raise ValueError()
            checked.export()
        except Exception:raise ValidationError('备份图谱验证失败，未改动现有记忆') from None
        if any(not isinstance(r,dict) or r.get('library_id')!=library_id or not isinstance(r.get('payload'),str) for r in archives):raise ValidationError('备份档案归属不正确')
        return value
    @staticmethod
    def public(value):
        return {k:value[k] for k in ('id','library_id','name','created','node_count','archive_count')}
    def list(self,library_id):
        out=[]
        for path in self.directory.glob('backup_*.lovehouse.json'):
            try:
                value=self.read(path.name.split('.')[0],library_id);out.append(self.public(value))
            except (OSError,ValueError,ValidationError):continue
        return sorted(out,key=lambda r:-r['created'])
    def create(self,library_id):
        meta=self.host.library(library_id)
        if meta['is_demo']:raise ValidationError('示例库不需要备份')
        # Capture application is serialized with this snapshot; later events remain
        # in the live library and do not make the earlier backup inconsistent.
        with self.host._apply_lock:
            brain=self.host.snapshot(library_id);archives=self.host.connections.archives(library_id)
        brain['meta'].pop('organizer_log',None)
        value={'format':'love-house-backup/v1','id':'backup_'+uuid.uuid4().hex,'library_id':library_id,
               'name':meta['name'],'created':time.time(),'node_count':len(brain['nodes']),
               'archive_count':len(archives),'brain':brain,'archives':archives}
        path=self.path(value['id']);JsonFileStorage(path).save(value);path.chmod(0o600)
        return {**self.public(value),'path':str(path),'saved':True,'includes_keys':False,'includes_bindings':False}
    def preview(self,bid,library_id):
        value=self.read(bid,library_id)
        return {**self.public(value),'read_only':True,'restore_mode':'new_library','connections_rebound':False,'includes_keys':False}
    def purge(self,library_id):
        items=self.list(library_id)
        for item in items:self.path(item['id']).unlink()
        return len(items)
    def restore(self,bid,library_id,name=None):
        value=self.read(bid,library_id)
        created=self.host.manager.create_library(name or (value['name']+' · 恢复'))
        new_id=created['id'];brain=deepcopy(value['brain']);brain['name']=created['name']
        # Provider credentials, background organizer consent and live connections
        # are not portable. The restored Agent is idle until explicitly connected.
        profile=brain.get('meta',{}).get('organizer_profile',{})
        profile.update(enabled=False,provider_id='',base_url='',model='')
        mapping={r['id']:hashlib.sha256((new_id+':'+r['id']).encode()).hexdigest() for r in value['archives']}
        def remap_receipts(value):
            # Only typed archive references change. Quotes and original textual
            # IDs remain verbatim, while organized/candidate/persona metadata can
            # still follow its evidence inside the newly restored library.
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('archive_receipt_id','receipt_id') and isinstance(item,str) and item in mapping:
                        value[key]=mapping[item]
                    else:remap_receipts(item)
            elif isinstance(value,list):
                for item in value:remap_receipts(item)
        remap_receipts(brain)
        def apply(target):
            loaded=Brain(brain)
            for field in ('nodes','edges','meta','_vec','name','config','half_life'):setattr(target,field,deepcopy(getattr(loaded,field)))
            return {'node_count':len(target.nodes)}
        try:
            with self.host.connections.db() as db:
                for r in value['archives']:
                    db.execute('INSERT INTO receipts(id,connection_id,library_id,session_id,kind,status,payload,payload_hash,received,attempts,error,applied,node_ids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (mapping[r['id']],'restored:'+r['connection_id'],new_id,r['session_id'],r['kind'],
                        'saved' if r.get('node_ids') and r['node_ids']!='[]' else 'archived',r['payload'],r['payload_hash'],r['received'],0,None,r.get('applied'),r.get('node_ids','[]')))
            self.host.transact(new_id,apply)
        except Exception:
            # Never overwrite the source. Leave a clearly empty new library if the
            # target file could not be persisted; remove only its copied archives.
            with self.host.connections.db() as db:db.execute('DELETE FROM receipts WHERE library_id=?',(new_id,))
            raise ValidationError('恢复未完成，原库与备份均保留；新建的恢复库暂为空') from None
        self.host.manager.select(new_id)
        return {'restored':True,'library':self.host.library(new_id),'selected_id':new_id,'connections_rebound':False}
