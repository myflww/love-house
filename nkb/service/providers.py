"""Safe per-connection upstream settings; vendor secrets live only in KeyStore."""
from __future__ import annotations
import hashlib
import json
from urllib.parse import urlsplit
import ipaddress
from ..errors import ValidationError

DEFAULT_BASE = 'https://api.deepseek.com/v1'

def endpoint(base_url):
    if not isinstance(base_url,str) or len(base_url)>2000:
        raise ValidationError('API地址须为有效的HTTPS地址')
    if any(c.isspace() or ord(c)<32 for c in base_url.strip()) or '\\' in base_url:
        raise ValidationError('API地址不能包含空白或控制字符')
    try:p=urlsplit(base_url.strip())
    except ValueError:raise ValidationError('API地址格式不正确') from None
    if not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValidationError('API地址不能包含密钥、查询或片段')
    local=p.hostname=='localhost'
    try:local=local or ipaddress.ip_address(p.hostname).is_loopback
    except ValueError:pass
    if p.scheme!='https' and not (p.scheme=='http' and local):
        raise ValidationError('API使用HTTPS；仅本机调试可用HTTP')
    try:
        if p.port is not None and not 1<=p.port<=65535:raise ValueError()
    except ValueError:raise ValidationError('API端口不正确') from None
    if '/connections/' in p.path:raise ValidationError('上游地址不能是爱之屋自己的记忆网关')
    base=base_url.strip().rstrip('/')
    return base if p.path.rstrip('/').endswith('/chat/completions') else base+'/chat/completions'

def validate_settings(data,old=None):
    if not isinstance(data,dict):raise ValidationError('上游模型配置须为对象')
    old=old or {'base_url':DEFAULT_BASE,'model':''}
    base=data.get('base_url',old['base_url']);model=data.get('model',old['model'])
    endpoint(base)
    if not isinstance(model,str) or len(model)>200:raise ValidationError('模型名称须为最多200字的字符串')
    key=data.get('api_key','');save_key=data.get('save_key',True)
    if (not isinstance(key,str) or len(key)>32768 or type(save_key) is not bool
        or any(c.isspace() or ord(c)<32 for c in key.strip())):raise ValidationError('密钥配置格式不正确')
    if 'remove_key' in data and type(data['remove_key']) is not bool:raise ValidationError('remove_key必须是布尔值')
    return {'base_url':base.strip().rstrip('/'),'model':model.strip(),'api_key':key.strip(),'save_key':save_key}

class ProviderStore:
    def __init__(self,connections,keys):
        self.connections=connections;self.keys=keys
        with connections.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS providers(connection_id TEXT PRIMARY KEY,base_url TEXT NOT NULL,model TEXT NOT NULL,key_policy TEXT DEFAULT "persistent")')
            if 'key_policy' not in {r['name'] for r in db.execute('PRAGMA table_info(providers)')}:db.execute("ALTER TABLE providers ADD COLUMN key_policy TEXT DEFAULT 'persistent'")
    def get(self,cid):
        self.connections.get(cid)
        with self.connections.db() as db:r=db.execute('SELECT * FROM providers WHERE connection_id=?',(cid,)).fetchone()
        return dict(r) if r else {'connection_id':cid,'base_url':DEFAULT_BASE,'model':'','key_policy':'persistent'}
    def ref(self,cid,base_url=None,key_policy=None):
        c=self.connections.get(cid);p=self.get(cid);base_url=base_url or p['base_url'];key_policy=key_policy or p.get('key_policy','persistent')
        return {'provider':'upstream:'+hashlib.sha256(endpoint(base_url).encode()).hexdigest()+(':'+key_policy if key_policy=='session' else ''),
                'library_id':c['library_id'],'connection_id':cid}
    def public(self,cid):
        p=self.get(cid)
        return {**p,**self.keys.metadata(self.ref(cid,p['base_url'])),'protocol':'chat_completions'}
    def save(self,cid,data):
        config=validate_settings(data,self.get(cid));base=config['base_url'];model=config['model']
        key=config['api_key'];save_key=config['save_key']
        policy=('persistent' if save_key else 'session') if key.strip() else self.get(cid).get('key_policy','persistent')
        ref=self.ref(cid,base,policy)
        if key.strip():self.keys.set(ref,key.strip(),persist=save_key)
        if data.get('remove_key') is True:
            errors=[]
            for scope in ('session','persistent'):
                try:self.keys.delete(self.ref(cid,base,scope))
                except Exception as exc:errors.append(exc)
            if errors:
                from .credentials import KeyStoreError
                raise KeyStoreError('本次临时密钥已清除，但系统持久密钥删除尚未确认，请检查钥匙串权限') from None
        with self.connections.db() as db:
            db.execute('INSERT INTO providers(connection_id,base_url,model,key_policy) VALUES(?,?,?,?) ON CONFLICT(connection_id) DO UPDATE SET base_url=excluded.base_url,model=excluded.model,key_policy=excluded.key_policy',
                       (cid,base.strip().rstrip('/'),model.strip(),policy))
        return self.public(cid)
    def credential(self,cid):
        p=self.get(cid);return {'api_key':self.keys.get(self.ref(cid,p['base_url'])),'base_url':p['base_url'],'model':p['model']}
