"""OpenAI-compatible memory gateway; records independently of model tool choices."""
from __future__ import annotations
import codecs
import hashlib
import json
import time
import uuid
import urllib.request
import urllib.error
from ..adapters.http import RequestError

ENDPOINT='https://api.deepseek.com/chat/completions'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def plain_content(value):
    if isinstance(value,str):return value,[]
    text=[];refs=[]
    if isinstance(value,list):
        for part in value:
            if not isinstance(part,dict):continue
            if part.get('type')=='text' and isinstance(part.get('text'),str):text.append(part['text'])
            else:
                encoded=json.dumps(part,sort_keys=True,ensure_ascii=False)
                refs.append({'type':part.get('type','attachment'),'sha256':hashlib.sha256(encoded.encode()).hexdigest(),
                             'reference_only':True,'characters':len(encoded)})
    return '\n'.join(text),refs

def archive_messages(messages):
    """Keep received roles/tool results; attachment payloads remain hashes/references."""
    sensitive={'authorization','api_key','apikey','password','cookie','access_token','refresh_token'}
    def scrub(value):
        if isinstance(value,dict):return {k:scrub(v) for k,v in value.items() if k.lower().replace('-','_') not in sensitive}
        if isinstance(value,list):return [scrub(v) for v in value]
        return value
    out=[]
    for m in messages:
        if not isinstance(m,dict):continue
        item=scrub(m);text,refs=plain_content(m.get('content'))
        item['content']=text
        if refs:item['attachments']=refs
        for call in item.get('tool_calls',[]) or []:
            function=call.get('function',{}) if isinstance(call,dict) else {}
            try:function['arguments']=json.dumps(scrub(json.loads(function['arguments'])),ensure_ascii=False)
            except (KeyError,ValueError,TypeError):pass
        out.append(item)
    return out

def _record(host,c,sid,rid,user,assistant,refs,status,response_json=None,response_sse=None,request_messages=None):
    event={'session_id':sid,'event_id':rid,'event_type':'api/turn',
       'record':{'schema':'neural-api-proxy/v1','attachments':refs,
                 'response_json':response_json,'response_sse':response_sse,
                 'request_messages':archive_messages(request_messages or [])},
       'normalized':{'type':'turn','turn_id':rid,'status':status,'user':user,'assistant':assistant,'origin':'api_proxy'}}
    # Authenticated connection was resolved before network I/O. Preserve the received
    # response even if the user pauses new captures while it was already in flight.
    try:
        result=host.connections.receive(c,event);host.process_pending();return result
    except Exception:
        # A real paid upstream reply must still reach its caller even if local
        # storage has just failed. Never label this as successfully archived.
        try:host.connections.status(c['id'],'archive_failed','模型已返回，但本地档案未落盘；请检查存储空间与权限')
        except Exception:pass
        return {'status':'archive_failed'}

def _record_tools(host,c,sid,messages):
    """A tool request is an intention; only client-supplied results are observations."""
    previous_user=''
    for message in archive_messages(messages):
        if message.get('role')=='user':previous_user=message.get('content','')
        if message.get('role')!='tool':continue
        content=message.get('content','')
        if not content.strip():continue
        call=str(message.get('tool_call_id',''))[:200]
        identity=hashlib.sha256(json.dumps([previous_user,call,content],ensure_ascii=False).encode()).hexdigest()
        event={'session_id':sid,'event_id':'api-tool-'+identity,'event_type':'api/tool',
               'record':{'schema':'neural-api-tool/v1','message':message,'reported_by':'api_client'},
               'normalized':{'type':'tool','turn_id':'api-tool-'+identity,'call_id':call,
                             'text':content,'status':'complete','outcome':'observed','origin':'api_client_tool'}}
        host.connections.receive(c,event)
    host.process_pending()

def forward_chat(handler,host,cid,*,opener=None):
    c=host.connections.get(cid,secret=True)
    if c['host']!='api' or c['revoked']:raise RequestError('此API记忆连接已断开，请将客户端切回原API地址或新建连接',403)
    capturing=bool(c['enabled'])
    actual_session=handler.headers.get('X-NKB-Session') or handler.headers.get('X-Neural-Session')
    if capturing and c['session_scope']!='any' and not actual_session:
        raise RequestError('单窗口接入必须由客户端提供真实 X-NKB-Session；未记录或转发本次内容',400)
    if not handler.path.endswith('/v1/chat/completions'):raise RequestError('仅支持 /v1/chat/completions',404)
    auth=handler.headers.get('Authorization','')
    if not auth.startswith('Bearer ') or not auth[7:].strip():raise RequestError('请填写此连接的本地凭证或厂商API密钥',401)
    provider=host.providers.credential(cid)
    if provider['api_key']:
        import hmac
        if not hmac.compare_digest(auth[7:],c['token']):raise RequestError('本地连接凭证不正确；请从接入页复制',401)
        upstream_auth='Bearer '+provider['api_key']
    else:
        if auth[7:]==c['token']:raise RequestError('上游密钥尚未配置，请在爱之屋接入页填写',401)
        upstream_auth=auth
    from .providers import endpoint
    upstream_url=endpoint(provider['base_url'])
    data=handler._body(limit=32*1024*1024)
    messages=data.get('messages')
    if not isinstance(messages,list) or not messages or len(messages)>500:raise RequestError('messages格式不正确')
    latest=next((m for m in reversed(messages) if isinstance(m,dict) and m.get('role')=='user'),None)
    if latest is None:raise RequestError('需要真实用户消息')
    user,refs=plain_content(latest.get('content'))
    if not user and refs:user='[本轮用户发送附件；保存的是引用与哈希，不是附件全文]'
    if not user.strip():raise RequestError('本轮用户消息为空')
    sid=actual_session or 'api-default-session'
    if capturing:host.connections.authorize_session(cid,sid)
    rid=handler.headers.get('X-NKB-Request-ID') or handler.headers.get('Idempotency-Key') or 'api_'+uuid.uuid4().hex
    if len(rid)>200:raise RequestError('请求编号过长')
    old=host.connections.receipt(cid,sid,rid) if capturing else None
    if old:
        if old['status']=='forgotten':raise RequestError('这条请求的记忆已被明确忘记，不能重放',410)
        previous=json.loads(old['payload']);normalized=previous.get('normalized',{})
        if normalized.get('user')!=user:raise RequestError('同一请求编号已用于不同消息',409)
        record=previous.get('record',{})
        if normalized.get('status')!='complete':raise RequestError('该请求已有未完成记录，请使用新请求编号重试',409)
        body=(json.dumps(record['response_json'],ensure_ascii=False).encode() if record.get('response_json') is not None
              else (record.get('response_sse') or '').encode())
        handler.send_response(200);handler.send_header('Content-Type','text/event-stream' if data.get('stream') else 'application/json')
        handler.send_header('Content-Length',str(len(body)));handler.send_header('X-NKB-Replayed','true');handler.end_headers();handler.wfile.write(body);return
    context=host.context(cid,c['token'],{'session_id':sid,'query':user[:40000]}) if capturing else None
    if capturing:_record_tools(host,c,sid,messages)
    # Keep the caller's system/persona and original history; add clearly marked memory material.
    position=max(i for i,m in enumerate(messages) if isinstance(m,dict) and m.get('role')=='user')
    forwarded=list(messages)
    if context:forwarded.insert(position,{'role':'user','content':context['packet']})
    payload={**data,'messages':forwarded}
    if not payload.get('model') and provider['model']:payload['model']=provider['model']
    request=urllib.request.Request(upstream_url,data=json.dumps(payload,ensure_ascii=False).encode(),
                                   headers={'Authorization':upstream_auth,'Content-Type':'application/json'},method='POST')
    opener=opener or urllib.request.build_opener(NoRedirect())
    try:response=opener.open(request,timeout=90)
    except urllib.error.HTTPError as exc:
        raise RequestError('上游模型未接受请求（HTTP '+str(exc.code)+'），未伪造对话记录',exc.code if 400<=exc.code<600 else 502) from None
    except Exception:raise RequestError('无法连接上游模型，未伪造对话记录',502) from None
    stream=data.get('stream') is True
    if not stream:
        with response:body=response.read(16*1024*1024+1)
        if len(body)>16*1024*1024:raise RequestError('模型回复超过保存上限',502)
        try:
            result=json.loads(body);assistant=result['choices'][0]['message'].get('content') or ''
            finish=result['choices'][0].get('finish_reason')
            if not isinstance(assistant,str):raise ValueError()
        except Exception:raise RequestError('模型返回结构不完整，未伪造已完成记忆',502) from None
        status='complete' if assistant and finish is not None and finish not in ('length','content_filter') else 'partial'
        receipt=_record(host,c,sid,rid,user,assistant,refs,status,response_json=result,request_messages=messages) if capturing else {'status':'paused'}
        handler.send_response(200);handler.send_header('Content-Type','application/json; charset=utf-8')
        handler.send_header('Content-Length',str(len(body)));handler.send_header('X-NKB-Capture',receipt['status'])
        handler.send_header('X-NKB-Session',sid);handler.send_header('Cache-Control','no-store');handler.end_headers();handler.wfile.write(body)
        return
    handler.send_response(200);handler.send_header('Content-Type','text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control','no-store');handler.send_header('Connection','close')
    handler.send_header('X-NKB-Session',sid);handler.end_headers();handler.close_connection=True
    decoder=codecs.getincrementaldecoder('utf-8')();buffer='';parts=[];raw_chunks=[];total_bytes=0;done=False;finish=None;connected=True
    try:
        with response:
            while True:
                chunk=response.read1(8192) if hasattr(response,'read1') else response.read(8192)
                if not chunk:break
                raw_chunks.append(chunk)
                total_bytes+=len(chunk)
                if total_bytes>16*1024*1024:raise ValueError('stream too large')
                buffer+=decoder.decode(chunk)
                for line in buffer.split('\n')[:-1]:
                    if not line.startswith('data:'):continue
                    value=line[5:].strip()
                    if value=='[DONE]':done=True;continue
                    try:
                        event=json.loads(value)
                        for choice in event.get('choices',[]):
                            content=choice.get('delta',{}).get('content')
                            if isinstance(content,str):parts.append(content)
                            if choice.get('finish_reason'):finish=choice['finish_reason']
                    except (ValueError,TypeError):continue
                buffer=buffer.rsplit('\n',1)[-1]
                try:handler.wfile.write(chunk);handler.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):connected=False;break
                if done:break
    except Exception:connected=False
    assistant=''.join(parts)
    if capturing:
        _record(host,c,sid,rid,user,assistant,refs,'complete' if done and connected and assistant and finish is not None and finish not in ('length','content_filter') else 'partial',
                response_sse=b''.join(raw_chunks).decode('utf-8',errors='replace'),request_messages=messages)
