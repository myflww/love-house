"""Explicit host-source registration for one fixed Agent memory identity.

The authenticated source credential is the boundary. A declared runtime Agent
ID is an adapter assertion checked against registration, not remote attestation
or a name inferred from model text. Old window-bound connections are unchanged.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import secrets
import time
import uuid
from urllib.parse import urlsplit

from ..errors import ValidationError
from .source_client import (SCHEMA, SourceClientError, validate_base_url, validate_platforms,
                            validate_config, _write_private_json)


class AgentSourceRegistry:
    def __init__(self, root, connections):
        self.root = Path(root).expanduser().resolve()
        self.connections = connections
        self.directory = self.root / "agent-sources"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connections.db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS agent_sources(
                id TEXT PRIMARY KEY,connection_id TEXT NOT NULL UNIQUE,
                library_id TEXT NOT NULL,name TEXT NOT NULL,adapter TEXT NOT NULL,
                runtime_agent_id TEXT NOT NULL,platforms TEXT NOT NULL,
                base_url TEXT NOT NULL,created REAL NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS agent_sources_library ON agent_sources(library_id,created)")

    @staticmethod
    def _id(value):
        if (not isinstance(value, str) or not value.startswith("source_") or len(value) != 39
                or any(c not in "0123456789abcdef" for c in value[7:])):
            raise ValidationError("活动来源标识不合法")
        return value

    def _row(self, source_id):
        source_id = self._id(source_id)
        with self.connections.db() as db:
            row = db.execute("SELECT * FROM agent_sources WHERE id=?", (source_id,)).fetchone()
        if row is None: raise ValidationError("活动来源不存在")
        return dict(row)

    def _public(self, row):
        connection = self.connections.get(row["connection_id"])
        return {"id": row["id"], "source_id": row["id"], "connection_id": row["connection_id"],
                "library_id": row["library_id"], "agent_id": row["library_id"], "name": row["name"],
                "adapter": row["adapter"], "runtime_agent_id": row["runtime_agent_id"],
                "platforms": json.loads(row["platforms"]), "created": row["created"],
                "enabled": connection["enabled"], "revoked": connection["revoked"],
                "host_online": connection["host_online"], "last_received_at": connection["last_received_at"],
                "capture": connection["capture"], "archive_status": connection["archive_status"],
                "config_ready": (self.directory / (row["id"] + ".json")).is_file(),
                "identity_assurance": "registered_adapter_assertion",
                "full_activity_coverage_verified": False, "model_api_key_required": False}

    def get(self, source_id):
        return self._public(self._row(source_id))

    def list(self, library_id):
        with self.connections.db() as db:
            rows = db.execute("SELECT * FROM agent_sources WHERE library_id=? ORDER BY created,id", (library_id,)).fetchall()
        return [self._public(dict(row)) for row in rows]

    def for_connection(self, connection_id):
        with self.connections.db() as db:
            row = db.execute("SELECT * FROM agent_sources WHERE connection_id=?", (connection_id,)).fetchone()
        return self._public(dict(row)) if row else None

    def _private(self, row, connection, base_url=None):
        return validate_config({"schema": SCHEMA, "source_id": row["id"], "connection_id": row["connection_id"],
            "library_id": row["library_id"], "runtime_agent_id": row["runtime_agent_id"], "adapter": row["adapter"],
            "platforms": json.loads(row["platforms"]), "base_url": base_url or row["base_url"],
            "token": connection["token"], "enabled": bool(connection["enabled"]), "revoked": bool(connection["revoked"]),
            "outbox_dir": str(self.root / "source-outbox" / row["id"]), "runtime_dir": str(self.root / ".runtime")})

    def register(self, library_id, data, *, base_url="http://127.0.0.1:8768"):
        if (not isinstance(library_id, str) or not library_id or len(library_id) > 64
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in library_id)):
            raise ValidationError("Agent 存档身份不合法")
        if not isinstance(data, dict) or set(data) - {"name", "adapter", "runtime_agent_id", "platforms"}:
            raise ValidationError("来源登记只接受名称、适配器、宿主身份和平台范围")
        name = data.get("name"); adapter = data.get("adapter"); runtime = data.get("runtime_agent_id")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValidationError("活动来源名称须为1至80字")
        if adapter not in ("astrbot", "harness", "sdk"):
            raise ValidationError("活动来源适配器不支持")
        if (not isinstance(runtime, str) or not runtime.strip() or runtime != runtime.strip()
                or len(runtime) > 200 or any(ord(c) < 32 for c in runtime)):
            raise ValidationError("请填写宿主中稳定的 Agent 标识，不能靠模型自报昵称")
        try:
            name.encode("utf-8"); runtime.encode("utf-8")
            platforms = validate_platforms(data.get("platforms", ["*"]))
            base_url = validate_base_url(base_url)
        except (SourceClientError, UnicodeError):
            raise ValidationError("活动来源的平台、地址或身份格式不正确") from None
        source_id = "source_" + uuid.uuid4().hex
        cid = "conn_" + uuid.uuid4().hex
        created = time.time()
        row = {"id": source_id, "connection_id": cid, "library_id": library_id, "name": name.strip(),
               "adapter": adapter, "runtime_agent_id": runtime, "platforms": json.dumps(platforms),
               "base_url": base_url, "created": created}
        private = self.directory / (source_id + ".json")
        connection = {"token": secrets.token_urlsafe(32), "enabled": True, "revoked": False}
        try:
            with self.connections.db() as db:
                db.execute("INSERT INTO connections(id,name,host,library_id,session_scope,token,enabled,revoked,created,last_received,archive_status,error) VALUES(?,?,?,?,?,?,1,0,?,NULL,'waiting',NULL)",
                           (cid, row["name"], "agent", library_id, "connection", connection["token"], created))
                db.execute("INSERT INTO agent_sources VALUES(?,?,?,?,?,?,?,?,?)", tuple(row[k] for k in (
                    "id", "connection_id", "library_id", "name", "adapter", "runtime_agent_id", "platforms", "base_url", "created")))
                _write_private_json(private, self._private(row, connection))
        except BaseException:
            private.unlink(missing_ok=True)
            raise
        return {"source": self.get(source_id), "private_path": str(private), "config_ready": True,
                "instructions": "在这个来源宿主所在机器加载私有配置文件；工具配置就绪不代表所有活动已接入。"}

    def configuration(self, source_id, *, base_url=None):
        row = self._row(source_id)
        connection = self.connections.get(row["connection_id"], secret=True)
        try:
            config = self._private(row, connection, base_url)
        except SourceClientError:
            raise ValidationError("来源配置不合法，未覆盖原配置") from None
        path = self.directory / (row["id"] + ".json")
        _write_private_json(path, config)
        if base_url:
            with self.connections.db() as db:
                db.execute("UPDATE agent_sources SET base_url=? WHERE id=?", (config["base_url"], row["id"]))
        return {"source": self.get(source_id), "private_path": str(path), "config_ready": True,
                "model_api_key_required": False, "same_machine_config": True,
                "instructions": "来源宿主加载此私有文件；不要将这台机器的路径直接搬到另一台服务器。"}

    def set_enabled(self, source_id, enabled, disconnect=False):
        row = self._row(source_id)
        self.connections.toggle(row["connection_id"], enabled, disconnect=disconnect)
        # Server revocation is already authoritative even if this file refresh
        # fails; the caller must report that local collector reload is pending.
        self.configuration(source_id)
        return self.get(source_id)

    def _registered(self, connection):
        with self.connections.db() as db:
            source = db.execute("SELECT * FROM agent_sources WHERE connection_id=?", (connection.get("id"),)).fetchone()
        if source is None: return None
        source = dict(source)
        if (connection.get("library_id") != source["library_id"] or connection.get("host") != "agent"
                or connection.get("revoked") or not connection.get("enabled")):
            raise ValidationError("活动来源不属于已启用的固定 Agent 身份")
        return source

    @staticmethod
    def _identity(source, data):
        expected = {"source_id": source["id"], "runtime_agent_id": source["runtime_agent_id"]}
        if not isinstance(data, dict) or any(data.get(k) != v for k, v in expected.items()):
            raise ValidationError("事件缺少匹配的宿主来源身份，原文未接收")
        for key in ("agent_id", "library_id"):
            if key in data and data[key] != source["library_id"]:
                raise ValidationError("活动身份不能选择其他 Agent 存档")

    def check_source_event(self, connection, event):
        source = self._registered(connection)
        if source is None: return  # The old single-window boundary is unchanged.
        self._identity(source, event)
        platforms = json.loads(source["platforms"])
        platform = event.get("platform")
        if not isinstance(platform, str) or not platform or (platforms != ["*"] and platform not in platforms):
            raise ValidationError("活动平台不属于此来源，原文未接收")
        record = event.get("record") if isinstance(event.get("record"), dict) else {}
        if record.get('source_adapter') not in (None,source['adapter']):
            raise ValidationError('活动适配器与登记来源不一致')
        if event.get("normalized") is not None and record.get("normalized") is not None:
            raise ValidationError("事件含多个语义入口，未猜测采用哪份")
        normalized = event.get("normalized", record.get("normalized"))
        for envelope in (record, normalized):
            if not isinstance(envelope, dict): continue
            for key, expected in (("source_id", source["id"]), ("runtime_agent_id", source["runtime_agent_id"]),
                                  ("agent_id", source["library_id"]), ("library_id", source["library_id"])):
                if key in envelope and envelope[key] != expected:
                    raise ValidationError("事件语义中的来源归属冲突，原文未接收")
        if normalized is not None:
            if (not isinstance(normalized, dict) or normalized.get("type") not in ("turn", "tool")
                    or normalized.get("status", "complete") not in ("partial", "complete")):
                raise ValidationError("当前来源只接完整对话或真实观察的既有语义，未把未知活动塞入重试")
            complete=normalized.get('status','complete')=='complete'
            fields=('user','assistant') if normalized['type']=='turn' else ('text',)
            for field in fields:
                value=normalized.get(field,'')
                if (not isinstance(value,str) or len(value)>40000 or complete and not value.strip()):
                    raise ValidationError('活动语义缺少有效的角色原文或实际观察')
                try:value.encode('utf-8')
                except UnicodeError:raise ValidationError('活动原文无法保存') from None
            if normalized['type']=='tool':
                if normalized.get('outcome','observed') not in ('observed','success','failed'):
                    raise ValidationError('实际观察状态不支持')
                if normalized.get('source_url'):
                    try:
                        p=urlsplit(normalized['source_url']);p.port
                        valid=p.scheme in ('http','https') and p.hostname and not p.username and not p.password
                    except (ValueError,TypeError):valid=False
                    if not valid:raise ValidationError('观察来源链接不合法')
            evidence=normalized.get('evidence')
            if evidence is not None:
                try:
                    if not isinstance(evidence,dict):raise ValueError()
                    encoded=json.dumps(evidence,ensure_ascii=False,allow_nan=False)
                    if len(encoded)>12000:raise ValueError()
                    encoded.encode('utf-8')
                except (ValueError,TypeError,UnicodeError,RecursionError):
                    raise ValidationError('活动证据结构无效或超过单条预算') from None
            stamp=event.get('occurred_at')
            if stamp is not None and (type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<0):
                raise ValidationError('活动发生时间不正确')
            if isinstance(evidence,dict):
                expected={'platform':platform,'source_id':source['id'],'source_runtime_agent_id':source['runtime_agent_id']}
                if any(k in evidence and evidence[k]!=v for k,v in expected.items()):
                    raise ValidationError('活动证据与已登记来源冲突')
                if 'source_event_at' in evidence:
                    recorded=evidence['source_event_at']
                    if (type(recorded) not in (int,float) or not math.isfinite(recorded)
                            or stamp is None or recorded!=stamp):
                        raise ValidationError('活动证据中的发生时间与来源事件不一致')
        return None

    def check_context(self, connection, data):
        source = self._registered(connection)
        if source is None: return data
        self._identity(source, data)
        allowed = {"source_id", "runtime_agent_id", "agent_id", "library_id", "query", "session_id", "max_chars"}
        if set(data) - allowed:
            raise ValidationError("来源记忆请求含未声明参数")
        return {k: data[k] for k in ("query", "session_id", "max_chars") if k in data}


Registry = AgentSourceRegistry
