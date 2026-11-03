"""Explicit optional reading indexes; full share archives never depend on a model."""
from copy import deepcopy
import json
import threading
import time
import uuid
import urllib.request

from ..core.brain import Brain
from ..errors import ValidationError
from ..organizer.config import get_profile
from ..organizer.model import resolve_model, model_options
from .sharing import build_summary_input, validate_summary_response


class ReadingSummaryService:
    def __init__(self, host):
        self.host = host
        self._lock = threading.Lock()
        self._summaries = {}
        self._running = set()

    def resolve(self, library_id, summary_id, revision):
        if not summary_id:
            return None
        if not isinstance(summary_id, str) or len(summary_id) > 80 or not isinstance(revision, str):
            raise ValidationError('阅读索引编号或版本不正确')
        with self._lock:
            value = self._summaries.get(summary_id)
        if not value or value['library_id'] != library_id or value['revision'] != revision or time.time()-value['created'] > 1800:
            raise ValidationError('阅读索引已过期或不属于本库，请重新生成；完整导出仍可使用')
        # A caller cannot revive a cached pre-forgetting summary by supplying its
        # old revision. The full download also checks again at extraction time.
        if self.host.sharing.prepare(library_id)['content_revision'] != revision:
            raise ValidationError('阅读索引对应的记忆已变化，请重新生成；完整导出仍可使用')
        return deepcopy(value['summary'])

    def generate(self, library_id, *, expected_revision, confirm=False):
        if confirm is not True:
            raise ValidationError('请先确认将本库脱敏摘录发送给已配置的整理模型')
        with self._lock:
            if library_id in self._running:
                raise ValidationError('这个库正在生成阅读索引，请等待当前请求结束')
            self._running.add(library_id)
        try:
            package = self.host.sharing.prepare(library_id)
            revision = package['content_revision']
            if not expected_revision or expected_revision != revision:
                raise ValidationError('记忆内容已变化，请刷新分享预览后重试')
            profile = get_profile(Brain(self.host.snapshot(library_id)))
            credential = self.host.organizer_credential(library_id, profile)
            resolved, key, url = resolve_model(profile, credential)
            options = model_options(resolved)
            # This optional reading index intentionally receives a small scrubbed
            # excerpt, independently of the organizer's full-source context.
            prepared = build_summary_input(package, max_chars=min(12000, profile['max_input_chars'] or 12000))
            if not prepared['coverage']['included_nodes']:
                raise ValidationError('本次预算内没有完整的记忆条目可供索引；请直接导出完整文件')
            # Credentials normally live outside memory. If a user previously
            # pasted this actual (possibly unprefixed) key into ordinary prose,
            # the generic share scanner cannot recognize it by shape alone.
            # We have the active credential here: never duplicate it in content.
            messages = [{**message, 'content': message['content'].replace(key, '[整理模型密钥已隐藏]')}
                        for message in prepared['messages']]
            chars = len(json.dumps(messages, ensure_ascii=False))
            # Share the usage journal without a daily stop condition.
            with self.host.organizer.db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO calls VALUES(?,?,?,?)', (uuid.uuid4().hex, library_id, time.time(), chars))
            request = urllib.request.Request(url, data=json.dumps({'model':resolved['model'], 'messages':messages,
                'stream':False, 'response_format':{'type':'json_object'}, **options}, ensure_ascii=False).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key}, method='POST')
            try:
                response = self.host.organizer.transport(request, timeout=300)
                choice = response['choices'][0]
                content = choice['message']['content']
                if choice.get('finish_reason') == 'length' or not isinstance(content, str) or key in content:
                    raise ValueError('invalid model output')
                summary = validate_summary_response(content, prepared['coverage'])
                if key in summary['text']:
                    raise ValueError('credential appeared after decoding model output')
            except Exception:
                raise ValidationError('阅读索引生成未完成，已记录本次调用用量；原文和完整导出仍保留') from None
            if self.host.sharing.prepare(library_id)['content_revision'] != revision:
                raise ValidationError('生成期间记忆发生变化，本次索引未采用；请刷新后重试')
            identifier = 'summary_' + uuid.uuid4().hex
            with self._lock:
                now = time.time()
                self._summaries = {k:v for k,v in self._summaries.items() if now-v['created'] < 1800}
                if len(self._summaries) >= 16:
                    self._summaries.pop(min(self._summaries, key=lambda k:self._summaries[k]['created']))
                self._summaries[identifier] = {'library_id':library_id, 'revision':revision,
                    'created':now, 'summary':summary}
            return {'summary_id':identifier, 'content_revision':revision, 'reading_summary':summary,
                'model_called':True, 'full_archive_unchanged':True, 'input_chars':chars}
        finally:
            with self._lock:
                self._running.discard(library_id)
